package infraops

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"example.com/aos-pkg/internal/agent"
	"example.com/aos-pkg/internal/buildsystem"
)

const testRuntimeImage = "registry.local/runtime@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

func TestInfraOpsModelDeploymentFlow(t *testing.T) {
	statePath := filepath.Join(t.TempDir(), "state.json")
	store, err := NewStore(statePath, RuntimeImages{Llama: testRuntimeImage, VLLM: testRuntimeImage, Fetcher: testRuntimeImage})
	if err != nil {
		t.Fatal(err)
	}
	handler := NewServer(store, "secret-token")
	inventory := agent.Inventory{
		SchemaVersion: "kiki.io/inventory/v1alpha1", Hostname: "node-01",
		Memory:       agent.Memory{TotalBytes: 16 << 30, AvailableBytes: 12 << 30},
		CPU:          agent.CPUInventory{Architecture: "amd64", LogicalCores: 8},
		Accelerators: []agent.Accelerator{},
	}
	requestJSON(t, handler, http.MethodPut, "/api/v1/nodes/node-01/inventory", inventory, http.StatusOK)
	model := Model{
		Name: "ops-model", Digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		Format: "gguf", Source: "oci://registry.local/models/ops@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		SizeBytes: 4 << 30, MinimumMemoryBytes: 8 << 30, LicenseID: "apache-2.0", LicenseAccepted: true,
	}
	requestJSON(t, handler, http.MethodPost, "/api/v1/models", model, http.StatusCreated)
	deployment := DeploymentRequest{
		Name: "ops", Namespace: "kiki-system", ModelName: "ops-model", NodeName: "node-01",
		ModelPath: "/models/ops/model.gguf", CachePVC: "model-cache", Port: 8000, ContextLength: 8192,
	}
	recorder := requestJSON(t, handler, http.MethodPost, "/api/v1/model-deployments", deployment, http.StatusCreated)
	var created ModelDeployment
	if err := json.Unmarshal(recorder.Body.Bytes(), &created); err != nil {
		t.Fatal(err)
	}
	if created.Plan.Engine != "llama.cpp" || created.Plan.Backend != "cpu" || created.PodTemplate == nil {
		t.Fatalf("unexpected deployment: %#v", created)
	}
	if len(store.ListAudit()) != 3 {
		t.Fatalf("expected three audit records, got %#v", store.ListAudit())
	}

	reloaded, err := NewStore(statePath, RuntimeImages{Llama: testRuntimeImage, VLLM: testRuntimeImage, Fetcher: testRuntimeImage})
	if err != nil {
		t.Fatal(err)
	}
	if len(reloaded.ListDeployments()) != 1 || len(reloaded.ListAudit()) != 3 {
		t.Fatal("state was not persisted")
	}
}

func TestInfraOpsAuthenticationAndStrictJSON(t *testing.T) {
	store, err := NewStore(filepath.Join(t.TempDir(), "state.json"), RuntimeImages{})
	if err != nil {
		t.Fatal(err)
	}
	handler := NewServer(store, "secret-token")
	request := httptest.NewRequest(http.MethodGet, "/api/v1/models", nil)
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, request)
	if recorder.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d", recorder.Code)
	}

	request = httptest.NewRequest(http.MethodPost, "/api/v1/models", bytes.NewBufferString(`{"name":"model","unexpected":true}`))
	request.Header.Set("Authorization", "Bearer secret-token")
	request.Header.Set("X-Kiki-Actor", "tester")
	recorder = httptest.NewRecorder()
	handler.ServeHTTP(recorder, request)
	if recorder.Code != http.StatusBadRequest {
		t.Fatalf("strict JSON status = %d body=%s", recorder.Code, recorder.Body.String())
	}
}

func TestWebAssetsUseStrictContentSecurityPolicy(t *testing.T) {
	store, err := NewStore(filepath.Join(t.TempDir(), "state.json"), RuntimeImages{})
	if err != nil {
		t.Fatal(err)
	}
	handler := NewServer(store, "secret-token")
	for _, path := range []string{"/", "/static/app.css", "/static/recipe.css", "/static/app.js"} {
		request := httptest.NewRequest(http.MethodGet, path, nil)
		recorder := httptest.NewRecorder()
		handler.ServeHTTP(recorder, request)
		if recorder.Code != http.StatusOK {
			t.Fatalf("%s status=%d", path, recorder.Code)
		}
		if strings.Contains(recorder.Header().Get("Content-Security-Policy"), "unsafe-inline") {
			t.Fatal("unsafe inline CSP remains enabled")
		}
	}
}

