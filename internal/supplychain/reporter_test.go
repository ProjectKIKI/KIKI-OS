package supplychain

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"reflect"
	"testing"
)

func TestReporterSendsOrderedAuthenticatedBuildPhases(t *testing.T) {
	var phases []string
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.URL.Path != "/api/v1/builds/build-0001/result" || request.Header.Get("Authorization") != "Bearer build-token" || request.Header.Get("X-Kiki-Actor") != "build-worker" {
			t.Error("invalid report request")
		}
		var report BuildReport
		_ = json.NewDecoder(request.Body).Decode(&report)
		phases = append(phases, report.Phase)
		response.Header().Set("Content-Type", "application/json")
		_, _ = response.Write([]byte(`{"phase":"ok"}`))
	}))
	defer server.Close()
	reporter := Reporter{BaseURL: server.URL, Token: "build-token", Actor: "build-worker", HTTP: server.Client()}
	if err := reporter.Advance(context.Background(), "build-0001", "Fetching", "Validating", "Building"); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(phases, []string{"Fetching", "Validating", "Building"}) {
		t.Fatalf("phases=%#v", phases)
	}
}
