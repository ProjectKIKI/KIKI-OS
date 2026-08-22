package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"example.com/aos-pkg/internal/agent"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: kiki-agent <inventory|serve>")
		os.Exit(2)
	}
	if os.Args[1] == "serve" {
		serve(os.Args[2:])
		return
	}
	if len(os.Args) != 2 || os.Args[1] != "inventory" {
		fmt.Fprintln(os.Stderr, "usage: kiki-agent <inventory|serve>")
		os.Exit(2)
	}
	inventory, err := agent.NewCollector().Collect()
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(inventory); err != nil {
		fmt.Fprintln(os.Stderr, "error: encode inventory:", err)
		os.Exit(1)
	}
}

func serve(arguments []string) {
	flags := flag.NewFlagSet("serve", flag.ExitOnError)
	infraOpsURL := flags.String("infraops-url", "", "InfraOps base URL")
	tokenFile := flags.String("token-file", "", "bearer-token file")
	nodeName := flags.String("node-name", "", "Kubernetes node name")
	interval := flags.Duration("interval", 60*time.Second, "inventory reporting interval")
	_ = flags.Parse(arguments)
	if *infraOpsURL == "" || *tokenFile == "" || *nodeName == "" {
		log.Fatal("-infraops-url, -token-file, and -node-name are required")
	}
	data, err := os.ReadFile(*tokenFile)
	if err != nil {
		log.Fatal(err)
	}
	token := strings.TrimSpace(string(data))
	collector := agent.NewCollector()
	reporter := agent.Reporter{BaseURL: *infraOpsURL, Token: token, Actor: "kiki-agent", NodeName: *nodeName, HTTP: &http.Client{Timeout: 30 * time.Second}, Collect: collector.Collect, Interval: *interval, OnError: func(err error) { log.Printf("inventory report failed: %v", err) }}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := reporter.Run(ctx); err != nil {
		log.Fatal(err)
	}
}
