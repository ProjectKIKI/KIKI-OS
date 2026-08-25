package aiconsole

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

type Result struct {
	DescriptionKO string    `json:"description_ko"`
	Argv          []string  `json:"argv"`
	StartedAt     time.Time `json:"started_at"`
	FinishedAt    time.Time `json:"finished_at"`
	ExitCode      int       `json:"exit_code"`
	Error         string    `json:"error,omitempty"`
}

type Executor struct {
	Stdout io.Writer
	Stderr io.Writer
}

func (executor Executor) Run(ctx context.Context, commands []Command) []Result {
	results := make([]Result, 0, len(commands))
	for _, command := range commands {
		result := Result{DescriptionKO: command.DescriptionKO, Argv: append([]string(nil), command.Argv...), StartedAt: time.Now().UTC(), ExitCode: -1}
		timeout := time.Duration(command.TimeoutSeconds) * time.Second
		if timeout <= 0 {
			timeout = 5 * time.Minute
		}
		commandContext, cancel := context.WithTimeout(ctx, timeout)
		process := exec.CommandContext(commandContext, command.Argv[0], command.Argv[1:]...)
		if command.Directory != "" {
			process.Dir = command.Directory
		}
		environment := make(map[string]string)
		for _, item := range os.Environ() {
			if name, value, ok := strings.Cut(item, "="); ok {
				environment[name] = value
			}
		}
		for key, value := range command.Environment {
			environment[key] = value
		}
		keys := make([]string, 0, len(command.Environment))
		for key := range environment {
			keys = append(keys, key)
		}
		sort.Strings(keys)
		for _, key := range keys {
			process.Env = append(process.Env, key+"="+environment[key])
		}
		process.Stdin = os.Stdin
		process.Stdout = executor.Stdout
		process.Stderr = executor.Stderr
		err := process.Run()
		cancel()
		result.FinishedAt = time.Now().UTC()
		if process.ProcessState != nil {
			result.ExitCode = process.ProcessState.ExitCode()
		}
		if err != nil {
			result.Error = err.Error()
		}
		results = append(results, result)
		if err != nil {
			break
		}
	}
	return results
}

func QuoteArgv(argv []string) string {
	quoted := make([]string, len(argv))
	for index, value := range argv {
		if value != "" && strings.IndexFunc(value, func(r rune) bool {
			return !(r == '_' || r == '-' || r == '.' || r == '/' || r == ':' || r == '@' || r == '+' || r == '=' || r >= '0' && r <= '9' || r >= 'A' && r <= 'Z' || r >= 'a' && r <= 'z')
		}) == -1 {
			quoted[index] = value
			continue
		}
		quoted[index] = "'" + strings.ReplaceAll(value, "'", "'\\''") + "'"
	}
	return strings.Join(quoted, " ")
}

type AuditEntry struct {
	Time    time.Time `json:"time"`
	Event   string    `json:"event"`
	Request string    `json:"request,omitempty"`
	Plan    *Plan     `json:"plan,omitempty"`
	Results []Result  `json:"results,omitempty"`
}

func AppendAudit(path string, entry AuditEntry) error {
	if path == "" {
		return nil
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o750); err != nil {
		return err
	}
	file, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	defer file.Close()
	entry.Time = time.Now().UTC()
	data, err := json.Marshal(entry)
	if err != nil {
		return err
	}
	if _, err := fmt.Fprintf(file, "%s\n", data); err != nil {
		return err
	}
	return file.Sync()
}
