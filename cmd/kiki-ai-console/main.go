package main

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
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
		return result, fmt.Errorf("설정 파일 해석: %w", err)
	}
	if err := decoder.Decode(&struct{}{}); err != io.EOF {
		return result, errors.New("설정 파일 뒤에 허용되지 않은 데이터가 있습니다")
	}
	if result.Endpoint == "" || result.Model == "" {
		return result, errors.New("endpoint와 model 설정이 필요합니다")
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
	configPath := flag.String("config", "/etc/kiki/ai-console.json", "설정 파일")
	once := flag.String("once", "", "요청 하나를 계획만 하고 종료")
	flag.Parse()

	cfg, err := loadConfig(*configPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, "KIKI AI 콘솔 설정 오류:", err)
		os.Exit(1)
	}
	apiKey, err := readAPIKey(cfg.APIKeyFile)
	if err != nil {
		fmt.Fprintln(os.Stderr, "API 키 읽기 오류:", err)
		os.Exit(1)
	}
	console := newConsole(cfg, apiKey, os.Stdin, os.Stdout, os.Stderr)
	if *once != "" {
		if err := console.planOnly(context.Background(), *once); err != nil {
			fmt.Fprintln(os.Stderr, "계획 생성 오류:", err)
			os.Exit(1)
		}
		return
	}
	console.run(context.Background())
}

type planner interface {
	Plan(context.Context, string, string) (aiconsole.Plan, error)
}

type console struct {
	planner  planner
	executor aiconsole.Executor
	reader   *bufio.Scanner
	out      io.Writer
	errOut   io.Writer
	auditLog string
}

func newConsole(cfg config, apiKey string, in io.Reader, out, errOut io.Writer) *console {
	reader := bufio.NewScanner(in)
	reader.Buffer(make([]byte, 4096), 1024*1024)
	return &console{
		planner:  aiconsole.Client{Endpoint: cfg.Endpoint, Model: cfg.Model, APIKey: apiKey},
		executor: aiconsole.Executor{Stdout: out, Stderr: errOut},
		reader:   reader,
		out:      out,
		errOut:   errOut,
		auditLog: cfg.AuditLog,
	}
}

