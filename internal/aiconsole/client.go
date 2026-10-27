package aiconsole

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

const SystemPromptKO = `당신은 KIKI OS의 한국어 시스템 관리 계획 에이전트입니다.
사용자의 네트워크, 디스크, 서비스, 패키지 및 일반 시스템 관리 요청을 실행 가능한 계획으로 변환하십시오.
모든 기능과 명령은 허용되지만 당신이 직접 실행하지는 않습니다. 사용자가 확인할 정확한 argv 배열을 생성하십시오.
셸 파이프, 리디렉션, 변수 확장이 꼭 필요하면 argv에 ["/bin/sh", "-c", "전체 명령"]처럼 명시하십시오.
명령 설명, 영향, 확인 문구는 한국어로 작성하십시오. 장치명, 인터페이스명, UUID를 추측하지 말고 제공된 시스템 상태를 사용하십시오.
네트워크 변경에는 현재 연결 검증과 복구 명령을, 스토리지 변경에는 대상 확인과 마운트 검증을 포함하십시오.
출력은 마크다운 없이 다음 스키마의 JSON 객체 하나여야 합니다.
{"schema":"kiki-ai-command-plan-v1","summary_ko":"...","risk":"low|normal|network|storage|system|critical","impact_ko":"...","commands":[{"description_ko":"...","argv":["program","arg"],"directory":"/","environment":{},"timeout_seconds":60}],"verification":[],"rollback":[],"confirmation_ko":"..."}`

type Client struct {
	Endpoint string
	Model    string
	APIKey   string
	HTTP     *http.Client
}

// Keep v1 field names for compatibility with existing plans and audit readers.
const SystemPromptEN = `You are the KIKI OS system administration planning agent.
Turn the user's request into a plan; never execute commands yourself.
Use English ASCII text for summaries, descriptions, impact and confirmation,
even though the legacy JSON field names end in _ko. Preserve exact paths and argv.
Show every command as an exact argv array and require the user's explicit approval.
If shell syntax is needed, show it explicitly as ["/bin/sh","-c","command"].
Do not guess devices, interfaces or UUIDs; use the supplied system inventory.
Include connection checks and recovery commands for network changes, and target
checks and mount verification for storage changes. Output one JSON object only:
{"schema":"kiki-ai-command-plan-v1","summary_ko":"...","risk":"low|normal|network|storage|system|critical","impact_ko":"...","commands":[{"description_ko":"...","argv":["program","arg"],"directory":"/","environment":{},"timeout_seconds":60}],"verification":[],"rollback":[],"confirmation_ko":"..."}`

type chatRequest struct {
	Model          string         `json:"model"`
	Messages       []chatMessage  `json:"messages"`
	Temperature    float64        `json:"temperature"`
	MaxTokens      int            `json:"max_tokens"`
	ResponseFormat map[string]any `json:"response_format"`
}

type chatMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type chatResponse struct {
	Choices []struct {
		Message      chatMessage `json:"message"`
		FinishReason string      `json:"finish_reason"`
	} `json:"choices"`
	Error *struct {
		Message string `json:"message"`
	} `json:"error,omitempty"`
}

func (client Client) Plan(ctx context.Context, request, inventory string) (Plan, error) {
	for attempt := 0; attempt < 2; attempt++ {
		plan, err := client.planAttempt(ctx, request, inventory, attempt > 0)
		var invalid *invalidReply
		if !errors.As(err, &invalid) {
			return plan, err
		}
	}
	return Plan{}, errors.New("The AI returned an invalid response after one retry. No commands were executed. Rephrase your request or use /status for local diagnostics")
}

type invalidReply struct{ err error }

func (e *invalidReply) Error() string { return e.err.Error() }

func (client Client) planAttempt(ctx context.Context, request, inventory string, retry bool) (Plan, error) {
	endpoint, err := url.Parse(client.Endpoint)
	if err != nil || (endpoint.Scheme != "http" && endpoint.Scheme != "https") || endpoint.Host == "" {
		return Plan{}, errors.New("AI endpoint must be a valid HTTP(S) URL")
	}
	if strings.TrimSpace(client.Model) == "" {
		return Plan{}, errors.New("AI model name is empty")
	}
	payload := chatRequest{
		Model: client.Model,
		Messages: []chatMessage{
			{Role: "system", Content: responseInstructions},
			{Role: "user", Content: "Current system state:\n" + inventory + "\n\nUser request:\n" + request},
		},
		Temperature:    0.1,
		MaxTokens:      2048,
		ResponseFormat: map[string]any{"type": "json_object", "schema": responseSchema()},
	}
	if retry {
		payload.Messages[0].Content += "\nThe previous response failed validation. Return exactly one complete object matching the supplied schema. Never invent commands for greetings or questions."
	}
	data, err := json.Marshal(payload)
	if err != nil {
		return Plan{}, err
	}
	httpClient := client.HTTP
	if httpClient == nil {
		httpClient = &http.Client{Timeout: 90 * time.Second}
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, client.Endpoint, bytes.NewReader(data))
	if err != nil {
		return Plan{}, err
	}
	req.Header.Set("Content-Type", "application/json")
	if client.APIKey != "" {
		req.Header.Set("Authorization", "Bearer "+client.APIKey)
	}
	response, err := httpClient.Do(req)
	if err != nil {
		return Plan{}, fmt.Errorf("AI runtime connection: %w", err)
	}
	defer response.Body.Close()
	body, err := io.ReadAll(io.LimitReader(response.Body, 4<<20))
	if err != nil {
		return Plan{}, err
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return Plan{}, fmt.Errorf("AI runtime HTTP %d: %s", response.StatusCode, strings.TrimSpace(string(body)))
	}
	var decoded chatResponse
	if err := json.Unmarshal(body, &decoded); err != nil {
		return Plan{}, fmt.Errorf("Parse AI response: %w", err)
	}
	if decoded.Error != nil {
		return Plan{}, errors.New(decoded.Error.Message)
	}
	if len(decoded.Choices) != 1 || strings.TrimSpace(decoded.Choices[0].Message.Content) == "" {
		return Plan{}, &invalidReply{errors.New("AI response must contain exactly one response")}
	}
	if reason := decoded.Choices[0].FinishReason; reason != "" && reason != "stop" {
		return Plan{}, &invalidReply{fmt.Errorf("Incomplete AI response: %s", reason)}
	}
	plan, err := DecodePlan([]byte(decoded.Choices[0].Message.Content))
	if err != nil {
		return Plan{}, &invalidReply{err}
	}
	return plan, nil
}