func TestMetricsRequireViewerRoleAndExposePhaseCounts(t *testing.T) {
	store, err := NewStore(filepath.Join(t.TempDir(), "state.json"), RuntimeImages{})
	if err != nil {
		t.Fatal(err)
	}
	handler, err := NewServerWithPrincipals(store, []Principal{{Token: "viewer-token", Actor: "metrics", Roles: []string{"viewer"}}, {Token: "agent-token", Actor: "agent", Roles: []string{"agent"}}})
	if err != nil {
		t.Fatal(err)
	}
	request := httptest.NewRequest(http.MethodGet, "/metrics", nil)
	request.Header.Set("Authorization", "Bearer viewer-token")
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, request)
	if recorder.Code != http.StatusOK || !strings.Contains(recorder.Body.String(), "kiki_infraops_nodes 0") {
		t.Fatalf("metrics response: %d %s", recorder.Code, recorder.Body.String())
	}
	request = httptest.NewRequest(http.MethodGet, "/metrics", nil)
	request.Header.Set("Authorization", "Bearer agent-token")
	recorder = httptest.NewRecorder()
	handler.ServeHTTP(recorder, request)
	if recorder.Code != http.StatusForbidden {
		t.Fatalf("agent read metrics status=%d", recorder.Code)
	}
}

