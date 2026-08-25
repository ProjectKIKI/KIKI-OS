package aiconsole

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestClientPlansWithOpenAICompatibleEndpoint(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		if request.Header.Get("Authorization") != "Bearer secret" {
			t.Error("missing API authorization")
		}
		var body chatRequest
		if err := json.NewDecoder(request.Body).Decode(&body); err != nil {
			t.Fatal(err)
		}
		if len(body.Messages) != 2 || !strings.Contains(body.Messages[1].Content, "디스크 확인") {
			t.Fatalf("unexpected messages: %#v", body.Messages)
		}
		writer.Header().Set("Content-Type", "application/json")
		_, _ = writer.Write([]byte(`{"choices":[{"message":{"role":"assistant","content":"{\"schema\":\"kiki-ai-command-plan-v1\",\"summary_ko\":\"확인\",\"risk\":\"low\",\"impact_ko\":\"없음\",\"commands\":[{\"description_ko\":\"확인\",\"argv\":[\"lsblk\"]}],\"verification\":[],\"rollback\":[],\"confirmation_ko\":\"실행할까요?\"}"}}]}`))
	}))
	defer server.Close()

	client := Client{Endpoint: server.URL, Model: "test", APIKey: "secret"}
	plan, err := client.Plan(context.Background(), "디스크 확인", "inventory")
	if err != nil {
		t.Fatal(err)
	}
	if plan.Commands[0].Argv[0] != "lsblk" {
		t.Fatalf("unexpected plan: %#v", plan)
	}
}