func (c *console) run(ctx context.Context) {
	fmt.Fprintln(c.out, "KIKI OS 한국어 AI 관리 콘솔 (tty1)")
	fmt.Fprintln(c.out, "명령은 반드시 화면에 표시한 뒤 '실행' 확인을 받아 수행합니다.")
	fmt.Fprintln(c.out, "독립 복구 셸은 Ctrl+Alt+F2 (tty2), 도움말은 /도움말 입니다.")
	for {
		fmt.Fprint(c.out, "\nkiki-ai> ")
		if !c.reader.Scan() {
			return
		}
		request := strings.TrimSpace(c.reader.Text())
		switch request {
		case "":
			continue
		case "/종료", "/exit", "exit", "quit":
			return
		case "/도움말", "/help":
			fmt.Fprintln(c.out, "자연어로 원하는 작업을 입력하세요. 예: '고정 IP를 설정해줘'.")
			fmt.Fprintln(c.out, "계획 확인 단계: 실행 / 수정 / 취소")
			continue
		case "/상태":
			fmt.Fprintln(c.out, aiconsole.CollectInventory(ctx))
			continue
		}
		if err := c.handle(ctx, request); err != nil {
			fmt.Fprintln(c.errOut, "요청 처리 오류:", err)
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
	fmt.Fprintln(c.out, "시스템 상태를 확인하고 실행 계획을 만드는 중입니다...")
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
		fmt.Fprint(c.out, "\n선택 [실행/수정/취소]: ")
		if !c.reader.Scan() {
			return io.EOF
		}
		switch strings.TrimSpace(c.reader.Text()) {
		case "취소", "cancel":
			_ = aiconsole.AppendAudit(c.auditLog, aiconsole.AuditEntry{Event: "cancelled", Request: request, Plan: &plan})
			fmt.Fprintln(c.out, "취소했습니다. 어떤 명령도 실행하지 않았습니다.")
			return nil
		case "수정", "edit":
			fmt.Fprint(c.out, "수정할 내용을 입력하세요: ")
			if !c.reader.Scan() {
				return io.EOF
			}
			request += "\n추가 수정 요청: " + strings.TrimSpace(c.reader.Text())
			continue
		case "실행", "execute":
			if err := aiconsole.AppendAudit(c.auditLog, aiconsole.AuditEntry{Event: "approved", Request: request, Plan: &plan}); err != nil {
				return fmt.Errorf("감사 로그 기록: %w", err)
			}
			results := c.executor.Run(ctx, plan.Commands)
			_ = aiconsole.AppendAudit(c.auditLog, aiconsole.AuditEntry{Event: "executed", Plan: &plan, Results: results})
			if failed(results) {
				fmt.Fprintln(c.errOut, "명령 실행이 중단되었습니다.")
				return c.offerRollback(ctx, plan)
			}
			if len(plan.Verification) > 0 {
				fmt.Fprintln(c.out, "\n검증 명령을 실행합니다.")
				verification := c.executor.Run(ctx, plan.Verification)
				_ = aiconsole.AppendAudit(c.auditLog, aiconsole.AuditEntry{Event: "verified", Plan: &plan, Results: verification})
				if failed(verification) {
					fmt.Fprintln(c.errOut, "검증이 실패했습니다.")
					return c.offerRollback(ctx, plan)
				}
			}
			fmt.Fprintln(c.out, "작업과 검증을 완료했습니다.")
			return nil
		default:
			fmt.Fprintln(c.out, "'실행', '수정', '취소' 중 하나를 정확히 입력하세요.")
		}
	}
}

func (c *console) offerRollback(ctx context.Context, plan aiconsole.Plan) error {
	if len(plan.Rollback) == 0 {
		fmt.Fprintln(c.errOut, "제공된 자동 롤백 명령이 없습니다. tty2 복구 셸을 사용하세요.")
		return nil
	}
	fmt.Fprintln(c.out, "\n사용 가능한 롤백 명령:")
	renderCommands(c.out, plan.Rollback)
	fmt.Fprint(c.out, "롤백하려면 '롤백' 입력, 아니면 Enter: ")
	if !c.reader.Scan() || strings.TrimSpace(c.reader.Text()) != "롤백" {
		return nil
	}
	results := c.executor.Run(ctx, plan.Rollback)
	_ = aiconsole.AppendAudit(c.auditLog, aiconsole.AuditEntry{Event: "rolled_back", Plan: &plan, Results: results})
	if failed(results) {
		return errors.New("롤백 명령 일부가 실패했습니다. tty2 복구 셸을 사용하세요")
	}
	fmt.Fprintln(c.out, "롤백을 완료했습니다.")
	return nil
}

func renderPlan(out io.Writer, plan aiconsole.Plan) {
	fmt.Fprintf(out, "\n요약: %s\n위험 등급: %s\n영향: %s\n", plan.SummaryKO, plan.Risk, plan.ImpactKO)
	fmt.Fprintln(out, "\n실행할 정확한 명령:")
	renderCommands(out, plan.Commands)
	if len(plan.Verification) > 0 {
		fmt.Fprintln(out, "\n실행 후 검증:")
		renderCommands(out, plan.Verification)
	}
	if len(plan.Rollback) > 0 {
		fmt.Fprintln(out, "\n실패 시 롤백 후보:")
		renderCommands(out, plan.Rollback)
	}
	fmt.Fprintln(out, "\n확인:", plan.ConfirmationKO)
}

func renderCommands(out io.Writer, commands []aiconsole.Command) {
	for index, command := range commands {
		fmt.Fprintf(out, "  %d. %s\n     $ %s\n", index+1, command.DescriptionKO, aiconsole.QuoteArgv(command.Argv))
		if command.Directory != "" {
			fmt.Fprintf(out, "     작업 경로: %s\n", command.Directory)
		}
		if len(command.Environment) > 0 {
			keys := make([]string, 0, len(command.Environment))
			for key := range command.Environment {
				keys = append(keys, key)
			}
			sort.Strings(keys)
			for _, key := range keys {
				fmt.Fprintf(out, "     환경 변수: %s=%s\n", key, command.Environment[key])
			}
		}
	}
}

func failed(results []aiconsole.Result) bool {
	return len(results) == 0 || results[len(results)-1].ExitCode != 0
}
