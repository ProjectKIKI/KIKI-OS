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

type Plan struct {
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
		return Plan{}, fmt.Errorf("AI 계획 JSON 해석: %w", err)
	}
	if err := decoder.Decode(&struct{}{}); err != io.EOF {
		return Plan{}, errors.New("AI 계획 뒤에 허용되지 않은 데이터가 있습니다")
	}
	if err := plan.Validate(); err != nil {
		return Plan{}, err
	}
	return plan, nil
}

func (plan Plan) Validate() error {
	if plan.Schema != PlanSchema {
		return fmt.Errorf("지원하지 않는 AI 계획 스키마 %q", plan.Schema)
	}
	if strings.TrimSpace(plan.SummaryKO) == "" || strings.TrimSpace(plan.ImpactKO) == "" {
		return errors.New("AI 계획에는 한국어 요약과 영향 설명이 필요합니다")
	}
	switch plan.Risk {
	case "low", "normal", "network", "storage", "system", "critical":
	default:
		return fmt.Errorf("지원하지 않는 위험 등급 %q", plan.Risk)
	}
	if len(plan.Commands) == 0 || len(plan.Commands) > 32 {
		return errors.New("실행 명령은 1개 이상 32개 이하여야 합니다")
	}
	if len(plan.Verification) > 16 || len(plan.Rollback) > 16 {
		return errors.New("검증 및 롤백 명령은 각각 16개 이하여야 합니다")
	}
	for group, commands := range map[string][]Command{"실행": plan.Commands, "검증": plan.Verification, "롤백": plan.Rollback} {
		for index, command := range commands {
			if err := command.Validate(); err != nil {
				return fmt.Errorf("%s 명령 %d: %w", group, index+1, err)
			}
		}
	}
	return nil
}

func (command Command) Validate() error {
	if strings.TrimSpace(command.DescriptionKO) == "" {
		return errors.New("한국어 명령 설명이 비어 있습니다")
	}
	if len(command.Argv) == 0 || len(command.Argv) > 128 {
		return errors.New("argv는 1개 이상 128개 이하여야 합니다")
	}
	for _, value := range command.Argv {
		if value == "" || strings.ContainsRune(value, '\x00') || len(value) > 4096 {
			return errors.New("argv에 비어 있거나 잘못된 값이 있습니다")
		}
	}
	if command.Directory != "" && !strings.HasPrefix(command.Directory, "/") {
		return errors.New("작업 디렉터리는 절대 경로여야 합니다")
	}
	if command.TimeoutSeconds < 0 || command.TimeoutSeconds > 3600 {
		return errors.New("명령 제한 시간은 0~3600초여야 합니다")
	}
	if len(command.Environment) > 32 {
		return errors.New("환경 변수는 32개 이하여야 합니다")
	}
	for name, value := range command.Environment {
		if !environmentName.MatchString(name) || strings.ContainsRune(value, '\x00') || len(value) > 4096 {
			return errors.New("환경 변수 이름 또는 값이 잘못되었습니다")
		}
	}
	return nil
}
