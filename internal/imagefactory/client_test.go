package imagefactory

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"reflect"
	"testing"

	"example.com/aos-pkg/internal/buildsystem"
)

func TestClientClaimsAndReportsWithWorkerIdentity(t *testing.T) {
	task, err := CreateTask(Request{BuildID: "image-0001", Type: "iso", Source: buildsystem.Source{URL: "https://git.example.com/kiki/os.git", Revision: "aabbccddaabbccddaabbccddaabbccddaabbccdd"}, Release: "v3.20", Arch: "x86_64", BootModes: []string{"bios"}, OutputName: "kiki.iso"}, []string{"git.example.com"})
	if err != nil {
		t.Fatal(err)
	}
	var paths []string
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.Header.Get("Authorization") != "Bearer factory-token" || request.Header.Get("X-Kiki-Actor") != "factory-01" {
			t.Error("worker credentials were not sent")
		}
		paths = append(paths, request.Method+" "+request.URL.Path)
		response.Header().Set("Content-Type", "application/json")
		if request.URL.Path == "/api/v1/image-factory/claim" {
			_ = json.NewEncoder(response).Encode(ClaimedBuild{ID: "image-0001", Phase: "Fetching", FactoryTask: &task})
			return
		}
		_ = json.NewEncoder(response).Encode(map[string]string{"phase": "Validating"})
	}))
	defer server.Close()
	client := Client{BaseURL: server.URL, Token: "factory-token", Actor: "factory-01", HTTP: server.Client()}
	claimed, err := client.Claim(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if claimed.FactoryTask.Request.BuildID != "image-0001" {
		t.Fatalf("unexpected claim: %#v", claimed)
	}
	if err := client.Report(context.Background(), claimed.ID, "Validating", ""); err != nil {
		t.Fatal(err)
	}
	want := []string{"POST /api/v1/image-factory/claim", "PUT /api/v1/builds/image-0001/result"}
	if !reflect.DeepEqual(paths, want) {
		t.Fatalf("paths = %#v, want %#v", paths, want)
	}
}

func TestClientRejectsClaimWithMismatchedTask(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, _ *http.Request) {
		_ = json.NewEncoder(response).Encode(ClaimedBuild{ID: "image-0001", Phase: "Fetching", FactoryTask: &Task{Request: Request{BuildID: "other"}}})
	}))
	defer server.Close()
	client := Client{BaseURL: server.URL, Token: "token", Actor: "factory", HTTP: server.Client()}
	if _, err := client.Claim(context.Background()); err == nil {
		t.Fatal("mismatched task was accepted")
	}
}
