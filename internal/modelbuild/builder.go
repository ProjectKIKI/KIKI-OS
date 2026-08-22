package modelbuild

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
)

type Options struct {
	Input         string
	InputFormat   string
	OutputFormat  string
	Quantization  string
	Destination   string
	Metadata      string
	LicenseID     string
	ConverterPath string
	QuantizerPath string
	WorkspaceRoot string
	Runner        Runner
}

type Result struct {
	Reference string `json:"reference"`
	Digest    string `json:"digest"`
	MediaType string `json:"media_type"`
}

type Runner interface {
	Output(context.Context, string, ...string) ([]byte, error)
}

type ExecRunner struct{}

func (ExecRunner) Output(ctx context.Context, name string, args ...string) ([]byte, error) {
	command := exec.CommandContext(ctx, name, args...)
	var stdout bytes.Buffer
	command.Stdout = &stdout
	command.Stderr = os.Stderr
	if err := command.Run(); err != nil {
		return nil, err
	}
	return stdout.Bytes(), nil
}

var digestPattern = regexp.MustCompile(`^sha256:[a-f0-9]{64}$`)
var destinationPattern = regexp.MustCompile(`^[a-z0-9.-]+(?::[0-9]+)?/[a-z0-9]+(?:[._/-][a-z0-9]+)*:build-[a-z0-9]([-a-z0-9.]{0,61}[a-z0-9])?$`)
var licensePattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9.+-]{0,63}$`)

func BuildPush(ctx context.Context, options Options) (Result, error) {
	if options.Runner == nil {
		options.Runner = ExecRunner{}
	}
	if options.ConverterPath == "" {
		options.ConverterPath = "/opt/llama.cpp/convert_hf_to_gguf.py"
	}
	if options.QuantizerPath == "" {
		options.QuantizerPath = "/opt/llama.cpp/llama-quantize"
	}
	if options.InputFormat != "gguf" && options.InputFormat != "safetensors" {
		return Result{}, errors.New("input format must be gguf or safetensors")
	}
	if options.OutputFormat != "gguf" && options.OutputFormat != "safetensors" {
		return Result{}, errors.New("output format must be gguf or safetensors")
	}
	quantizations := map[string]bool{"none": true, "q4_k_m": true, "q5_k_m": true, "q8_0": true}
	if !quantizations[options.Quantization] || (options.OutputFormat == "safetensors" && options.Quantization != "none") {
		return Result{}, errors.New("unsupported output quantization")
	}
	if options.InputFormat == "gguf" && options.OutputFormat == "safetensors" {
		return Result{}, errors.New("GGUF to safetensors conversion is not supported")
	}
	if !destinationPattern.MatchString(options.Destination) || !licensePattern.MatchString(options.LicenseID) {
		return Result{}, errors.New("destination or SPDX-like license ID is invalid")
	}
	if options.WorkspaceRoot == "" {
		options.WorkspaceRoot = "/workspace/source"
	}
	input, err := secureInput(options.Input, options.WorkspaceRoot)
	if err != nil {
		return Result{}, err
	}
	work, err := os.MkdirTemp("", "kiki-model-build-")
	if err != nil {
		return Result{}, err
	}
	defer os.RemoveAll(work)
	artifact := input
	if options.OutputFormat == "gguf" && options.InputFormat == "safetensors" {
		artifact = filepath.Join(work, "model-f16.gguf")
		if _, err := options.Runner.Output(ctx, "python3", options.ConverterPath, input, "--outfile", artifact, "--outtype", "f16"); err != nil {
			return Result{}, fmt.Errorf("convert safetensors to GGUF: %w", err)
		}
	}
	if options.OutputFormat == "gguf" && options.Quantization != "none" {
		quantized := filepath.Join(work, "model-"+options.Quantization+".gguf")
		if _, err := options.Runner.Output(ctx, options.QuantizerPath, artifact, quantized, options.Quantization); err != nil {
			return Result{}, fmt.Errorf("quantize GGUF: %w", err)
		}
		artifact = quantized
	}
	info, err := os.Stat(artifact)
	if err != nil {
		return Result{}, fmt.Errorf("inspect model output: %w", err)
	}
	if (!info.Mode().IsRegular() && !info.IsDir()) || info.Size() == 0 && info.Mode().IsRegular() {
		return Result{}, errors.New("model output is empty or unsupported")
	}
	if options.OutputFormat == "safetensors" {
		if !info.IsDir() {
			return Result{}, errors.New("safetensors output must be a directory")
		}
		matches, err := filepath.Glob(filepath.Join(artifact, "*.safetensors"))
		if err != nil || len(matches) == 0 {
			return Result{}, errors.New("safetensors directory contains no model shard")
		}
	}
	layerType := "application/vnd.kiki.model.safetensors.v1+tar"
	if options.OutputFormat == "gguf" {
		layerType = "application/vnd.kiki.model.gguf.v1"
	}
	artifactType := "application/vnd.kiki.model." + options.OutputFormat + ".v1"
	output, err := options.Runner.Output(ctx, "oras", "push", "--artifact-type", artifactType, "--annotation", "org.opencontainers.image.licenses="+options.LicenseID, "--annotation", "io.kiki.model.format="+options.OutputFormat, "--annotation", "io.kiki.model.quantization="+options.Quantization, options.Destination, artifact+":"+layerType, "--format", "json")
	if err != nil {
		return Result{}, fmt.Errorf("push model OCI artifact: %w", err)
	}
	var descriptor struct {
		Reference string `json:"reference"`
		Digest    string `json:"digest"`
		MediaType string `json:"mediaType"`
		Size      uint64 `json:"size"`
	}
	if err := json.Unmarshal(output, &descriptor); err != nil || !digestPattern.MatchString(descriptor.Digest) || !strings.HasSuffix(descriptor.Reference, "@"+descriptor.Digest) || descriptor.Size == 0 || descriptor.MediaType == "" {
		return Result{}, errors.New("ORAS output does not contain a valid immutable manifest descriptor")
	}
	metadata, err := json.Marshal(map[string]any{"containerimage.digest": descriptor.Digest, "containerimage.descriptor": map[string]any{"digest": descriptor.Digest, "size": descriptor.Size, "mediaType": descriptor.MediaType}})
	if err != nil {
		return Result{}, err
	}
	if err := writeAtomic(options.Metadata, metadata); err != nil {
		return Result{}, err
	}
	return Result{Reference: descriptor.Reference, Digest: descriptor.Digest, MediaType: descriptor.MediaType}, nil
}

func secureInput(value, workspaceRoot string) (string, error) {
	clean := filepath.Clean(value)
	root, err := filepath.EvalSymlinks(filepath.Clean(workspaceRoot))
	if err != nil {
		return "", fmt.Errorf("resolve workspace root: %w", err)
	}
	if clean != root && !strings.HasPrefix(clean, root+string(filepath.Separator)) {
		return "", errors.New("model input must remain below /workspace/source")
	}
	resolved, err := filepath.EvalSymlinks(clean)
	if err != nil {
		return "", fmt.Errorf("resolve model input: %w", err)
	}
	if resolved != root && !strings.HasPrefix(resolved, root+string(filepath.Separator)) {
		return "", errors.New("model input symlink escapes source root")
	}
	return resolved, nil
}

func writeAtomic(path string, data []byte) error {
	if path == "" {
		return errors.New("metadata path is required")
	}
	directory := filepath.Dir(filepath.Clean(path))
	if err := os.MkdirAll(directory, 0o750); err != nil {
		return err
	}
	file, err := os.CreateTemp(directory, ".model-metadata-*.tmp")
	if err != nil {
		return err
	}
	name := file.Name()
	committed := false
	defer func() {
		_ = file.Close()
		if !committed {
			_ = os.Remove(name)
		}
	}()
	if err := file.Chmod(0o640); err != nil {
		return err
	}
	if _, err := file.Write(data); err != nil {
		return err
	}
	if err := file.Sync(); err != nil {
		return err
	}
	if err := file.Close(); err != nil {
		return err
	}
	if err := os.Rename(name, path); err != nil {
		return err
	}
	committed = true
	return nil
}
