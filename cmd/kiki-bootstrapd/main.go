package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"example.com/aos-pkg/internal/bootstrap"
)

func main() {
	host := flag.String("host", "127.0.0.1", "listen host")
	port := flag.Int("port", 8088, "listen port")
	state := flag.String("state", "installer/bootstrap/state/kiki-bootstrap-state.json", "state JSON path")
	artifacts := flag.String("artifacts", "installer/dist", "artifact directory")
	requireTokenFlag := flag.Bool("require-token", false, "require active registration tokens")
	adminTokenFile := flag.String("admin-token-file", "", "administrator bearer-token file (required for non-loopback listeners)")
	maxUpload := flag.Int64("max-upload-bytes", 128<<20, "maximum log-bundle upload size")
	flag.Parse()

	requireToken := *requireTokenFlag || strings.EqualFold(os.Getenv("KIKI_REQUIRE_TOKEN"), "true")
	adminToken, err := readOptionalToken(*adminTokenFile)
	if err != nil {
		log.Fatal(err)
	}
	if !isLoopbackHost(*host) && adminToken == "" {
		log.Fatal("-admin-token-file is required for non-loopback listeners")
	}
	store, err := bootstrap.NewStore(*state)
	if err != nil {
		log.Fatal(err)
	}

	handler := bootstrap.NewServerWithOptions(store, *artifacts, bootstrap.ServerOptions{RequireRegistrationToken: requireToken, AdminToken: adminToken, MaxUploadBytes: *maxUpload, Diagnostics: bootstrap.RunnerFromEnv()})
	addr := fmt.Sprintf("%s:%d", *host, *port)
	log.Printf("KIKI bootstrap server listening on http://%s", addr)
	log.Printf("state file: %s", *state)
	server := &http.Server{Addr: addr, Handler: handler, ReadHeaderTimeout: 10 * time.Second, ReadTimeout: 30 * time.Second, WriteTimeout: 2 * time.Minute, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 1 << 20}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdown)
	}()
	if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatal(err)
	}
}

func readOptionalToken(path string) (string, error) {
	if strings.TrimSpace(path) == "" {
		return "", nil
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return "", fmt.Errorf("read admin token file: %w", err)
	}
	token := strings.TrimSpace(string(data))
	if token == "" {
		return "", fmt.Errorf("admin token file is empty")
	}
	if len(token) < 32 {
		return "", fmt.Errorf("admin token must contain at least 32 characters")
	}
	info, err := os.Stat(path)
	if err != nil {
		return "", fmt.Errorf("stat admin token file: %w", err)
	}
	if info.Mode().Perm()&0o077 != 0 {
		return "", fmt.Errorf("admin token file permissions must not allow group or other access")
	}
	return token, nil
}

func isLoopbackHost(host string) bool {
	switch strings.TrimSpace(strings.ToLower(host)) {
	case "127.0.0.1", "localhost", "::1":
		return true
	default:
		return false
	}
}
