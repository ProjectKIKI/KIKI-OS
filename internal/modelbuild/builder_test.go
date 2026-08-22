package modelbuild

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

type fakeRunner struct{ calls []string }

func (runner *fakeRunner) Output(_ context.Context, name string, args ...string) ([]byte, error) {
	runner.calls = append(runner.calls, name+" "+strings.Join(args, " "))
	if strings.Contains(name, "llama-quantize") {
		if err := os.WriteFile(args[1], []byte("QUANTIZED"), 0o640); err != nil {
			return nil, err
		}
	}
	if name == "oras" {
		return []byte(`{"reference":"registry.example.com/models/ops@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","mediaType":"application/vnd.oci.image.manifest.v1+json","size":812}`), nil
	}
	return nil, nil
}

func TestBuildPushQuantizesAndRecordsImmutableORASDigest(t *testing.T) {
	workspace := filepath.Join(t.TempDir(), "source")
	if err := os.MkdirAll(workspace, 0o750); err != nil {
		t.Fatal(err)
	}
	input := filepath.Join(workspace, "model.gguf")
	if err := os.WriteFile(input, []byte("GGUF"), 0o640); err != nil {
		t.Fatal(err)
	}
	metadata := filepath.Join(t.TempDir(), "metadata.json")
	runner := &fakeRunner{}
	result, err := BuildPush(context.Background(), Options{Input: input, InputFormat: "gguf", OutputFormat: "gguf", Quantization: "q4_k_m", Destination: "registry.example.com/models/ops:build-model-0001", Metadata: metadata, LicenseID: "Apache-2.0", QuantizerPath: "/tools/llama-quantize", WorkspaceRoot: workspace, Runner: runner})
	if err != nil {
		t.Fatal(err)
	}
	if !digestPattern.MatchString(result.Digest) || len(runner.calls) != 2 || !strings.HasPrefix(runner.calls[0], "/tools/llama-quantize ") || !strings.Contains(runner.calls[1], "--format json") {
		t.Fatalf("unexpected build: result=%#v calls=%#v", result, runner.calls)
	}
	data, err := os.ReadFile(metadata)
	if err != nil || !strings.Contains(string(data), result.Digest) {
		t.Fatalf("metadata not recorded: %s (%v)", data, err)
	}
}

func TestBuildPushRejectsInputSymlinkEscape(t *testing.T) {
	directory := t.TempDir()
	workspace := filepath.Join(directory, "source")
	if err := os.MkdirAll(workspace, 0o750); err != nil {
		t.Fatal(err)
	}
	outside := filepath.Join(directory, "outside.gguf")
	_ = os.WriteFile(outside, []byte("GGUF"), 0o640)
	link := filepath.Join(workspace, "model.gguf")
	if err := os.Symlink(outside, link); err != nil {
		t.Fatal(err)
	}
	_, err := BuildPush(context.Background(), Options{Input: link, InputFormat: "gguf", OutputFormat: "gguf", Quantization: "none", Destination: "registry.example.com/models/ops:build-model-0001", Metadata: filepath.Join(directory, "metadata.json"), LicenseID: "MIT", WorkspaceRoot: workspace, Runner: &fakeRunner{}})
	if err == nil || !strings.Contains(err.Error(), "escapes") {
		t.Fatalf("escaping symlink accepted: %v", err)
	}
}
