package main

import (
	"bytes"
	"strings"
	"testing"

	"example.com/aos-pkg/internal/aiconsole"
)

func TestRenderPlanShowsExactExecutionContext(t *testing.T) {
	plan := aiconsole.Plan{
		Schema:         aiconsole.PlanSchema,
		SummaryKO:      "설정 변경",
		Risk:           "network",
		ImpactKO:       "연결이 변경될 수 있음",
		ConfirmationKO: "명령을 확인했습니까?",
		Commands: []aiconsole.Command{{
			DescriptionKO: "설정 쓰기",
			Argv:          []string{"/bin/sh", "-c", "printf '%s' ok"},
			Directory:     "/etc",
			Environment:   map[string]string{"LANG": "ko_KR.UTF-8"},
		}},
	}
	var output bytes.Buffer
	renderPlan(&output, plan)
	for _, expected := range []string{
		"위험 등급: network",
		`$ /bin/sh -c 'printf '\''%s'\'' ok'`,
		"작업 경로: /etc",
		"환경 변수: LANG=ko_KR.UTF-8",
	} {
		if !strings.Contains(output.String(), expected) {
			t.Fatalf("rendered plan missing %q:\n%s", expected, output.String())
		}
	}
}
