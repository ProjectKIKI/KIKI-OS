package aiconsole

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"regexp"
	"strings"
)

const PlanSchema = "kiki-ai-command-plan-v1"

// MessageSchema is display-only: it must never carry executable commands.
const MessageSchema = "kiki-ai-message-v1"

type Plan struct {
	Reply          string    `json:"reply,omitempty"`
	Kind           string    `json:"kind,omitempty"`
	Schema         string    `json:"schema"`
	SummaryKO      string    `json:"summary_ko"`
	Risk           string    `json:"risk"`
	ImpactKO       string    `json:"impact_ko"`
	Commands       []Command `json:"commands"`
	Verification   []Command `json:"verification"`
	Rollback       []Command `json:"rollback"`
	ConfirmationKO string    `json:"confirmation_ko"`
}

type Command struct {
	DescriptionKO  string            `json:"description_ko"`
	Argv           []string          `json:"argv"`
	Directory      string            `json:"directory,omitempty"`
	Environment    map[string]string `json:"environment,omitempty"`
	TimeoutSeconds int               `json:"timeout_seconds,omitempty"`
}

var environmentName = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]*$`)

func DecodePlan(data []byte) (Plan, error) {
	trimmed := bytes.TrimSpace(data)
	if bytes.HasPrefix(trimmed, []byte("```")) {
		lines := bytes.Split(trimmed, []byte("\n"))
		if len(lines) >= 3 && bytes.HasPrefix(lines[0], []byte("```")) && bytes.Equal(bytes.TrimSpace(lines[len(lines)-1]), []byte("```")) {
			trimmed = bytes.Join(lines[1:len(lines)-1], []byte("\n"))
		}
	}
	var plan Plan
	decoder := json.NewDecoder(bytes.NewReader(trimmed))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&plan); err != nil {
		return Plan{}, fmt.Errorf("Parse AI plan JSON: %w", err)
	}
	if err := decoder.Decode(&struct{}{}); err != io.EOF {
		return Plan{}, errors.New("Unexpected trailing AI plan data")
	}
	if err := plan.Validate(); err != nil {
		return Plan{}, err
	}
	return plan, nil
}

func (plan Plan) Validate() error {
	if plan.Kind != "" && !((plan.Kind == "message" && plan.Schema == MessageSchema) || (plan.Kind == "plan" && plan.Schema == PlanSchema)) {
		return errors.New("AI reply kind and schema do not match")
	}
	if plan.Schema == MessageSchema {
		if strings.TrimSpace(plan.Reply) == "" || len(plan.Reply) > 8192 || plan.SummaryKO != "" {
			return errors.New("AI message requires a non-empty, bounded summary")
		}
		if len(plan.Commands)+len(plan.Verification)+len(plan.Rollback) != 0 || plan.Risk != "" || plan.ImpactKO != "" || plan.ConfirmationKO != "" {
			return errors.New("Display-only AI messages cannot contain commands or plan fields")
		}
		return nil
	}
	if plan.Schema != PlanSchema {
		return fmt.Errorf("Unsupported AI plan schema %q", plan.Schema)
	}
	if plan.Reply != "" {
		return errors.New("Execution plans cannot contain display-only reply fields")
	}
	if strings.TrimSpace(plan.SummaryKO) == "" || strings.TrimSpace(plan.ImpactKO) == "" {
		return errors.New("AI plan requires a summary and impact description")
	}
	switch plan.Risk {
	case "low", "normal", "network", "storage", "system", "critical":
	default:
		return fmt.Errorf("Unsupported risk level %q", plan.Risk)
	}
	if len(plan.Commands) == 0 || len(plan.Commands) > 32 {
		return errors.New("Plan requires between 1 and 32 commands")
	}
	if len(plan.Verification) > 16 || len(plan.Rollback) > 16 {
		return errors.New("Verification and rollback may each contain at most 16 commands")
	}
	for group, commands := range map[string][]Command{"execution": plan.Commands, "verification": plan.Verification, "rollback": plan.Rollback} {
		for index, command := range commands {
			if err := command.Validate(); err != nil {
				return fmt.Errorf("%s command %d: %w", group, index+1, err)
			}
		}
	}
	return nil
}

func (command Command) Validate() error {
	if strings.TrimSpace(command.DescriptionKO) == "" {
		return errors.New("Command description is empty")
	}
	if len(command.Argv) == 0 || len(command.Argv) > 128 {
		return errors.New("argv must contain between 1 and 128 entries")
	}
	for _, value := range command.Argv {
		if value == "" || strings.ContainsRune(value, '\x00') || len(value) > 4096 {
			return errors.New("argv contains an empty or invalid value")
		}
	}
	if command.Directory != "" && !strings.HasPrefix(command.Directory, "/") {
		return errors.New("Working directory must be an absolute path")
	}
	if command.TimeoutSeconds < 0 || command.TimeoutSeconds > 3600 {
		return errors.New("Command timeout must be 0..3600 seconds")
	}
	if len(command.Environment) > 32 {
		return errors.New("At most 32 environment variables are allowed")
	}
	for name, value := range command.Environment {
		if !environmentName.MatchString(name) || strings.ContainsRune(value, '\x00') || len(value) > 4096 {
			return errors.New("Invalid environment variable name or value")
		}
	}
	return nil
}
