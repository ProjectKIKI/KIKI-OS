package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"

	"example.com/aos-pkg/internal/modelbuild"
)

func main() {
	if len(os.Args) < 2 || os.Args[1] != "build-push" {
		fmt.Fprintln(os.Stderr, "usage: kiki-model-builder build-push [options]")
		os.Exit(2)
	}
	flags := flag.NewFlagSet("build-push", flag.ExitOnError)
	options := modelbuild.Options{}
	flags.StringVar(&options.Input, "input", "", "model source path below /workspace/source")
	flags.StringVar(&options.InputFormat, "input-format", "", "gguf or safetensors")
	flags.StringVar(&options.OutputFormat, "output-format", "", "gguf or safetensors")
	flags.StringVar(&options.Quantization, "quantization", "none", "none, q4_k_m, q5_k_m, or q8_0")
	flags.StringVar(&options.Destination, "destination", "", "tagged build destination")
	flags.StringVar(&options.Metadata, "metadata", "", "digest metadata output")
	flags.StringVar(&options.LicenseID, "license", "", "SPDX-like license identifier")
	flags.StringVar(&options.ConverterPath, "converter", "/opt/llama.cpp/convert_hf_to_gguf.py", "trusted converter path")
	flags.StringVar(&options.QuantizerPath, "quantizer", "/opt/llama.cpp/llama-quantize", "trusted quantizer path")
	_ = flags.Parse(os.Args[2:])
	result, err := modelbuild.BuildPush(context.Background(), options)
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(result); err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}
