package modelruntime

import (
	"fmt"
	"sort"

	"example.com/aos-pkg/internal/agent"
)

type Model struct {
	Digest             string `json:"digest"`
	Format             string `json:"format"`
	SizeBytes          uint64 `json:"size_bytes"`
	MinimumMemoryBytes uint64 `json:"minimum_memory_bytes"`
	MinimumVRAMBytes   uint64 `json:"minimum_vram_bytes,omitempty"`
}

type Placement struct {
	Runtime     string `json:"runtime"`
	Accelerator string `json:"accelerator"`
}

type Plan struct {
	Phase          string      `json:"phase"`
	Engine         string      `json:"engine,omitempty"`
	Backend        string      `json:"backend,omitempty"`
	AcceleratorID  string      `json:"accelerator_id,omitempty"`
	GPUOffload     bool        `json:"gpu_offload"`
	RequiredMemory uint64      `json:"required_memory_bytes"`
	Conditions     []Condition `json:"conditions"`
}

type Condition struct {
	Type    string `json:"type"`
	Status  string `json:"status"`
	Reason  string `json:"reason"`
	Message string `json:"message"`
}

func Select(model Model, placement Placement, inventory agent.Inventory) Plan {
	if model.Format != "gguf" && model.Format != "safetensors" {
		return pending("UnsupportedModelFormat", "model format must be gguf or safetensors", model.MinimumMemoryBytes)
	}
	if placement.Runtime != "" && placement.Runtime != "auto" && placement.Runtime != "llama.cpp" && placement.Runtime != "vllm" {
		return pending("UnsupportedRuntime", "runtime must be auto, llama.cpp, or vllm", model.MinimumMemoryBytes)
	}
	if placement.Accelerator == "" {
		placement.Accelerator = "auto"
	}

	accelerators := append([]agent.Accelerator(nil), inventory.Accelerators...)
	sort.SliceStable(accelerators, func(i, j int) bool { return accelerators[i].MemoryBytes > accelerators[j].MemoryBytes })
	for _, accelerator := range accelerators {
		if placement.Accelerator == "cpu" || (placement.Accelerator != "auto" && placement.Accelerator != accelerator.Vendor) {
			continue
		}
		if model.MinimumVRAMBytes > 0 && accelerator.MemoryBytes < model.MinimumVRAMBytes {
			continue
		}
		if model.Format == "safetensors" && (placement.Runtime == "" || placement.Runtime == "auto" || placement.Runtime == "vllm") && supportsVLLM(accelerator) {
			return ready("vllm", accelerator.Backend, accelerator.ID, false, model.MinimumMemoryBytes)
		}
		if model.Format == "gguf" && (placement.Runtime == "" || placement.Runtime == "auto" || placement.Runtime == "llama.cpp") {
			return ready("llama.cpp", accelerator.Backend, accelerator.ID, true, model.MinimumMemoryBytes)
		}
	}

	if placement.Accelerator != "auto" && placement.Accelerator != "cpu" {
		return pending("AcceleratorUnavailable", fmt.Sprintf("no compatible %s accelerator has enough memory", placement.Accelerator), model.MinimumMemoryBytes)
	}
	if model.Format != "gguf" || placement.Runtime == "vllm" {
		return pending("RuntimeUnavailable", "CPU MVP requires a GGUF model with llama.cpp", model.MinimumMemoryBytes)
	}
	if inventory.Memory.AvailableBytes < model.MinimumMemoryBytes {
		return pending("InsufficientMemory", fmt.Sprintf("available memory %d is below required %d", inventory.Memory.AvailableBytes, model.MinimumMemoryBytes), model.MinimumMemoryBytes)
	}
	return ready("llama.cpp", "cpu", "", false, model.MinimumMemoryBytes)
}

func supportsVLLM(accelerator agent.Accelerator) bool {
	return accelerator.Backend == "cuda" || accelerator.Backend == "rocm" || accelerator.Backend == "xpu"
}

func ready(engine, backend, acceleratorID string, offload bool, required uint64) Plan {
	return Plan{
		Phase: "Ready", Engine: engine, Backend: backend, AcceleratorID: acceleratorID,
		GPUOffload: offload, RequiredMemory: required,
		Conditions: []Condition{{Type: "Scheduled", Status: "True", Reason: "CompatibleRuntimeSelected", Message: engine + " selected on " + backend}},
	}
}

func pending(reason, message string, required uint64) Plan {
	return Plan{
		Phase: "Pending", RequiredMemory: required,
		Conditions: []Condition{{Type: "Scheduled", Status: "False", Reason: reason, Message: message}},
	}
}
