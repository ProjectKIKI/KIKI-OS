package bootstrap

import (
	"bytes"
	"encoding/json"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const testAdminToken = "stage3-admin-token"

func TestAuthenticatedBootstrapLifecycle(t *testing.T) {
	statePath := filepath.Join(t.TempDir(), "state.json")
	store, err := NewStore(statePath)
	if err != nil {
		t.Fatal(err)
	}
	artifactsDir := t.TempDir()
	if err := os.WriteFile(filepath.Join(artifactsDir, "kiki.iso"), []byte("iso"), 0o644); err != nil {
		t.Fatal(err)
	}
	handler := NewServerWithOptions(store, artifactsDir, ServerOptions{RequireRegistrationToken: true, AdminToken: testAdminToken, MaxUploadBytes: 1024, Diagnostics: DiagnosticRunner{}})

	requestJSON(t, handler, http.MethodGet, "/api/v1/nodes", nil, "", http.StatusUnauthorized, nil)
	var issued IssuedToken
	requestJSON(t, handler, http.MethodPost, "/api/v1/tokens", map[string]any{"nodeName": "kiki-node-test", "ttlSeconds": 3600}, testAdminToken, http.StatusCreated, &issued)
	if issued.Token == "" {
		t.Fatal("registration token was not returned")
	}

	registration := registrationPayload("kiki-node-test", "installing")
	registration["spec"].(map[string]any)["registrationToken"] = issued.Token
	var result RegistrationResult
	requestJSON(t, handler, http.MethodPost, "/api/v1/nodes/register", registration, "", http.StatusOK, &result)
	if result.Node != "kiki-node-test" || result.NodeToken == "" {
		t.Fatalf("unexpected registration result: %#v", result)
	}

	reused := registrationPayload("kiki-node-test", "installing")
	reused["spec"].(map[string]any)["registrationToken"] = issued.Token
	requestJSON(t, handler, http.MethodPost, "/api/v1/nodes/register", reused, "", http.StatusUnauthorized, nil)
	requestJSON(t, handler, http.MethodPost, "/api/v1/nodes/register", registrationPayload("kiki-node-test", "installed"), result.NodeToken, http.StatusOK, nil)

	heartbeat := map[string]any{"metadata": map[string]any{"name": "kiki-node-test"}, "spec": map[string]any{"role": "controller", "clusterRef": map[string]any{"name": "lab"}}}
	requestJSON(t, handler, http.MethodPost, "/api/v1/nodes/heartbeat", heartbeat, "", http.StatusUnauthorized, nil)
	otherHeartbeat := map[string]any{"metadata": map[string]any{"name": "other-node"}, "spec": map[string]any{}}
	requestJSON(t, handler, http.MethodPost, "/api/v1/nodes/heartbeat", otherHeartbeat, result.NodeToken, http.StatusUnauthorized, nil)
	requestJSON(t, handler, http.MethodPost, "/api/v1/nodes/heartbeat", heartbeat, result.NodeToken, http.StatusOK, nil)

	postMultipartBundle(t, handler, "/api/v1/nodes/log-bundles", "kiki-node-test", "bundle.tar.gz", []byte("logs"), result.NodeToken, http.StatusCreated)
	postMultipartBundle(t, handler, "/api/v1/nodes/log-bundles", "kiki-node-test", "large.tar.gz", bytes.Repeat([]byte("x"), 2048), result.NodeToken, http.StatusRequestEntityTooLarge)
	requestJSON(t, handler, http.MethodPost, "/api/v1/nodes/kiki-node-test/diagnose", map[string]any{}, testAdminToken, http.StatusCreated, nil)

	var node Node
	requestJSON(t, handler, http.MethodGet, "/api/v1/nodes/kiki-node-test", nil, testAdminToken, http.StatusOK, &node)
	if node.Phase != "booted" || node.LastHeartbeatAt == "" || len(node.Diagnostics) == 0 {
		t.Fatalf("unexpected node state: %#v", node)
	}
	var artifacts []Artifact
	requestJSON(t, handler, http.MethodGet, "/api/v1/artifacts", nil, testAdminToken, http.StatusOK, &artifacts)
	if len(artifacts) != 2 {
		t.Fatalf("expected ISO and one accepted log bundle, got %#v", artifacts)
	}

	state, err := os.ReadFile(statePath)
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(state, []byte(issued.Token)) || bytes.Contains(state, []byte(result.NodeToken)) {
		t.Fatal("plaintext credential was persisted")
	}
	reloaded, err := NewStore(statePath)
	if err != nil {
		t.Fatal(err)
	}
	reloadedHandler := NewServerWithOptions(reloaded, artifactsDir, ServerOptions{RequireRegistrationToken: true, AdminToken: testAdminToken})
	requestJSON(t, reloadedHandler, http.MethodPost, "/api/v1/nodes/heartbeat", heartbeat, result.NodeToken, http.StatusOK, nil)
}

func TestDashboardSupportsAuthenticatedManagementAPI(t *testing.T) {
	store, err := NewStore(filepath.Join(t.TempDir(), "state.json"))
	if err != nil {
		t.Fatal(err)
	}
	handler := NewServerWithOptions(store, t.TempDir(), ServerOptions{AdminToken: testAdminToken})
	request := httptest.NewRequest(http.MethodGet, "/", nil)
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, request)
	if recorder.Code != http.StatusOK {
		t.Fatalf("dashboard status = %d", recorder.Code)
	}
	if recorder.Header().Get("Content-Security-Policy") == "" || !strings.Contains(recorder.Body.String(), "sessionStorage") || !strings.Contains(recorder.Body.String(), "escapeHTML") {
		t.Fatal("dashboard is missing authenticated API or output-escaping support")
	}
}

