package main

import (
	"bytes"
	"context"
	"net/http"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"example.com/aos-pkg/internal/aiconsole"
)

func TestRenderPlanShowsExactExecutionContext(t *testing.T) {
	plan := aiconsole.Plan{
		Schema:         aiconsole.PlanSchema,
		SummaryKO:      "설정 변경",
		Risk:           "network",
		ImpactKO:       "연결이 변경될 수 있음",
		ConfirmationKO: "명령을 확인했습니까?",
		Commands: []aiconsole.Command{{
			DescriptionKO: "설정 쓰기",
			Argv:          []string{"/bin/sh", "-c", "printf '%s' ok"},
			Directory:     "/etc",
			Environment:   map[string]string{"LANG": "ko_KR.UTF-8"},
		}},
	}
	var output bytes.Buffer
	renderPlan(&output, plan)
	for _, expected := range []string{
		"위험 등급: network",
		`$ /bin/sh -c 'printf '\''%s'\'' ok'`,
		"작업 경로: /etc",
		"환경 변수: LANG=ko_KR.UTF-8",
	} {
		if !strings.Contains(output.String(), expected) {
			t.Fatalf("rendered plan missing %q:\n%s", expected, output.String())
		}
	}
}

func TestLoopbackEndpointDetection(t *testing.T) {
	for _, endpoint := range []string{
		"http://127.0.0.1:8080/v1/chat/completions",
		"http://[::1]:8080/v1/chat/completions",
		"http://localhost:8080/v1/chat/completions",
	} {
		if !isLoopbackEndpoint(endpoint) {
			t.Fatalf("%q should be detected as loopback", endpoint)
		}
	}
	if isLoopbackEndpoint("https://ai.example/v1/chat/completions") {
		t.Fatal("remote endpoint must not be detected as loopback")
	}
}

func TestWaitForRuntimeRetriesUntilHealthy(t *testing.T) {
	var requests atomic.Int32
	client := &http.Client{Transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
		if request.URL.Path != "/health" {
			t.Fatalf("health path = %q", request.URL.Path)
		}
		status := http.StatusOK
		if requests.Add(1) == 1 {
			status = http.StatusServiceUnavailable
		}
		return &http.Response{StatusCode: status, Body: http.NoBody, Header: make(http.Header)}, nil
	})}

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if err := waitForRuntimeWithClient(ctx, "http://127.0.0.1:8080/v1/chat/completions", client, time.Millisecond); err != nil {
		t.Fatal(err)
	}
	if requests.Load() < 2 {
		t.Fatalf("requests = %d, want at least 2", requests.Load())
	}
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (function roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) {
	return function(request)
}
