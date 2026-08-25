package aiconsole

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestExecutorStopsAfterFailure(t *testing.T) {
	var output bytes.Buffer
	executor := Executor{Stdout: &output, Stderr: &output}
	results := executor.Run(context.Background(), []Command{
		{DescriptionKO: "출력", Argv: []string{"/bin/sh", "-c", "printf first"}},
		{DescriptionKO: "실패", Argv: []string{"/bin/sh", "-c", "exit 7"}},
		{DescriptionKO: "실행 금지", Argv: []string{"/bin/sh", "-c", "printf third"}},
	})
	if len(results) != 2 || results[1].ExitCode != 7 || output.String() != "first" {
		t.Fatalf("unexpected execution: results=%#v output=%q", results, output.String())
	}
}

func TestAppendAuditUsesPrivatePermissions(t *testing.T) {
	path := filepath.Join(t.TempDir(), "audit", "console.jsonl")
	if err := AppendAudit(path, AuditEntry{Event: "test"}); err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("unexpected permissions: %o", info.Mode().Perm())
	}
	data, _ := os.ReadFile(path)
	if !strings.Contains(string(data), `"event":"test"`) {
		t.Fatalf("unexpected audit: %s", data)
	}
}

func TestQuoteArgv(t *testing.T) {
	if got := QuoteArgv([]string{"/bin/sh", "-c", "echo '한글'"}); got != "/bin/sh -c 'echo '\\''한글'\\'''" {
		t.Fatalf("unexpected quote: %s", got)
	}
}
