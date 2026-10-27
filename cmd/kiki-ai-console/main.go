package main

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"sort"
	"strings"
	"time"

	"example.com/aos-pkg/internal/aiconsole"
)

type config struct {
	Endpoint   string `json:"endpoint"`
	Model      string `json:"model"`
	APIKeyFile string `json:"api_key_file,omitempty"`
	AuditLog   string `json:"audit_log"`
}

func defaultConfig() config {
	return config{
		Endpoint: "http://127.0.0.1:8080/v1/chat/completions",
		Model:    "kiki-ops",
		AuditLog: "/var/log/kiki/ai-console.jsonl",
	}
}

func loadConfig(path string) (config, error) {
	result := defaultConfig()
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return result, nil
	}
	if err != nil {
		return result, err
	}
	decoder := json.NewDecoder(strings.NewReader(string(data)))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&result); err != nil {
		return result, fmt.Errorf("Parse configuration: %w", err)
	}
	if err := decoder.Decode(&struct{}{}); err != io.EOF {
		return result, errors.New("Unexpected trailing configuration data")
	}
	if result.Endpoint == "" || result.Model == "" {
		return result, errors.New("endpoint and model are required")
	}
	return result, nil
}

func readAPIKey(path string) (string, error) {
	if path == "" {
		return "", nil
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(string(data)), nil
}

func main() {
	configPath := flag.String("config", "/etc/kiki/ai-console.json", "Configuration file")
	once := flag.String("once", "", "Plan one request without execution, then exit")
	waitLocalRuntime := flag.Duration("wait-local-runtime", 0, "Local AI runtime readiness timeout")
	flag.Parse()

	cfg, err := loadConfig(*configPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, "KIKI AI console configuration error:", err)
		os.Exit(1)
	}
	apiKey, err := readAPIKey(cfg.APIKeyFile)
	if err != nil {
		fmt.Fprintln(os.Stderr, "Cannot read API key:", err)
		os.Exit(1)
	}
	if *waitLocalRuntime > 0 && isLoopbackEndpoint(cfg.Endpoint) {
		fmt.Fprintln(os.Stdout, "Waiting for the local AI runtime...")
		waitContext, cancel := context.WithTimeout(context.Background(), *waitLocalRuntime)
		err := waitForRuntime(waitContext, cfg.Endpoint)
		cancel()
		if err != nil {
			fmt.Fprintln(os.Stderr, "Warning: local AI runtime is not ready:", err)
			fmt.Fprintln(os.Stderr, "Use tty2: systemctl status kiki-llama-server.service; journalctl -u kiki-llama-server.service")
		} else {
			fmt.Fprintln(os.Stdout, "Local AI runtime is ready.")
		}
	}
	console := newConsole(cfg, apiKey, os.Stdin, os.Stdout, os.Stderr)
	if *once != "" {
		if err := console.planOnly(context.Background(), *once); err != nil {
			fmt.Fprintln(os.Stderr, "Planning error:", err)
			os.Exit(1)
		}
		return
	}
	console.run(context.Background())
}

func isLoopbackEndpoint(rawEndpoint string) bool {
	parsed, err := url.Parse(rawEndpoint)
	if err != nil {
		return false
	}
	hostname := parsed.Hostname()
	if hostname == "localhost" {
		return true
	}
	address := net.ParseIP(hostname)
	return address != nil && address.IsLoopback()
}

func runtimeHealthURL(rawEndpoint string) (string, error) {
	parsed, err := url.Parse(rawEndpoint)
	if err != nil || parsed.Scheme == "" || parsed.Host == "" {
		return "", errors.New("Invalid AI endpoint")
	}
	parsed.Path = "/health"
	parsed.RawPath = ""
	parsed.RawQuery = ""
	parsed.Fragment = ""
	return parsed.String(), nil
}

func waitForRuntime(ctx context.Context, endpoint string) error {
	return waitForRuntimeWithClient(ctx, endpoint, &http.Client{Timeout: 2 * time.Second}, time.Second)
}

