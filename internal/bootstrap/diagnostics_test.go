package bootstrap

import (
	"context"
	"io"
	"net/http"
	"strings"
	"testing"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (fn roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) { return fn(request) }

func TestOpenAIDiagnosticRunner(t *testing.T) {
	client := &http.Client{Transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
		if request.URL.String() != "http://inference.kiki-system.svc/v1/chat/completions" {
			t.Fatalf("unexpected URL: %s", request.URL)
		}
		if request.Method != http.MethodPost || request.Header.Get("Content-Type") != "application/json" {
			t.Fatalf("unexpected request: %s %#v", request.Method, request.Header)
		}
		body, err := io.ReadAll(request.Body)
		if err != nil {
			t.Fatal(err)
		}
		if !strings.Contains(string(body), `"model":"ops-model"`) || !strings.Contains(string(body), "Do not suggest destructive actions") {
			t.Fatalf("unexpected request body: %s", body)
		}
		return &http.Response{
			StatusCode: http.StatusOK,
			Header:     make(http.Header),
			Body:       io.NopCloser(strings.NewReader(`{"choices":[{"message":{"content":" Check the mirror. "}}]}`)),
			Request:    request,
		}, nil
	})}
	runner := DiagnosticRunner{Endpoint: "http://inference.kiki-system.svc", Model: "ops-model", Client: client}
	provider, summary := runner.Diagnose(Node{Name: "node-01", Phase: "failed"})
	if provider != "openai-compatible" || summary != "Check the mirror." {
		t.Fatalf("unexpected diagnostic: %q %q", provider, summary)
	}
}

func TestDiagnosticRunnerFallsBack(t *testing.T) {
	client := &http.Client{Transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: http.StatusServiceUnavailable, Header: make(http.Header), Body: io.NopCloser(strings.NewReader("unavailable")), Request: request}, nil
	})}
	runner := DiagnosticRunner{Endpoint: "http://inference", Model: "ops", Client: client}
	provider, summary := runner.Diagnose(Node{Name: "node-01", Phase: "failed", LastError: "debootstrap failed"})
	if provider != "rules-fallback" || !strings.Contains(summary, "inference endpoint returned 503") || !strings.Contains(summary, "Last recorded error") {
		t.Fatalf("unexpected fallback: %q %q", provider, summary)
	}
}

func TestOpenAIRequestRejectsNonHTTPURL(t *testing.T) {
	runner := DiagnosticRunner{Endpoint: "file:///etc/passwd", Model: "ops"}
	if _, err := runner.openAIRequest(context.Background(), "prompt"); err == nil {
		t.Fatal("non-HTTP endpoint accepted")
	}
}
