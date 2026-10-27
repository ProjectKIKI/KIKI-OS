package aiconsole

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestDisplayOnlyReplyValidation(t *testing.T) {
	for _, input := range []string{
		"{}",
		"null",
		"{\"summary_ko\":\"Hello\"}",
		"{\"schema\":\"kiki-ai-message-v1\",\"reply\":\"\"}",
		"{\"schema\":\"kiki-ai-message-v1\",\"reply\":\"Hi\",\"commands\":[{\"description_ko\":\"bad\",\"argv\":[\"true\"]}]}",
		"{\"schema\":\"kiki-ai-message-v1\",\"reply\":\"Hi\",\"verification\":[{\"description_ko\":\"bad\",\"argv\":[\"true\"]}]}",
		"{\"schema\":\"kiki-ai-message-v1\",\"reply\":\"Hi\",\"rollback\":[{\"description_ko\":\"bad\",\"argv\":[\"true\"]}]}",
	} {
		if _, err := DecodePlan([]byte(input)); err == nil {
			t.Fatalf("accepted invalid reply: %s", input)
		}
	}
	if _, err := DecodePlan([]byte("{\"schema\":\"kiki-ai-message-v1\",\"reply\":\"Hello. How can I help?\"}")); err != nil {
		t.Fatal(err)
	}
}

func TestClientBoundedSchemaRetry(t *testing.T) {
	for _, scenario := range []string{"recover", "invalid", "truncated", "http"} {
		t.Run(scenario, func(t *testing.T) {
			calls := 0
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls++
				var body chatRequest
				if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
					t.Error(err)
				}
				if body.ResponseFormat["schema"] == nil {
					t.Error("missing grammar schema")
				}
				if calls == 2 && !strings.Contains(body.Messages[0].Content, "previous response failed") {
					t.Error("missing correction instruction")
				}
				if scenario == "http" {
					w.WriteHeader(503)
					return
				}
				content, finish := "{}", "stop"
				if scenario == "recover" && calls == 2 || scenario == "truncated" {
					content = "{\"schema\":\"kiki-ai-message-v1\",\"reply\":\"Hello\"}"
				}
				if scenario == "truncated" {
					finish = "length"
				}
				_ = json.NewEncoder(w).Encode(map[string]any{"choices": []any{map[string]any{
					"message": map[string]any{"role": "assistant", "content": content}, "finish_reason": finish,
				}}})
			}))
			defer server.Close()
			plan, err := (Client{Endpoint: server.URL, Model: "test"}).Plan(context.Background(), "Hello", "")
			if scenario == "recover" {
				if err != nil || plan.Schema != MessageSchema {
					t.Fatalf("reply=%+v err=%v", plan, err)
				}
			} else if err == nil {
				t.Fatal("expected rejection")
			}
			want := 2
			if scenario == "http" {
				want = 1
			}
			if calls != want {
				t.Fatalf("calls=%d, want %d", calls, want)
			}
		})
	}
}
