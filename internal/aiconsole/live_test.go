package aiconsole

import (
	"context"
	"os"
	"strings"
	"testing"
	"time"
)

// Explicitly opt in to a local, isolated model server. Never executes a plan.
func TestLiveModelReplies(t *testing.T) {
	endpoint := os.Getenv("KIKI_AI_TEST_ENDPOINT")
	if endpoint == "" {
		t.Skip("set KIKI_AI_TEST_ENDPOINT for the packaged model acceptance test")
	}
	client := Client{Endpoint: endpoint, Model: "kiki-ops"}
	for _, sample := range []struct{ request, schema string }{
		{"Hello", MessageSchema},
		{"What can you help me with?", MessageSchema},
		{"Explain what DHCP means. Do not run any commands.", MessageSchema},
		{"Show the current kernel version using uname -r.", PlanSchema},
	} {
		t.Run(sample.request, func(t *testing.T) {
			ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
			defer cancel()
			plan, err := client.Plan(ctx, sample.request, "[Kernel]\nLinux kiki 6.1.187-kiki-vm x86_64\n[Network links]\neth0\n")
			if err != nil {
				t.Fatal(err)
			}
			if plan.Schema != sample.schema {
				t.Fatalf("schema=%q want %q: %+v", plan.Schema, sample.schema, plan)
			}
			t.Logf("validated display/plan only: %+v", plan)
			if plan.Reply == sample.request || strings.TrimSuffix(plan.Reply, ".") == "Explain what DHCP means" {
				t.Fatalf("model echoed the request instead of answering: %+v", plan)
			}
		})
	}
}
