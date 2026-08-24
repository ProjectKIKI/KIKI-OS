package stage3

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/pem"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (function roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) {
	return function(request)
}

func TestFetchRemotePlanVerifiesBeforePromotion(t *testing.T) {
	data := []byte("install_plan:\n  schema: kiki-install-plan-v1\n")
	digest := sha256.Sum256(data)
	directory := t.TempDir()
	client := &http.Client{Transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: http.StatusOK, Body: io.NopCloser(strings.NewReader(string(data))), Header: make(http.Header), Request: request}, nil
	})}
	result, err := FetchRemotePlan(context.Background(), RemotePlanOptions{
		URL:            "https://repo.example/kiki/install-plan.yaml",
		SHA256:         fmt.Sprintf("%x", digest),
		DownloadedPath: filepath.Join(directory, "remote.yaml"),
		VerifiedPath:   filepath.Join(directory, "install.yaml"),
		Client:         client,
	})
	if err != nil {
		t.Fatal(err)
	}
	if !result.Verified || result.Size != int64(len(data)) {
		t.Fatalf("result = %+v", result)
	}
	verified, err := os.ReadFile(result.VerifiedPath)
	if err != nil || string(verified) != string(data) {
		t.Fatalf("verified plan = %q, err=%v", verified, err)
	}
}

func TestFetchRemotePlanDoesNotPromoteDigestMismatch(t *testing.T) {
	directory := t.TempDir()
	client := &http.Client{Transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: http.StatusOK, Body: io.NopCloser(strings.NewReader("plan\n")), Header: make(http.Header), Request: request}, nil
	})}
	verified := filepath.Join(directory, "install.yaml")
	_, err := FetchRemotePlan(context.Background(), RemotePlanOptions{URL: "https://repo.example/plan.yaml", SHA256: strings.Repeat("a", 64), DownloadedPath: filepath.Join(directory, "remote.yaml"), VerifiedPath: verified, Client: client})
	if err == nil || !strings.Contains(err.Error(), "verification failed") {
		t.Fatalf("error = %v", err)
	}
	if _, statErr := os.Stat(verified); !os.IsNotExist(statErr) {
		t.Fatalf("unverified plan was promoted: %v", statErr)
	}
}

func TestFetchRemotePlanRejectsUnverifiedByDefault(t *testing.T) {
	_, err := FetchRemotePlan(context.Background(), RemotePlanOptions{URL: "https://repo.example/plan.yaml", DownloadedPath: "/tmp/remote", VerifiedPath: "/tmp/verified"})
	if err == nil || !strings.Contains(err.Error(), "requires sha256 or Ed25519") {
		t.Fatalf("error = %v", err)
	}
}

func TestFetchRemotePlanVerifiesEd25519Signature(t *testing.T) {
	data := []byte("install_plan:\n  schema: kiki-install-plan-v1\n")
	publicKey, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	directory := t.TempDir()
	publicKeyPath := writeTestPublicKey(t, directory, publicKey)
	client := &http.Client{Transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: http.StatusOK, Body: io.NopCloser(strings.NewReader(string(data))), Header: make(http.Header), Request: request}, nil
	})}
	result, err := FetchRemotePlan(context.Background(), RemotePlanOptions{
		URL:            "https://repo.example/kiki/install-plan.yaml",
		Signature:      "base64:" + base64.StdEncoding.EncodeToString(ed25519.Sign(privateKey, data)),
		PublicKeyPath:  publicKeyPath,
		DownloadedPath: filepath.Join(directory, "remote.yaml"),
		VerifiedPath:   filepath.Join(directory, "install.yaml"),
		Client:         client,
	})
	if err != nil {
		t.Fatal(err)
	}
	if !result.Verified || !result.SignatureVerified || result.VerificationMethod != "ed25519" {
		t.Fatalf("result = %+v", result)
	}
}

func TestFetchRemotePlanRejectsInvalidEd25519Signature(t *testing.T) {
	data := []byte("plan: expected\n")
	publicKey, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	directory := t.TempDir()
	client := &http.Client{Transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: http.StatusOK, Body: io.NopCloser(strings.NewReader("plan: tampered\n")), Header: make(http.Header), Request: request}, nil
	})}
	verified := filepath.Join(directory, "install.yaml")
	_, err = FetchRemotePlan(context.Background(), RemotePlanOptions{
		URL:            "https://repo.example/plan.yaml",
		Signature:      base64.StdEncoding.EncodeToString(ed25519.Sign(privateKey, data)),
		PublicKeyPath:  writeTestPublicKey(t, directory, publicKey),
		DownloadedPath: filepath.Join(directory, "remote.yaml"),
		VerifiedPath:   verified,
		Client:         client,
	})
	if err == nil || !strings.Contains(err.Error(), "signature verification failed") {
		t.Fatalf("error = %v", err)
	}
	if _, statErr := os.Stat(verified); !os.IsNotExist(statErr) {
		t.Fatalf("invalidly signed plan was promoted: %v", statErr)
	}
}

func TestParsePlanKernelParameters(t *testing.T) {
	values := ParsePlanKernelParameters("quiet kiki.plan.url=https://repo.example/plan.yaml kiki.plan.sha256=abc kiki.plan.signature=https://repo.example/plan.yaml.sig console=ttyS0")
	if values["kiki.plan.url"] != "https://repo.example/plan.yaml" || values["kiki.plan.sha256"] != "abc" || values["kiki.plan.signature"] != "https://repo.example/plan.yaml.sig" {
		t.Fatalf("values = %#v", values)
	}
}

func writeTestPublicKey(t *testing.T, directory string, publicKey ed25519.PublicKey) string {
	t.Helper()
	der, err := x509.MarshalPKIXPublicKey(publicKey)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(directory, "install-plan.ed25519.pub")
	if err := os.WriteFile(path, pem.EncodeToMemory(&pem.Block{Type: "PUBLIC KEY", Bytes: der}), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}
