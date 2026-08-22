package agent

import (
	"encoding/json"
	"strings"
	"testing"
	"time"
)

const testDigest = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

func TestTaskValidateAllowList(t *testing.T) {
	now := time.Date(2026, 7, 31, 0, 0, 0, 0, time.UTC)
	task := validTestTask(now)
	if err := task.Validate(now); err != nil {
		t.Fatal(err)
	}

	task.Action = "shell"
	task.Parameters = json.RawMessage(`{"command":"rm -rf /"}`)
	if err := task.Validate(now); err == nil || !strings.Contains(err.Error(), "unsupported task action") {
		t.Fatalf("unsafe action accepted: %v", err)
	}
}

func TestTaskRejectsUnknownParametersAndWeakApproval(t *testing.T) {
	now := time.Date(2026, 7, 31, 0, 0, 0, 0, time.UTC)
	task := validTestTask(now)
	task.Parameters = json.RawMessage(`{"scope":"node","command":"id"}`)
	if err := task.Validate(now); err == nil || !strings.Contains(err.Error(), "unknown field") {
		t.Fatalf("unknown parameter accepted: %v", err)
	}

	task = validTestTask(now)
	task.Action = ActionRuntimeRestart
	task.Parameters = json.RawMessage(`{"deployment_id":"ops-model"}`)
	if err := task.Validate(now); err == nil || !strings.Contains(err.Error(), "operator approval") {
		t.Fatalf("weak approval accepted: %v", err)
	}
	task.Approval = ApprovalOperator
	if err := task.Validate(now); err != nil {
		t.Fatalf("operator-approved task rejected: %v", err)
	}
}

func TestTaskRejectsExpiredAndMutableIdentity(t *testing.T) {
	now := time.Date(2026, 7, 31, 0, 0, 0, 0, time.UTC)
	task := validTestTask(now)
	task.ExpiresAt = now.Add(time.Minute)
	if err := task.Validate(now.Add(2 * time.Minute)); err == nil || !strings.Contains(err.Error(), "expired") {
		t.Fatalf("expired task accepted: %v", err)
	}
	task = validTestTask(now)
	task.Action = ActionModelPull
	task.Parameters = json.RawMessage(`{"digest":"` + testDigest + `","source":"oci://registry/models/latest"}`)
	if err := task.Validate(now); err != nil {
		t.Fatalf("digest-pinned model pull rejected: %v", err)
	}
}

func TestTaskStateTransitions(t *testing.T) {
	allowed := [][2]TaskState{{TaskPending, TaskRunning}, {TaskPending, TaskCancelled}, {TaskRunning, TaskSucceeded}, {TaskRunning, TaskFailed}}
	for _, transition := range allowed {
		if !CanTransitionTask(transition[0], transition[1]) {
			t.Fatalf("expected transition %s -> %s", transition[0], transition[1])
		}
	}
	denied := [][2]TaskState{{TaskPending, TaskSucceeded}, {TaskSucceeded, TaskRunning}, {TaskFailed, TaskPending}}
	for _, transition := range denied {
		if CanTransitionTask(transition[0], transition[1]) {
			t.Fatalf("unexpected transition %s -> %s", transition[0], transition[1])
		}
	}
}

func validTestTask(now time.Time) Task {
	return Task{
		APIVersion: "infraops.kiki.io/v1alpha1", ID: "task-00000001", IdempotencyKey: "deploy-00000001",
		Action: ActionDiagnosticCollect, TargetNode: "node-01", Parameters: json.RawMessage(`{"scope":"node"}`),
		Approval: ApprovalNone, CreatedBy: "user@example.com", CreatedAt: now, ExpiresAt: now.Add(time.Hour), State: TaskPending,
	}
}
