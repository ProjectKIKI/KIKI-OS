package modelruntime

import (
	"strings"
	"testing"
)

const pinnedImage = "registry.local/kiki/runtime@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
const modelSource = "oci://registry.local/kiki/model"
const modelDigest = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

func TestRenderRestrictedCPUModelPod(t *testing.T) {
	template, err := RenderPodTemplate(PodSpec{
		Name: "ops", Namespace: "kiki-system", ModelAlias: "ops-model", ModelPath: "/models/ops/model.gguf",
		ModelSource: modelSource, ModelDigest: modelDigest, FetcherImage: pinnedImage, CachePVC: "kiki-model-cache", Port: 8000, ContextLength: 8192, LlamaImage: pinnedImage,
	}, Plan{Phase: "Ready", Engine: "llama.cpp", Backend: "cpu"})
	if err != nil {
		t.Fatal(err)
	}
	metadata := template["metadata"].(map[string]any)
	if template["apiVersion"] != "v1" || template["kind"] != "Pod" || metadata["name"] != "ops" || metadata["namespace"] != "kiki-system" {
		t.Fatalf("rendered object is not an applyable Pod: %#v", template)
	}
	spec := template["spec"].(map[string]any)
	if spec["automountServiceAccountToken"] != false {
		t.Fatal("service account token was mounted")
	}
	container := spec["containers"].([]any)[0].(map[string]any)
	security := container["securityContext"].(map[string]any)
	if security["allowPrivilegeEscalation"] != false || security["readOnlyRootFilesystem"] != true {
		t.Fatalf("container is not restricted: %#v", security)
	}
	args := strings.Join(container["args"].([]string), " ")
	if !strings.Contains(args, "--model /models/ops/model.gguf") || strings.Contains(args, "--gpu-layers") {
		t.Fatalf("unexpected llama.cpp arguments: %s", args)
	}
	fetcher := spec["initContainers"].([]any)[0].(map[string]any)
	fetchArgs := strings.Join(fetcher["args"].([]string), " ")
	if !strings.Contains(fetchArgs, "registry.local/kiki/model@"+modelDigest) || fetcher["image"] != pinnedImage {
		t.Fatalf("model fetch is not digest bound: %#v", fetcher)
	}
	mount := container["volumeMounts"].([]any)[0].(map[string]any)
	if mount["readOnly"] != true {
		t.Fatal("runtime model mount must remain read-only")
	}
}

func TestRenderGPUResourceAndPinnedImage(t *testing.T) {
	template, err := RenderPodTemplate(PodSpec{
		Name: "ops", Namespace: "kiki-system", ModelAlias: "ops", ModelPath: "/models/ops",
		ModelSource: modelSource, ModelDigest: modelDigest, FetcherImage: pinnedImage, CachePVC: "cache", Port: 8000, ContextLength: 4096, VLLMImage: pinnedImage,
	}, Plan{Phase: "Ready", Engine: "vllm", Backend: "cuda", AcceleratorID: "gpu0"})
	if err != nil {
		t.Fatal(err)
	}
	container := template["spec"].(map[string]any)["containers"].([]any)[0].(map[string]any)
	limits := container["resources"].(map[string]any)["limits"].(map[string]any)
	if limits["nvidia.com/gpu"] != 1 {
		t.Fatalf("GPU resource missing: %#v", limits)
	}

	_, err = RenderPodTemplate(PodSpec{
		Name: "ops", Namespace: "kiki-system", ModelAlias: "ops", ModelPath: "/models/ops/model.gguf",
		ModelSource: modelSource, ModelDigest: modelDigest, FetcherImage: pinnedImage, CachePVC: "cache", Port: 8000, ContextLength: 4096, LlamaImage: "registry/runtime:latest",
	}, Plan{Phase: "Ready", Engine: "llama.cpp", Backend: "cpu"})
	if err == nil || !strings.Contains(err.Error(), "pinned") {
		t.Fatalf("mutable image accepted: %v", err)
	}
}

func TestRenderRejectsUnsafeModelPath(t *testing.T) {
	_, err := RenderPodTemplate(PodSpec{
		Name: "ops", Namespace: "kiki-system", ModelAlias: "ops", ModelPath: "/models/../etc/passwd",
		ModelSource: modelSource, ModelDigest: modelDigest, FetcherImage: pinnedImage, CachePVC: "cache", Port: 8000, ContextLength: 4096, LlamaImage: pinnedImage,
	}, Plan{Phase: "Ready", Engine: "llama.cpp", Backend: "cpu"})
	if err == nil {
		t.Fatal("unsafe model path accepted")
	}
}
