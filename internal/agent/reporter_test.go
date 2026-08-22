package agent

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestReporterSendsAuthenticatedNodeInventory(t *testing.T) {
	called := false
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		called = true
		if request.Method != http.MethodPut || request.URL.Path != "/api/v1/nodes/node-01/inventory" {
			t.Errorf("unexpected request: %s %s", request.Method, request.URL.Path)
		}
		if request.Header.Get("Authorization") != "Bearer node-token" || request.Header.Get("X-Kiki-Actor") != "kiki-agent/node-01" {
			t.Error("agent identity headers missing")
		}
		response.Header().Set("Content-Type", "application/json")
		_, _ = response.Write([]byte(`{"name":"node-01"}`))
	}))
	defer server.Close()
	reporter := Reporter{BaseURL: server.URL, Token: "node-token", NodeName: "node-01", HTTP: server.Client(), Collect: func() (Inventory, error) {
		return Inventory{SchemaVersion: "kiki.io/inventory/v1alpha1", CollectedAt: time.Now(), Hostname: "node-01"}, nil
	}}
	if err := reporter.Report(context.Background()); err != nil {
		t.Fatal(err)
	}
	if !called {
		t.Fatal("inventory endpoint was not called")
	}
}

func TestReporterClaimsOnlyDiagnosticsAndCompletesIt(t *testing.T) {
	var result struct {
		State  TaskState       `json:"state"`
		Output json.RawMessage `json:"output"`
	}
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		response.Header().Set("Content-Type", "application/json")
		switch request.URL.Path {
		case "/api/v1/nodes/node-01/tasks/claim":
			var claim map[string][]TaskAction
			_ = json.NewDecoder(request.Body).Decode(&claim)
			if len(claim["actions"]) != 1 || claim["actions"][0] != ActionDiagnosticCollect {
				t.Error("unsafe capability claim")
			}
			_ = json.NewEncoder(response).Encode(Task{APIVersion: "infraops.kiki.io/v1alpha1", ID: "task-0001", Action: ActionDiagnosticCollect, TargetNode: "node-01", State: TaskRunning})
		case "/api/v1/nodes/node-01/tasks/task-0001/result":
			_ = json.NewDecoder(request.Body).Decode(&result)
			_ = json.NewEncoder(response).Encode(map[string]string{"state": "Succeeded"})
		default:
			http.NotFound(response, request)
		}
	}))
	defer server.Close()
	reporter := Reporter{BaseURL: server.URL, Token: "token", Actor: "kiki-agent", NodeName: "node-01", HTTP: server.Client(), Collect: func() (Inventory, error) {
		return Inventory{SchemaVersion: "kiki.io/inventory/v1alpha1", Hostname: "node-01"}, nil
	}}
	if err := reporter.ProcessTask(context.Background()); err != nil {
		t.Fatal(err)
	}
	if result.State != TaskSucceeded || len(result.Output) == 0 {
		t.Fatalf("unexpected diagnostic result: %#v", result)
	}
}