func waitForRuntimeWithClient(ctx context.Context, endpoint string, client *http.Client, retryInterval time.Duration) error {
	healthURL, err := runtimeHealthURL(endpoint)
	if err != nil {
		return err
	}
	ticker := time.NewTicker(retryInterval)
	defer ticker.Stop()
	var lastError error
	for {
		request, requestErr := http.NewRequestWithContext(ctx, http.MethodGet, healthURL, nil)
		if requestErr != nil {
			return requestErr
		}
		response, requestErr := client.Do(request)
		if requestErr == nil {
			_ = response.Body.Close()
			if response.StatusCode != http.StatusServiceUnavailable && response.StatusCode < 500 {
				return nil
			}
			lastError = fmt.Errorf("%s response: HTTP %d", healthURL, response.StatusCode)
		} else {
			lastError = requestErr
		}
		select {
		case <-ctx.Done():
			if lastError != nil {
				return fmt.Errorf("%w (last error: %v)", ctx.Err(), lastError)
			}
			return ctx.Err()
		case <-ticker.C:
		}
	}
}

type planner interface {
	Plan(context.Context, string, string) (aiconsole.Plan, error)
}

type console struct {
	planner  planner
	executor aiconsole.Executor
	reader   *bufio.Scanner
	hangul   *hangulLineReader
	out      io.Writer
	errOut   io.Writer
	auditLog string
}

func newConsole(cfg config, apiKey string, in io.Reader, out, errOut io.Writer) *console {
	in, hangul := maybeHangulInput(in, out)
	reader := bufio.NewScanner(in)
	reader.Buffer(make([]byte, 4096), 1024*1024)
	return &console{
		planner:  aiconsole.Client{Endpoint: cfg.Endpoint, Model: cfg.Model, APIKey: apiKey},
		executor: aiconsole.Executor{Stdout: out, Stderr: errOut},
		reader:   reader,
		hangul:   hangul,
		out:      out,
		errOut:   errOut,
		auditLog: cfg.AuditLog,
	}
}

func (c *console) scan(prompt string) bool {
	if c.hangul != nil {
		c.hangul.prompt = strings.TrimLeft(prompt, "\n")
	}
	fmt.Fprint(c.out, prompt)
	return c.reader.Scan()
}

func (c *console) run(ctx context.Context) {
	fmt.Fprintln(c.out, "KIKI OS AI management console (tty1)")
	fmt.Fprintln(c.out, "Commands are displayed first and require explicit 'execute' approval.")
	fmt.Fprintln(c.out, "Recovery shell: Ctrl+Alt+F2 (tty2). Help: /help. Status: /status.")
	for {
		if !c.scan("\nkiki-ai> ") {
			return
		}
		request := strings.TrimSpace(c.reader.Text())
		switch request {
		case "":
			continue
		case "/종료", "/exit", "exit", "quit":
			return
		case "/도움말", "/help":
			fmt.Fprintln(c.out, "Greetings and questions receive display-only replies; no commands are executed.")
			fmt.Fprintln(c.out, "Describe a task, for example: 'Configure a static IP address'.")
			fmt.Fprintln(c.out, "Review choices: execute / edit / cancel")
			continue
		case "/상태", "/status":
			fmt.Fprintln(c.out, aiconsole.CollectInventory(ctx))
			continue
		}
		if err := c.handle(ctx, request); err != nil {
			fmt.Fprintln(c.errOut, "Request error:", err)
		}
	}
}

func (c *console) planOnly(ctx context.Context, request string) error {
	plan, err := c.makePlan(ctx, request)
	if err != nil {
		return err
	}
	renderPlan(c.out, plan)
	return nil
}

func (c *console) makePlan(ctx context.Context, request string) (aiconsole.Plan, error) {
	fmt.Fprintln(c.out, "Inspecting the system and preparing a response...")
	planContext, cancel := context.WithTimeout(ctx, 2*time.Minute)
	defer cancel()
	return c.planner.Plan(planContext, request, aiconsole.CollectInventory(planContext))
}

