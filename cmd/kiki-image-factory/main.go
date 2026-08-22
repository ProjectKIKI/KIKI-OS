package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"

	"example.com/aos-pkg/internal/imagefactory"
	"example.com/aos-pkg/internal/supplychain"
)

func main() {
	root := flag.String("root", "", "factory artifact root")
	timeout := flag.Duration("timeout", 90*time.Minute, "maximum task duration")
	infraOpsURL := flag.String("infraops-url", "", "InfraOps base URL; claim one task when set")
	tokenFile := flag.String("token-file", "", "InfraOps bearer-token file")
	actor := flag.String("actor", "image-factory", "audited worker identity")
	evidenceDir := flag.String("evidence-dir", "", "supply-chain evidence directory")
	signingKey := flag.String("signing-key", "/run/secrets/signing/cosign.key", "Cosign private-key path")
	flag.Parse()
	if *root == "" {
		fmt.Fprintln(os.Stderr, "-root is required")
		os.Exit(2)
	}
	ctx := context.Background()
	var task imagefactory.Task
	var client *imagefactory.Client
	if *infraOpsURL == "" {
		decoder := json.NewDecoder(os.Stdin)
		decoder.DisallowUnknownFields()
		if err := decoder.Decode(&task); err != nil {
			fmt.Fprintln(os.Stderr, "error: decode task:", err)
			os.Exit(1)
		}
	} else {
		if *tokenFile == "" {
			fmt.Fprintln(os.Stderr, "error: -token-file is required with -infraops-url")
			os.Exit(2)
		}
		data, err := os.ReadFile(*tokenFile)
		if err != nil {
			fmt.Fprintln(os.Stderr, "error: read token:", err)
			os.Exit(1)
		}
		client = &imagefactory.Client{BaseURL: *infraOpsURL, Token: strings.TrimSpace(string(data)), Actor: *actor, HTTP: &http.Client{Timeout: 30 * time.Second}, SupportedTypes: []string{"iso", "pxe", "disk"}}
		claimed, err := client.Claim(ctx)
		if err != nil {
			fmt.Fprintln(os.Stderr, "error: claim task:", err)
			os.Exit(1)
		}
		task = *claimed.FactoryTask
	}
	worker := imagefactory.Worker{Runner: imagefactory.ExecRunner{}, RootDir: *root, Timeout: *timeout}
	if client != nil {
		worker.Progress = func(progressContext context.Context, phase string) error {
			return client.Report(progressContext, task.Request.BuildID, phase, "")
		}
	}
	result, err := worker.Execute(ctx, task)
	if err != nil {
		if client != nil {
			_ = client.Report(context.Background(), task.Request.BuildID, "Failed", err.Error())
		}
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
	if client != nil {
		if *evidenceDir == "" {
			fail(client, task.Request.BuildID, "-evidence-dir is required in InfraOps mode")
		}
		if err := client.Report(ctx, task.Request.BuildID, "Scanning", ""); err != nil {
			fail(client, task.Request.BuildID, err.Error())
		}
		evidence, err := supplychain.FinalizeFile(supplychain.FileFinalizeOptions{BuildID: task.Request.BuildID, Artifact: result.ArtifactPath, Source: task.Request.Source.URL, Revision: task.Request.Source.Revision, Artifacts: *evidenceDir, PackageType: task.Request.Type, SigningKey: *signingKey})
		if err != nil {
			fail(client, task.Request.BuildID, err.Error())
		}
		for _, phase := range []string{"Signing", "Publishing"} {
			if err := client.Report(ctx, task.Request.BuildID, phase, ""); err != nil {
				fail(client, task.Request.BuildID, err.Error())
			}
		}
		report := imagefactory.BuildReport{Phase: "Succeeded", Digest: evidence.Digest, SizeBytes: uint64(evidence.SizeBytes), MediaType: mediaType(task.Request.Type), SBOMDigest: evidence.SBOMDigest, ScanDigest: evidence.ScanDigest, ProvenanceDigest: evidence.ProvenanceDigest, SignatureDigest: evidence.SignatureDigest}
		if err := client.ReportResult(ctx, task.Request.BuildID, report); err != nil {
			fail(client, task.Request.BuildID, err.Error())
		}
	}
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(result); err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}

func fail(client *imagefactory.Client, buildID, message string) {
	_ = client.Report(context.Background(), buildID, "Failed", message)
	fmt.Fprintln(os.Stderr, "error:", message)
	os.Exit(1)
}

func mediaType(kind string) string {
	switch kind {
	case "iso":
		return "application/vnd.kiki.os.iso"
	case "pxe":
		return "application/vnd.kiki.os.pxe+gzip"
	case "disk":
		return "application/vnd.kiki.os.disk.qcow2"
	default:
		return "application/octet-stream"
	}
}
