package bootstrap

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type DiagnosticRunner struct {
	Endpoint   string
	Model      string
	APIKeyFile string
	Timeout    time.Duration
	Client     *http.Client
}

func (r DiagnosticRunner) Diagnose(node Node) (string, string) {
	if r.Endpoint == "" {
		return "rules", ruleBasedDiagnosis(node)
	}
	timeout := r.Timeout
	if timeout <= 0 {
		timeout = 30 * time.Second
	}
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	summary, err := r.openAIRequest(ctx, buildDiagnosticPrompt(node))
	if err != nil {
		return "rules-fallback", fmt.Sprintf("LLM request failed: %v\n\n%s", err, ruleBasedDiagnosis(node))
	}
	return "openai-compatible", summary
}

func RunnerFromEnv() DiagnosticRunner {
	timeout := 30 * time.Second
	if raw := os.Getenv("KIKI_LLM_TIMEOUT_SECONDS"); raw != "" {
		if parsed, err := time.ParseDuration(raw + "s"); err == nil {
			timeout = parsed
		}
	}
	return DiagnosticRunner{
		Endpoint:   strings.TrimRight(os.Getenv("KIKI_LLM_ENDPOINT"), "/"),
		Model:      firstEnvironment("KIKI_LLM_MODEL", "kiki-ops"),
		APIKeyFile: os.Getenv("KIKI_LLM_API_KEY_FILE"),
		Timeout:    timeout,
	}
}

func (r DiagnosticRunner) openAIRequest(ctx context.Context, prompt string) (string, error) {
	endpoint, err := url.Parse(r.Endpoint)
	if err != nil || (endpoint.Scheme != "http" && endpoint.Scheme != "https") || endpoint.Host == "" {
		return "", errors.New("KIKI_LLM_ENDPOINT must be an absolute HTTP(S) URL")
	}
	endpoint.Path = strings.TrimRight(endpoint.Path, "/") + "/v1/chat/completions"
	payload := map[string]any{
		"model":       r.Model,
		"messages":    []map[string]string{{"role": "user", "content": prompt}},
		"temperature": 0,
		"max_tokens":  512,
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return "", err
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint.String(), bytes.NewReader(body))
	if err != nil {
		return "", err
	}
	request.Header.Set("Content-Type", "application/json")
	if r.APIKeyFile != "" {
		key, err := readSecretFile(r.APIKeyFile)
		if err != nil {
			return "", err
		}
		request.Header.Set("Authorization", "Bearer "+key)
	}
	client := r.Client
	if client == nil {
		client = http.DefaultClient
	}
	response, err := client.Do(request)
	if err != nil {
		return "", err
	}
	defer response.Body.Close()
	limited := io.LimitReader(response.Body, 1<<20)
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		message, _ := io.ReadAll(io.LimitReader(limited, 4096))
		return "", fmt.Errorf("inference endpoint returned %d: %s", response.StatusCode, strings.TrimSpace(string(message)))
	}
	var result struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
	}
	if err := json.NewDecoder(limited).Decode(&result); err != nil {
		return "", fmt.Errorf("decode inference response: %w", err)
	}
	if len(result.Choices) == 0 || strings.TrimSpace(result.Choices[0].Message.Content) == "" {
		return "", errors.New("inference endpoint returned no message")
	}
	return strings.TrimSpace(result.Choices[0].Message.Content), nil
}

func readSecretFile(path string) (string, error) {
	data, err := os.ReadFile(filepath.Clean(path))
	if err != nil {
		return "", fmt.Errorf("read LLM API key file: %w", err)
	}
	key := strings.TrimSpace(string(data))
	if key == "" {
		return "", errors.New("LLM API key file is empty")
	}
	return key, nil
}

func firstEnvironment(name, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(name)); value != "" {
		return value
	}
	return fallback
}

func buildDiagnosticPrompt(node Node) string {
	data, _ := json.MarshalIndent(map[string]any{
		"node": map[string]any{
			"name":              node.Name,
			"role":              node.Role,
			"phase":             node.Phase,
			"boot_mode":         node.BootMode,
			"disk":              node.Disk,
			"last_error":        node.LastError,
			"last_heartbeat_at": node.LastHeartbeatAt,
		},
		"events": node.Events,
	}, "", "  ")
	return "You are diagnosing a KIKI bootstrap node installation. Summarize likely causes and next checks. Do not suggest destructive actions.\n\n" + string(data)
}

func ruleBasedDiagnosis(node Node) string {
	var checks []string
	joinedEvents := strings.Builder{}
	for _, event := range node.Events {
		joinedEvents.WriteString(strings.ToLower(event.Message))
		joinedEvents.WriteByte(' ')
		joinedEvents.WriteString(strings.ToLower(event.Type))
		joinedEvents.WriteByte(' ')
	}
	text := joinedEvents.String()

	switch node.Phase {
	case "pending", "installing":
		checks = append(checks, "No completed boot event has arrived yet. Check installer console output and management API reachability.")
	case "installed":
		if node.LastHeartbeatAt == "" {
			checks = append(checks, "The installer reported completion, but the Debian node has not sent a heartbeat. Check GRUB boot mode, DHCP, and kiki-agent.service.")
		}
	case "failed":
		checks = append(checks, "The node is marked failed. Review the latest error event and installer log bundle.")
	}
	if node.LastError != "" {
		checks = append(checks, "Last recorded error: "+node.LastError)
	}
	if strings.Contains(text, "debootstrap") {
		checks = append(checks, "debootstrap appears in recent events. Verify Debian mirror access, DNS, proxy, and requested package names.")
	}
	if strings.Contains(text, "grub") {
		checks = append(checks, "GRUB appears in recent events. Verify BIOS/UEFI mode matches the VM firmware and partition layout.")
	}
	if strings.Contains(text, "token") {
		checks = append(checks, "Token-related text appears in events. Verify the registration token is active and has not already been consumed.")
	}
	if len(checks) == 0 {
		checks = append(checks, "No obvious failure signature is present. Review the latest installer log bundle and node heartbeat timing.")
	}
	for i, check := range checks {
		checks[i] = "- " + check
	}
	return strings.Join(checks, "\n")
}
