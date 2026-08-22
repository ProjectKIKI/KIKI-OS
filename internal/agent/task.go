package agent

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"regexp"
	"strings"
	"time"
)

type TaskAction string

const (
	ActionDiagnosticCollect TaskAction = "diagnostic.collect"
	ActionModelPull         TaskAction = "model.pull"
	ActionModelVerify       TaskAction = "model.verify"
	ActionModelDeploy       TaskAction = "model.deploy"
	ActionModelStop         TaskAction = "model.stop"
	ActionModelCachePrune   TaskAction = "model.cache.prune"
	ActionRuntimeRestart    TaskAction = "runtime.restart"
)

type TaskState string

const (
	TaskPending   TaskState = "Pending"
	TaskRunning   TaskState = "Running"
	TaskSucceeded TaskState = "Succeeded"
	TaskFailed    TaskState = "Failed"
	TaskCancelled TaskState = "Cancelled"
	TaskExpired   TaskState = "Expired"
)

type ApprovalClass string

const (
	ApprovalNone     ApprovalClass = "none"
	ApprovalOperator ApprovalClass = "operator"
	ApprovalTwoParty ApprovalClass = "two-party"
)

type Task struct {
	APIVersion     string          `json:"api_version"`
	ID             string          `json:"id"`
	IdempotencyKey string          `json:"idempotency_key"`
	Action         TaskAction      `json:"action"`
	TargetNode     string          `json:"target_node"`
	Parameters     json.RawMessage `json:"parameters"`
	Approval       ApprovalClass   `json:"approval"`
	CreatedBy      string          `json:"created_by"`
	CreatedAt      time.Time       `json:"created_at"`
	ExpiresAt      time.Time       `json:"expires_at"`
	State          TaskState       `json:"state"`
}

type DiagnosticCollectParameters struct {
	Scope string `json:"scope"`
}

type ModelPullParameters struct {
	Digest string `json:"digest"`
	Source string `json:"source"`
}

type ModelVerifyParameters struct {
	Digest string `json:"digest"`
}

type ModelDeployParameters struct {
	DeploymentID string `json:"deployment_id"`
	ModelDigest  string `json:"model_digest"`
	Runtime      string `json:"runtime"`
}

type ModelStopParameters struct {
	DeploymentID string `json:"deployment_id"`
}

type ModelCachePruneParameters struct {
	KeepFreeBytes uint64 `json:"keep_free_bytes"`
}

type RuntimeRestartParameters struct {
	DeploymentID string `json:"deployment_id"`
}

var taskIDPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$`)
var digestPattern = regexp.MustCompile(`^sha256:[a-f0-9]{64}$`)

func (task Task) Validate(now time.Time) error {
	if task.APIVersion != "infraops.kiki.io/v1alpha1" {
		return errors.New("unsupported task api_version")
	}
	if !taskIDPattern.MatchString(task.ID) {
		return errors.New("task id is invalid")
	}
	if !taskIDPattern.MatchString(task.IdempotencyKey) {
		return errors.New("task idempotency_key is invalid")
	}
	if strings.TrimSpace(task.TargetNode) == "" || strings.TrimSpace(task.CreatedBy) == "" {
		return errors.New("task target_node and created_by are required")
	}
	if task.CreatedAt.IsZero() || task.ExpiresAt.IsZero() || !task.ExpiresAt.After(task.CreatedAt) {
		return errors.New("task timestamps are invalid")
	}
	if !now.Before(task.ExpiresAt) {
		return errors.New("task is expired")
	}
	if task.State != TaskPending {
		return errors.New("new task must be Pending")
	}
	minimumApproval, err := validateTaskParameters(task.Action, task.Parameters)
	if err != nil {
		return err
	}
	if approvalRank(task.Approval) < approvalRank(minimumApproval) {
		return fmt.Errorf("action %s requires %s approval", task.Action, minimumApproval)
	}
	return nil
}

func validateTaskParameters(action TaskAction, data json.RawMessage) (ApprovalClass, error) {
	switch action {
	case ActionDiagnosticCollect:
		var value DiagnosticCollectParameters
		if err := decodeStrict(data, &value); err != nil {
			return "", err
		}
		if value.Scope != "node" && value.Scope != "runtime" {
			return "", errors.New("diagnostic scope must be node or runtime")
		}
		return ApprovalNone, nil
	case ActionModelPull:
		var value ModelPullParameters
		if err := decodeStrict(data, &value); err != nil {
			return "", err
		}
		if !digestPattern.MatchString(value.Digest) || !strings.HasPrefix(value.Source, "oci://") {
			return "", errors.New("model.pull requires a sha256 digest and oci source")
		}
		return ApprovalNone, nil
	case ActionModelVerify:
		var value ModelVerifyParameters
		if err := decodeStrict(data, &value); err != nil {
			return "", err
		}
		if !digestPattern.MatchString(value.Digest) {
			return "", errors.New("model.verify requires a sha256 digest")
		}
		return ApprovalNone, nil
	case ActionModelDeploy:
		var value ModelDeployParameters
		if err := decodeStrict(data, &value); err != nil {
			return "", err
		}
		if value.DeploymentID == "" || !digestPattern.MatchString(value.ModelDigest) || !validRuntime(value.Runtime) {
			return "", errors.New("model.deploy parameters are invalid")
		}
		return ApprovalNone, nil
	case ActionModelStop:
		var value ModelStopParameters
		if err := decodeStrict(data, &value); err != nil {
			return "", err
		}
		if value.DeploymentID == "" {
			return "", errors.New("model.stop requires deployment_id")
		}
		return ApprovalOperator, nil
	case ActionModelCachePrune:
		var value ModelCachePruneParameters
		if err := decodeStrict(data, &value); err != nil {
			return "", err
		}
		if value.KeepFreeBytes == 0 {
			return "", errors.New("model.cache.prune requires keep_free_bytes")
		}
		return ApprovalOperator, nil
	case ActionRuntimeRestart:
		var value RuntimeRestartParameters
		if err := decodeStrict(data, &value); err != nil {
			return "", err
		}
		if value.DeploymentID == "" {
			return "", errors.New("runtime.restart requires deployment_id")
		}
		return ApprovalOperator, nil
	default:
		return "", fmt.Errorf("unsupported task action %q", action)
	}
}

func CanTransitionTask(from, to TaskState) bool {
	switch from {
	case TaskPending:
		return to == TaskRunning || to == TaskCancelled || to == TaskExpired
	case TaskRunning:
		return to == TaskSucceeded || to == TaskFailed || to == TaskCancelled || to == TaskExpired
	default:
		return false
	}
}

func decodeStrict(data json.RawMessage, target any) error {
	if len(data) == 0 {
		return errors.New("task parameters are required")
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return fmt.Errorf("decode task parameters: %w", err)
	}
	if err := decoder.Decode(&struct{}{}); err != io.EOF {
		return errors.New("task parameters contain trailing data")
	}
	return nil
}

func validRuntime(value string) bool {
	return value == "auto" || value == "llama.cpp" || value == "vllm"
}

func approvalRank(value ApprovalClass) int {
	switch value {
	case ApprovalNone:
		return 0
	case ApprovalOperator:
		return 1
	case ApprovalTwoParty:
		return 2
	default:
		return -1
	}
}
