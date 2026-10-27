package main

import (
	"bytes"
	"context"
	"strings"
	"testing"

	"example.com/aos-pkg/internal/aiconsole"
)

type messagePlanner struct{}

func (messagePlanner) Plan(context.Context, string, string) (aiconsole.Plan, error) {
	return aiconsole.Plan{Schema: aiconsole.MessageSchema, Reply: "Hello. How can I help?"}, nil
}

func TestConversationDoesNotRequestExecutionApproval(t *testing.T) {
	var out bytes.Buffer
	c := newConsole(defaultConfig(), "", strings.NewReader("execute\n"), &out, &out)
	c.planner = messagePlanner{}
	if err := c.handle(context.Background(), "Hello"); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(out.String(), "Choose [execute") || !strings.Contains(out.String(), "No commands were executed.") {
		t.Fatalf("unexpected conversation: %s", out.String())
	}
	// The would-be approval remains unread; the message never enters execution.
	if !c.reader.Scan() || c.reader.Text() != "execute" {
		t.Fatal("consumed approval for display-only reply")
	}
}
