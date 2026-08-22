package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"strings"

	"example.com/aos-pkg/internal/supplychain"
)

func main() {
	if len(os.Args) < 2 || (os.Args[1] != "finalize" && os.Args[1] != "finalize-file") {
		fmt.Fprintln(os.Stderr, "usage: kiki-supplychain <finalize|finalize-file> [options]")
		os.Exit(2)
	}
	if os.Args[1] == "finalize-file" {
		finalizeFile()
		return
	}
	flags := flag.NewFlagSet("finalize", flag.ExitOnError)
	options := supplychain.FinalizeOptions{}
	flags.StringVar(&options.BuildID, "build-id", "", "build ID")
	flags.StringVar(&options.Image, "image", "", "mutable build output reference")
	flags.StringVar(&options.Metadata, "metadata", "", "BuildKit metadata path")
	flags.StringVar(&options.Source, "source", "", "source URL")
	flags.StringVar(&options.Revision, "revision", "", "source commit")
	flags.StringVar(&options.Artifacts, "artifacts", "", "artifact output directory")
	flags.StringVar(&options.PackageType, "package-type", "", "oci, cpm, or model")
	flags.StringVar(&options.SigningKey, "signing-key", "/run/secrets/signing/cosign.key", "Cosign key path")
	infraOpsURL := flags.String("infraops-url", "", "InfraOps URL for trusted result reporting")
	tokenFile := flags.String("token-file", "", "build reporter token file")
	actor := flags.String("actor", "build-worker", "audited build worker identity")
	_ = flags.Parse(os.Args[2:])
	reporter, reportEnabled, err := newReporter(*infraOpsURL, *tokenFile, *actor)
	if err != nil {
		fail(nil, options.BuildID, err)
	}
	if reportEnabled {
		if err := reporter.Advance(context.Background(), options.BuildID, "Fetching", "Validating", "Building", "Testing", "Scanning"); err != nil {
			fail(&reporter, options.BuildID, err)
		}
	}
	evidence, err := supplychain.Finalize(options)
	if err != nil {
		fail(enabledReporter(reporter, reportEnabled), options.BuildID, err)
	}
	if reportEnabled {
		if err := reporter.Advance(context.Background(), options.BuildID, "Signing", "Publishing"); err != nil {
			fail(&reporter, options.BuildID, err)
		}
		report := supplychain.BuildReport{Phase: "Succeeded", Digest: evidence.Digest, SizeBytes: evidence.SizeBytes, MediaType: evidence.MediaType, SBOMDigest: evidence.SBOMDigest, ScanDigest: evidence.ScanDigest, ProvenanceDigest: evidence.ProvenanceDigest, SignatureDigest: evidence.SignatureDigest}
		if err := reporter.Report(context.Background(), options.BuildID, report); err != nil {
			fail(&reporter, options.BuildID, err)
		}
	}
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(evidence); err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}

func newReporter(baseURL, tokenFile, actor string) (supplychain.Reporter, bool, error) {
	if baseURL == "" && tokenFile == "" {
		return supplychain.Reporter{}, false, nil
	}
	if baseURL == "" || tokenFile == "" {
		return supplychain.Reporter{}, false, fmt.Errorf("-infraops-url and -token-file must be supplied together")
	}
	data, err := os.ReadFile(tokenFile)
	if err != nil {
		return supplychain.Reporter{}, false, err
	}
	token := strings.TrimSpace(string(data))
	if token == "" {
		return supplychain.Reporter{}, false, fmt.Errorf("build reporter token is empty")
	}
	return supplychain.Reporter{BaseURL: baseURL, Token: token, Actor: actor}, true, nil
}

func enabledReporter(reporter supplychain.Reporter, enabled bool) *supplychain.Reporter {
	if !enabled {
		return nil
	}
	return &reporter
}

func fail(reporter *supplychain.Reporter, buildID string, err error) {
	if reporter != nil {
		_ = reporter.Report(context.Background(), buildID, supplychain.BuildReport{Phase: "Failed", Message: err.Error()})
	}
	fmt.Fprintln(os.Stderr, "error:", err)
	os.Exit(1)
}

func finalizeFile() {
	flags := flag.NewFlagSet("finalize-file", flag.ExitOnError)
	options := supplychain.FileFinalizeOptions{}
	flags.StringVar(&options.BuildID, "build-id", "", "build ID")
	flags.StringVar(&options.Artifact, "artifact", "", "file artifact path")
	flags.StringVar(&options.Source, "source", "", "source URL")
	flags.StringVar(&options.Revision, "revision", "", "source commit")
	flags.StringVar(&options.Artifacts, "evidence-dir", "", "evidence output directory")
	flags.StringVar(&options.PackageType, "package-type", "", "bos, iso, pxe, disk, or model")
	flags.StringVar(&options.SigningKey, "signing-key", "/run/secrets/signing/cosign.key", "Cosign key path")
	infraOpsURL := flags.String("infraops-url", "", "InfraOps URL for trusted result reporting")
	tokenFile := flags.String("token-file", "", "build reporter token file")
	actor := flags.String("actor", "build-worker", "audited build worker identity")
	_ = flags.Parse(os.Args[2:])
	reporter, reportEnabled, err := newReporter(*infraOpsURL, *tokenFile, *actor)
	if err != nil {
		fail(nil, options.BuildID, err)
	}
	if reportEnabled {
		if err := reporter.Advance(context.Background(), options.BuildID, "Fetching", "Validating", "Building", "Testing", "Scanning"); err != nil {
			fail(&reporter, options.BuildID, err)
		}
	}
	evidence, err := supplychain.FinalizeFile(options)
	if err != nil {
		fail(enabledReporter(reporter, reportEnabled), options.BuildID, err)
	}
	if reportEnabled {
		if err := reporter.Advance(context.Background(), options.BuildID, "Signing", "Publishing"); err != nil {
			fail(&reporter, options.BuildID, err)
		}
		report := supplychain.BuildReport{Phase: "Succeeded", Digest: evidence.Digest, SizeBytes: uint64(evidence.SizeBytes), MediaType: fileMediaType(options.PackageType), SBOMDigest: evidence.SBOMDigest, ScanDigest: evidence.ScanDigest, ProvenanceDigest: evidence.ProvenanceDigest, SignatureDigest: evidence.SignatureDigest}
		if err := reporter.Report(context.Background(), options.BuildID, report); err != nil {
			fail(&reporter, options.BuildID, err)
		}
	}
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(evidence); err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}

func fileMediaType(kind string) string {
	switch kind {
	case "bos":
		return "application/vnd.kiki.bos.v1+gzip"
	case "iso":
		return "application/vnd.kiki.os.iso"
	case "pxe":
		return "application/vnd.kiki.os.pxe+gzip"
	case "disk":
		return "application/vnd.kiki.os.disk.qcow2"
	case "model":
		return "application/vnd.kiki.model.v1"
	default:
		return "application/octet-stream"
	}
}