func TestRegistrationTokenIsBoundToIssuedNode(t *testing.T) {
	store, err := NewStore(filepath.Join(t.TempDir(), "state.json"))
	if err != nil {
		t.Fatal(err)
	}
	issued, err := store.CreateToken("node-a", 60)
	if err != nil {
		t.Fatal(err)
	}
	payload := registrationPayload("node-b", "installing")
	payload["spec"].(map[string]any)["registrationToken"] = issued.Token
	if _, err := store.RegisterNode(payload, "", true); err == nil || !strings.Contains(err.Error(), "another node") {
		t.Fatalf("node-bound token was accepted: %v", err)
	}
}

func registrationPayload(name, phase string) map[string]any {
	return map[string]any{
		"apiVersion": "kiki.io/v1alpha1", "kind": "KikiNodeRegistration", "metadata": map[string]any{"name": name},
		"spec": map[string]any{
			"phase": phase, "role": "controller", "clusterRef": map[string]any{"name": "lab"},
			"storage": map[string]any{"disk": "/dev/sda", "bootMode": "bios", "rootFs": "ext4"},
			"os":      map[string]any{"distribution": "debian", "release": "bookworm", "architecture": "amd64"},
		},
	}
}

func requestJSON(t *testing.T, handler http.Handler, method, path string, payload any, token string, wantStatus int, target any) {
	t.Helper()
	var body io.Reader
	if payload != nil {
		data, err := json.Marshal(payload)
		if err != nil {
			t.Fatal(err)
		}
		body = bytes.NewReader(data)
	}
	request := httptest.NewRequest(method, path, body)
	request.Header.Set("Content-Type", "application/json")
	if token != "" {
		request.Header.Set("Authorization", "Bearer "+token)
	}
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, request)
	if recorder.Code != wantStatus {
		t.Fatalf("%s %s status = %d, want %d: %s", method, path, recorder.Code, wantStatus, recorder.Body.String())
	}
	if target != nil {
		if err := json.NewDecoder(recorder.Body).Decode(target); err != nil {
			t.Fatal(err)
		}
	}
}

func postMultipartBundle(t *testing.T, handler http.Handler, path, nodeName, filename string, content []byte, token string, wantStatus int) {
	t.Helper()
	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	if err := writer.WriteField("nodeName", nodeName); err != nil {
		t.Fatal(err)
	}
	part, err := writer.CreateFormFile("bundle", filename)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := part.Write(content); err != nil {
		t.Fatal(err)
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	request := httptest.NewRequest(http.MethodPost, path, &body)
	request.Header.Set("Content-Type", writer.FormDataContentType())
	request.Header.Set("Authorization", "Bearer "+token)
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, request)
	if recorder.Code != wantStatus {
		t.Fatalf("multipart status = %d, want %d: %s", recorder.Code, wantStatus, recorder.Body.String())
	}
}