func (c *console) handle(ctx context.Context, request string) error {
	for {
		plan, err := c.makePlan(ctx, request)
		if err != nil {
			return err
		}
		renderPlan(c.out, plan)
		if plan.Schema == aiconsole.MessageSchema {
			return nil
		}
		if !c.scan("\nChoose [execute/edit/cancel]: ") {
			return io.EOF
		}
		switch strings.TrimSpace(c.reader.Text()) {
		case "취소", "cancel":
			_ = aiconsole.AppendAudit(c.auditLog, aiconsole.AuditEntry{Event: "cancelled", Request: request, Plan: &plan})
			fmt.Fprintln(c.out, "Cancelled. No commands were executed.")
			return nil
		case "수정", "edit":
			if !c.scan("Enter the requested changes: ") {
				return io.EOF
			}
			request += "\nAdditional changes: " + strings.TrimSpace(c.reader.Text())
			continue
		case "실행", "execute":
			if err := aiconsole.AppendAudit(c.auditLog, aiconsole.AuditEntry{Event: "approved", Request: request, Plan: &plan}); err != nil {
				return fmt.Errorf("Write audit log: %w", err)
			}
			results := c.executor.Run(ctx, plan.Commands)
			_ = aiconsole.AppendAudit(c.auditLog, aiconsole.AuditEntry{Event: "executed", Plan: &plan, Results: results})
			if failed(results) {
				fmt.Fprintln(c.errOut, "Command execution stopped.")
				return c.offerRollback(ctx, plan)
			}
			if len(plan.Verification) > 0 {
				fmt.Fprintln(c.out, "\nRunning verification commands.")
				verification := c.executor.Run(ctx, plan.Verification)
				_ = aiconsole.AppendAudit(c.auditLog, aiconsole.AuditEntry{Event: "verified", Plan: &plan, Results: verification})
				if failed(verification) {
					fmt.Fprintln(c.errOut, "Verification failed.")
					return c.offerRollback(ctx, plan)
				}
			}
			fmt.Fprintln(c.out, "Task and verification completed.")
			return nil
		default:
			fmt.Fprintln(c.out, "Enter exactly 'execute', 'edit', or 'cancel'.")
		}
	}
}

func (c *console) offerRollback(ctx context.Context, plan aiconsole.Plan) error {
	if len(plan.Rollback) == 0 {
		fmt.Fprintln(c.errOut, "No rollback commands provided. Use the tty2 recovery shell.")
		return nil
	}
	fmt.Fprintln(c.out, "\nAvailable rollback commands:")
	renderCommands(c.out, plan.Rollback)
	if !c.scan("Type 'rollback' to roll back, or press Enter to skip: ") {
		return nil
	}
	choice := strings.TrimSpace(c.reader.Text())
	if choice != "rollback" && choice != "롤백" {
		return nil
	}
	results := c.executor.Run(ctx, plan.Rollback)
	_ = aiconsole.AppendAudit(c.auditLog, aiconsole.AuditEntry{Event: "rolled_back", Plan: &plan, Results: results})
	if failed(results) {
		return errors.New("Rollback failed. Use the tty2 recovery shell")
	}
	fmt.Fprintln(c.out, "Rollback completed.")
	return nil
}

func renderPlan(out io.Writer, plan aiconsole.Plan) {
	if plan.Schema == aiconsole.MessageSchema {
		fmt.Fprintln(out, plan.Reply)
		fmt.Fprintln(out, "No commands were executed.")
		return
	}
	fmt.Fprintf(out, "\nSummary: %s\nRisk: %s\nImpact: %s\n", plan.SummaryKO, plan.Risk, plan.ImpactKO)
	fmt.Fprintln(out, "\nExact commands to execute:")
	renderCommands(out, plan.Commands)
	if len(plan.Verification) > 0 {
		fmt.Fprintln(out, "\nPost-execution verification:")
		renderCommands(out, plan.Verification)
	}
	if len(plan.Rollback) > 0 {
		fmt.Fprintln(out, "\nRollback commands:")
		renderCommands(out, plan.Rollback)
	}
	fmt.Fprintln(out, "\nConfirmation:", plan.ConfirmationKO)
}

func renderCommands(out io.Writer, commands []aiconsole.Command) {
	for index, command := range commands {
		fmt.Fprintf(out, "  %d. %s\n     $ %s\n", index+1, command.DescriptionKO, aiconsole.QuoteArgv(command.Argv))
		if command.Directory != "" {
			fmt.Fprintf(out, "     Working directory: %s\n", command.Directory)
		}
		if len(command.Environment) > 0 {
			keys := make([]string, 0, len(command.Environment))
			for key := range command.Environment {
				keys = append(keys, key)
			}
			sort.Strings(keys)
			for _, key := range keys {
				fmt.Fprintf(out, "     Environment: %s=%s\n", key, command.Environment[key])
			}
		}
	}
}

func failed(results []aiconsole.Result) bool {
	return len(results) == 0 || results[len(results)-1].ExitCode != 0
}