func TestModelNameIsImmutable(t *testing.T) {
	store, err := NewStore(filepath.Join(t.TempDir(), "state.json"), RuntimeImages{})
	if err != nil {
		t.Fatal(err)
	}
	model := Model{Name: "ops", Digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", Format: "gguf", Source: "oci://registry/ops", SizeBytes: 1, MinimumMemoryBytes: 1, LicenseID: "mit", LicenseAccepted: true}
	if _, err := store.CreateModel("tester", model); err != nil {
		t.Fatal(err)
	}
	model.Digest = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
	if _, err := store.CreateModel("tester", model); err == nil {
		t.Fatal("model digest mutation accepted")
	}
}

func TestBOSBuildLifecycle(t *testing.T) {
	statePath := filepath.Join(t.TempDir(), "state.json")
	config := buildsystem.Config{GitImage: testRuntimeImage, BOSBuilderImage: testRuntimeImage, SupplyChainImage: testRuntimeImage, AllowedGitHosts: []string{"git.example.com"}, EgressProxyURL: "http://proxy:8080", EgressProxyCIDR: "10.20.0.10/32", SigningSecret: "signing", BuildTokenSecret: "infraops-auth", InfraOpsURL: "http://kiki-infraops:8090"}
	store, err := NewStore(statePath, RuntimeImages{}, config)
	if err != nil {
		t.Fatal(err)
	}
	handler := NewServer(store, "secret-token")
	build := BuildRequest{
		ID: "build-0001", Type: "bos", Source: buildsystem.Source{URL: "https://git.example.com/kiki/packages.git", Revision: "cccccccccccccccccccccccccccccccccccccccc"},
		ContextPath: "packages/agent", OutputName: "kiki-agent.bos", ArtifactPVC: "build-artifacts", Platforms: []string{"linux/amd64"},
		Security: BuildSecurity{GenerateSBOM: true, GenerateProvenance: true, Sign: true},
	}
	recorder := requestJSON(t, handler, http.MethodPost, "/api/v1/builds", build, http.StatusCreated)
	var created Build
	if err := json.Unmarshal(recorder.Body.Bytes(), &created); err != nil {
		t.Fatal(err)
	}
	if created.Phase != "Queued" || created.Job["kind"] != "Job" {
		t.Fatalf("unexpected build: %#v", created)
	}
	for _, phase := range []string{"Fetching", "Validating", "Building", "Testing", "Scanning", "Signing", "Publishing"} {
		requestJSON(t, handler, http.MethodPut, "/api/v1/builds/build-0001/result", BuildResult{Phase: phase}, http.StatusOK)
	}
	result := BuildResult{Phase: "Succeeded", Digest: "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd", SizeBytes: 4096, MediaType: "application/vnd.kiki.bos.v1+gzip", SBOMDigest: "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee", ScanDigest: "sha256:2222222222222222222222222222222222222222222222222222222222222222", ProvenanceDigest: "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff", SignatureDigest: "sha256:1111111111111111111111111111111111111111111111111111111111111111"}
	requestJSON(t, handler, http.MethodPut, "/api/v1/builds/build-0001/result", result, http.StatusOK)
	if len(store.ListArtifacts()) != 1 || store.ListArtifacts()[0].BuildID != "build-0001" {
		t.Fatalf("artifact not published: %#v", store.ListArtifacts())
	}
	reloaded, err := NewStore(statePath, RuntimeImages{}, config)
	if err != nil {
		t.Fatal(err)
	}
	if len(reloaded.ListBuilds()) != 1 || reloaded.ListBuilds()[0].Phase != "Succeeded" {
		t.Fatal("build lifecycle was not persisted")
	}
}

func TestBOSRecipeCreatesSinglePackageJob(t *testing.T) {
	config := buildsystem.Config{BOSBuilderImage: testRuntimeImage, SupplyChainImage: testRuntimeImage, AllowedSourceHosts: []string{"sources.example.com"}, EgressProxyURL: "http://proxy:8080", EgressProxyCIDR: "10.20.0.10/32", SigningSecret: "signing", BuildTokenSecret: "reporter", InfraOpsURL: "http://infraops:8090"}
	store, err := NewStore(filepath.Join(t.TempDir(), "state.json"), RuntimeImages{}, config)
	if err != nil {
		t.Fatal(err)
	}
	request := BuildRequest{ID: "hello-recipe", Type: "bos", Source: buildsystem.Source{URL: "https://sources.example.com/hello.tar.gz", Revision: strings.Repeat("a", 64)}, OutputName: "hello-1.0-1.bos", ArtifactPVC: "artifacts", Platforms: []string{"linux/amd64"}, BOSRecipe: &BOSRecipeOptions{Name: "hello", Version: "1.0", Release: "1", Summary: "hello", License: "MIT", Install: []string{"install -Dm755 hello $DESTDIR/usr/bin/hello"}, Files: []string{"/usr/bin/hello"}}, Security: BuildSecurity{GenerateSBOM: true, GenerateProvenance: true, Sign: true}}
	build, err := store.CreateBuild("operator", request)
	if err != nil {
		t.Fatal(err)
	}
	init := build.Job["spec"].(map[string]any)["template"].(map[string]any)["spec"].(map[string]any)["initContainers"].([]any)
	if len(init) != 1 || init[0].(map[string]any)["name"] != "bos-recipe-build" {
		t.Fatalf("not a single-package Recipe Job: %#v", init)
	}
}

func TestBOSBuildRequiresSupplyChainEvidence(t *testing.T) {
	config := buildsystem.Config{GitImage: testRuntimeImage, BOSBuilderImage: testRuntimeImage, SupplyChainImage: testRuntimeImage, AllowedGitHosts: []string{"git.example.com"}, EgressProxyURL: "http://proxy:8080", EgressProxyCIDR: "10.20.0.10/32", SigningSecret: "signing", BuildTokenSecret: "infraops-auth", InfraOpsURL: "http://kiki-infraops:8090"}
	store, err := NewStore(filepath.Join(t.TempDir(), "state.json"), RuntimeImages{}, config)
	if err != nil {
		t.Fatal(err)
	}
	request := BuildRequest{ID: "build-0002", Type: "bos", Source: buildsystem.Source{URL: "https://git.example.com/pkg.git", Revision: "cccccccccccccccccccccccccccccccccccccccc"}, OutputName: "pkg.bos", ArtifactPVC: "artifacts", Platforms: []string{"linux/amd64"}}
	if _, err := store.CreateBuild("tester", request); err == nil {
		t.Fatal("build without supply-chain requirements accepted")
	}
}

func TestOCIBuildCreation(t *testing.T) {
	oci := buildsystem.OCIConfig{GitImage: testRuntimeImage, BuildctlImage: testRuntimeImage, SupplyChainImage: testRuntimeImage, AllowedGitHosts: []string{"git.example.com"}, AllowedRegistries: []string{"registry.example.com"}, BuildKitAddress: "tcp://buildkitd:1234", BuildKitCIDR: "10.30.0.20/32", BuildKitPort: 1234, EgressProxyURL: "http://proxy:8080", EgressProxyCIDR: "10.20.0.10/32", RegistryAuthSecret: "registry-auth", SigningSecret: "signing-key", BuildTokenSecret: "infraops-auth", InfraOpsURL: "http://kiki-infraops:8090"}
	store, err := NewStore(filepath.Join(t.TempDir(), "state.json"), RuntimeImages{}, buildsystem.Config{OCI: oci})
	if err != nil {
		t.Fatal(err)
	}
	request := BuildRequest{ID: "build-oci-1", Type: "cpm", Source: buildsystem.Source{URL: "https://git.example.com/kiki/app.git", Revision: "cccccccccccccccccccccccccccccccccccccccc"}, ContextPath: "app", DefinitionPath: "Containerfile", Destination: "registry.example.com/kiki/app", ArtifactPVC: "artifacts", Platforms: []string{"linux/amd64"}, Security: BuildSecurity{GenerateSBOM: true, GenerateProvenance: true, Sign: true}}
	build, err := store.CreateBuild("tester", request)
	if err != nil {
		t.Fatal(err)
	}
	if build.Job["kind"] != "Job" || build.NetworkPolicy["kind"] != "NetworkPolicy" {
		t.Fatalf("OCI resources missing: %#v", build)
	}
	jobSpec := build.Job["spec"].(map[string]any)["template"].(map[string]any)["spec"].(map[string]any)
	if len(jobSpec["initContainers"].([]any)) != 3 {
		t.Fatal("OCI pipeline does not include clone, checkout, and BuildKit")
	}
}

func TestModelBuildCreation(t *testing.T) {
	modelConfig := buildsystem.ModelConfig{GitImage: testRuntimeImage, BuilderImage: testRuntimeImage, SupplyChainImage: testRuntimeImage, AllowedGitHosts: []string{"git.example.com"}, AllowedRegistries: []string{"registry.example.com"}, EgressProxyURL: "http://proxy:8080", EgressProxyCIDR: "10.20.0.10/32", RegistryAuthSecret: "registry-auth", SigningSecret: "signing", BuildTokenSecret: "infraops-auth", InfraOpsURL: "http://kiki-infraops:8090"}
	store, err := NewStore(filepath.Join(t.TempDir(), "state.json"), RuntimeImages{}, buildsystem.Config{Model: modelConfig})
	if err != nil {
		t.Fatal(err)
	}
	request := BuildRequest{ID: "model-build-1", Type: "model", Source: buildsystem.Source{URL: "https://git.example.com/models/ops.git", Revision: "cccccccccccccccccccccccccccccccccccccccc"}, ContextPath: "model", Destination: "registry.example.com/models/ops", OutputName: "ops-model", ArtifactPVC: "artifacts", ModelBuild: &ModelBuildOptions{InputPath: "weights/model.gguf", InputFormat: "gguf", OutputFormat: "gguf", Quantization: "q4_k_m", LicenseID: "Apache-2.0"}, Security: BuildSecurity{GenerateSBOM: true, GenerateProvenance: true, Sign: true}}
	build, err := store.CreateBuild("operator", request)
	if err != nil {
		t.Fatal(err)
	}
	if build.Job["kind"] != "Job" || build.NetworkPolicy["kind"] != "NetworkPolicy" {
		t.Fatalf("model build resources missing: %#v", build)
	}
	jobSpec := build.Job["spec"].(map[string]any)["template"].(map[string]any)["spec"].(map[string]any)
	if jobSpec["nodeSelector"].(map[string]any)["kiki.io/model-builder"] != "true" {
		t.Fatal("model build was not isolated")
	}
}

func TestImageFactoryBuildIsClaimedWithoutGeneralNodeJob(t *testing.T) {
	config := buildsystem.Config{AllowedGitHosts: []string{"git.example.com"}}
	store, err := NewStore(filepath.Join(t.TempDir(), "state.json"), RuntimeImages{}, config)
	if err != nil {
		t.Fatal(err)
	}
	handler := NewServer(store, "secret-token")
	request := BuildRequest{
		ID: "image-0001", Type: "iso",
		Source:     buildsystem.Source{URL: "https://git.example.com/kiki/os.git", Revision: "aabbccddaabbccddaabbccddaabbccddaabbccdd"},
		OutputName: "kiki-os.iso",
		Factory:    &FactoryOptions{Release: "v3.20", Arch: "x86_64", BootModes: []string{"bios", "uefi"}},
		Security:   BuildSecurity{GenerateSBOM: true, GenerateProvenance: true, Sign: true},
	}
	recorder := requestJSON(t, handler, http.MethodPost, "/api/v1/builds", request, http.StatusCreated)
	var created Build
	if err := json.Unmarshal(recorder.Body.Bytes(), &created); err != nil {
		t.Fatal(err)
	}
	if created.Job != nil || created.NetworkPolicy != nil || created.FactoryTask == nil || created.FactoryTask.Isolation.GeneralNodeAllowed {
		t.Fatalf("image build escaped factory boundary: %#v", created)
	}
	recorder = requestJSON(t, handler, http.MethodPost, "/api/v1/image-factory/claim", map[string][]string{"types": []string{"iso"}}, http.StatusOK)
	var claimed Build
	if err := json.Unmarshal(recorder.Body.Bytes(), &claimed); err != nil {
		t.Fatal(err)
	}
	if claimed.ID != request.ID || claimed.Phase != "Fetching" || claimed.FactoryTask == nil {
		t.Fatalf("unexpected claim: %#v", claimed)
	}
	requestJSON(t, handler, http.MethodPost, "/api/v1/image-factory/claim", map[string][]string{"types": []string{"iso"}}, http.StatusNotFound)
}

func TestScopedPrincipalsCannotCrossControlPlaneBoundaries(t *testing.T) {
	config := buildsystem.Config{GitImage: testRuntimeImage, BOSBuilderImage: testRuntimeImage, SupplyChainImage: testRuntimeImage, AllowedGitHosts: []string{"git.example.com"}, EgressProxyURL: "http://proxy:8080", EgressProxyCIDR: "10.20.0.10/32", SigningSecret: "signing", BuildTokenSecret: "infraops-auth", InfraOpsURL: "http://kiki-infraops:8090"}
	store, err := NewStore(filepath.Join(t.TempDir(), "state.json"), RuntimeImages{}, config)
	if err != nil {
		t.Fatal(err)
	}
	_, err = store.CreateBuild("admin", BuildRequest{ID: "image-scope-1", Type: "iso", Source: buildsystem.Source{URL: "https://git.example.com/kiki/os.git", Revision: "aabbccddaabbccddaabbccddaabbccddaabbccdd"}, OutputName: "kiki.iso", Factory: &FactoryOptions{Release: "v3.20", Arch: "x86_64", BootModes: []string{"bios"}}, Security: BuildSecurity{GenerateSBOM: true, GenerateProvenance: true, Sign: true}})
	if err != nil {
		t.Fatal(err)
	}
	_, err = store.CreateBuild("admin", BuildRequest{ID: "bos-scope-1", Type: "bos", Source: buildsystem.Source{URL: "https://git.example.com/kiki/pkg.git", Revision: "aabbccddaabbccddaabbccddaabbccddaabbccdd"}, ContextPath: "pkg", OutputName: "pkg.bos", ArtifactPVC: "artifacts", Platforms: []string{"linux/amd64"}, Security: BuildSecurity{GenerateSBOM: true, GenerateProvenance: true, Sign: true}})
	if err != nil {
		t.Fatal(err)
	}
	handler, err := NewServerWithPrincipals(store, []Principal{{Token: "agent-token", Actor: "kiki-agent", Roles: []string{"agent"}}, {Token: "factory-token", Actor: "image-factory", Roles: []string{"image-factory"}}, {Token: "build-token", Actor: "build-worker", Roles: []string{"build-worker"}}})
	if err != nil {
		t.Fatal(err)
	}
	inventory := agent.Inventory{SchemaVersion: "kiki.io/inventory/v1alpha1", Hostname: "node-01", CPU: agent.CPUInventory{Architecture: "amd64", LogicalCores: 4}, Memory: agent.Memory{TotalBytes: 8 << 30}}
	requestJSONAs(t, handler, http.MethodPut, "/api/v1/nodes/node-01/inventory", inventory, "agent-token", "kiki-agent", http.StatusOK)
	requestJSONAs(t, handler, http.MethodGet, "/api/v1/models", nil, "agent-token", "kiki-agent", http.StatusForbidden)
	requestJSONAs(t, handler, http.MethodPost, "/api/v1/image-factory/claim", map[string][]string{"types": []string{"iso"}}, "factory-token", "image-factory", http.StatusOK)
	requestJSONAs(t, handler, http.MethodPut, "/api/v1/builds/image-scope-1/result", BuildResult{Phase: "Validating"}, "factory-token", "spoofed-actor", http.StatusForbidden)
	requestJSONAs(t, handler, http.MethodGet, "/api/v1/models", nil, "factory-token", "image-factory", http.StatusForbidden)
	requestJSONAs(t, handler, http.MethodPut, "/api/v1/builds/bos-scope-1/result", BuildResult{Phase: "Fetching"}, "build-token", "build-worker", http.StatusOK)
	requestJSONAs(t, handler, http.MethodPut, "/api/v1/builds/image-scope-1/result", BuildResult{Phase: "Validating"}, "build-token", "build-worker", http.StatusForbidden)
}

func TestTwoPartyTaskApprovalClaimAndCompletion(t *testing.T) {
	store, err := NewStore(filepath.Join(t.TempDir(), "state.json"), RuntimeImages{})
	if err != nil {
		t.Fatal(err)
	}
	handler, err := NewServerWithPrincipals(store, []Principal{
		{Token: "alice-token", Actor: "alice", Roles: []string{"operator"}},
		{Token: "bob-token", Actor: "bob", Roles: []string{"operator"}},
		{Token: "carol-token", Actor: "carol", Roles: []string{"operator"}},
		{Token: "agent-token", Actor: "kiki-agent", Roles: []string{"agent"}},
	})
	if err != nil {
		t.Fatal(err)
	}
	task := TaskRequest{ID: "task-0001", IdempotencyKey: "idem-0001", Action: agent.ActionRuntimeRestart, TargetNode: "node-01", Parameters: json.RawMessage(`{"deployment_id":"project/model"}`), Approval: agent.ApprovalTwoParty, ExpiresAt: time.Now().Add(time.Hour)}
	requestJSONAs(t, handler, http.MethodPost, "/api/v1/tasks", task, "alice-token", "alice", http.StatusCreated)
	capabilities := map[string][]agent.TaskAction{"actions": []agent.TaskAction{agent.ActionRuntimeRestart}}
	requestJSONAs(t, handler, http.MethodPost, "/api/v1/nodes/node-01/tasks/claim", capabilities, "agent-token", "kiki-agent", http.StatusNotFound)
	requestJSONAs(t, handler, http.MethodPost, "/api/v1/tasks/task-0001/approve", nil, "alice-token", "alice", http.StatusBadRequest)
	requestJSONAs(t, handler, http.MethodPost, "/api/v1/tasks/task-0001/approve", nil, "bob-token", "bob", http.StatusOK)
	requestJSONAs(t, handler, http.MethodPost, "/api/v1/nodes/node-01/tasks/claim", capabilities, "agent-token", "kiki-agent", http.StatusNotFound)
	requestJSONAs(t, handler, http.MethodPost, "/api/v1/tasks/task-0001/approve", nil, "carol-token", "carol", http.StatusOK)
	recorder := requestJSONAs(t, handler, http.MethodPost, "/api/v1/nodes/node-01/tasks/claim", capabilities, "agent-token", "kiki-agent", http.StatusOK)
	var claimed ManagedTask
	if err := json.Unmarshal(recorder.Body.Bytes(), &claimed); err != nil {
		t.Fatal(err)
	}
	if claimed.State != agent.TaskRunning || claimed.ClaimedBy != "node-01" {
		t.Fatalf("unexpected claim: %#v", claimed)
	}
	requestJSONAs(t, handler, http.MethodPut, "/api/v1/nodes/node-02/tasks/task-0001/result", TaskResult{State: agent.TaskSucceeded}, "agent-token", "kiki-agent", http.StatusBadRequest)
	requestJSONAs(t, handler, http.MethodPut, "/api/v1/nodes/node-01/tasks/task-0001/result", TaskResult{State: agent.TaskSucceeded, Output: json.RawMessage(`{"restarted":true}`)}, "agent-token", "kiki-agent", http.StatusOK)
	if store.ListTasks()[0].State != agent.TaskSucceeded {
		t.Fatal("task did not reach terminal state")
	}
}

func requestJSON(t *testing.T, handler http.Handler, method, path string, value any, status int) *httptest.ResponseRecorder {
	t.Helper()
	data, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	request := httptest.NewRequest(method, path, bytes.NewReader(data))
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Authorization", "Bearer secret-token")
	request.Header.Set("X-Kiki-Actor", "tester")
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, request)
	if recorder.Code != status {
		t.Fatalf("%s %s status=%d body=%s", method, path, recorder.Code, recorder.Body.String())
	}
	return recorder
}

func requestJSONAs(t *testing.T, handler http.Handler, method, path string, value any, token, actor string, status int) *httptest.ResponseRecorder {
	t.Helper()
	data, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	request := httptest.NewRequest(method, path, bytes.NewReader(data))
	request.Header.Set("Authorization", "Bearer "+token)
	request.Header.Set("X-Kiki-Actor", actor)
	request.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, request)
	if recorder.Code != status {
		t.Fatalf("%s %s status=%d body=%s", method, path, recorder.Code, recorder.Body.String())
	}
	return recorder
}
