package modelruntime

import (
	"testing"

	"example.com/aos-pkg/internal/agent"
)

const gib = uint64(1024 * 1024 * 1024)

func TestSelectCPUAndGPURuntimes(t *testing.T) {
	tests := []struct {
		name      string
		model     Model
		placement Placement
		inventory agent.Inventory
		engine    string
		backend   string
	}{
		{
			name: "CPU GGUF", model: Model{Format: "gguf", MinimumMemoryBytes: 8 * gib},
			inventory: agent.Inventory{Memory: agent.Memory{AvailableBytes: 16 * gib}}, engine: "llama.cpp", backend: "cpu",
		},
		{
			name: "NVIDIA safetensors", model: Model{Format: "safetensors", MinimumMemoryBytes: 8 * gib, MinimumVRAMBytes: 12 * gib},
			inventory: agent.Inventory{Memory: agent.Memory{AvailableBytes: 16 * gib}, Accelerators: []agent.Accelerator{{ID: "0000:01:00.0", Vendor: "nvidia", Backend: "cuda", MemoryBytes: 24 * gib}}},
			engine:    "vllm", backend: "cuda",
		},
		{
			name: "AMD GGUF offload", model: Model{Format: "gguf", MinimumMemoryBytes: 8 * gib, MinimumVRAMBytes: 8 * gib},
			inventory: agent.Inventory{Memory: agent.Memory{AvailableBytes: 16 * gib}, Accelerators: []agent.Accelerator{{ID: "0000:02:00.0", Vendor: "amd", Backend: "rocm", MemoryBytes: 16 * gib}}},
			engine:    "llama.cpp", backend: "rocm",
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			plan := Select(test.model, test.placement, test.inventory)
			if plan.Phase != "Ready" || plan.Engine != test.engine || plan.Backend != test.backend {
				t.Fatalf("unexpected plan: %#v", plan)
			}
		})
	}
}

func TestSelectDoesNotSilentlyChangeModelOrRuntime(t *testing.T) {
	model := Model{Format: "safetensors", MinimumMemoryBytes: 8 * gib, MinimumVRAMBytes: 16 * gib}
	inventory := agent.Inventory{Memory: agent.Memory{AvailableBytes: 64 * gib}, Accelerators: []agent.Accelerator{{ID: "gpu", Vendor: "nvidia", Backend: "cuda", MemoryBytes: 8 * gib}}}
	plan := Select(model, Placement{}, inventory)
	if plan.Phase != "Pending" || plan.Conditions[0].Reason != "RuntimeUnavailable" {
		t.Fatalf("safetensors unexpectedly fell back to a different model format: %#v", plan)
	}
}

func TestSelectExplainsInsufficientMemory(t *testing.T) {
	plan := Select(Model{Format: "gguf", MinimumMemoryBytes: 8 * gib}, Placement{}, agent.Inventory{Memory: agent.Memory{AvailableBytes: 4 * gib}})
	if plan.Phase != "Pending" || plan.Conditions[0].Reason != "InsufficientMemory" {
		t.Fatalf("unexpected plan: %#v", plan)
	}
}
