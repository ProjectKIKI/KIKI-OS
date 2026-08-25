package aiconsole

import "testing"

func TestDecodePlanAcceptsFencedStrictPlan(t *testing.T) {
	data := []byte("```json\n" + `{"schema":"kiki-ai-command-plan-v1","summary_ko":"상태 확인","risk":"low","impact_ko":"변경 없음","commands":[{"description_ko":"커널 확인","argv":["uname","-a"]}],"verification":[],"rollback":[],"confirmation_ko":"실행할까요?"}` + "\n```")
	plan, err := DecodePlan(data)
	if err != nil {
		t.Fatal(err)
	}
	if got := QuoteArgv(plan.Commands[0].Argv); got != "uname -a" {
		t.Fatalf("unexpected command: %s", got)
	}
}

func TestDecodePlanRejectsUnknownField(t *testing.T) {
	data := []byte(`{"schema":"kiki-ai-command-plan-v1","summary_ko":"확인","risk":"low","impact_ko":"없음","commands":[{"description_ko":"확인","argv":["true"]}],"verification":[],"rollback":[],"confirmation_ko":"확인","surprise":true}`)
	if _, err := DecodePlan(data); err == nil {
		t.Fatal("unknown field must fail")
	}
}

func TestCommandAllowsExplicitShellButRejectsRelativeDirectory(t *testing.T) {
	command := Command{DescriptionKO: "셸 기능", Argv: []string{"/bin/sh", "-c", "printf ok"}}
	if err := command.Validate(); err != nil {
		t.Fatal(err)
	}
	command.Directory = "tmp"
	if err := command.Validate(); err == nil {
		t.Fatal("relative directory must fail")
	}
}
