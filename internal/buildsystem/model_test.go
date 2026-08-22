package buildsystem

import (
	"strings"
	"testing"
)

func TestRenderRestrictedModelBuildJob(t *testing.T) {
	config := ModelConfig{GitImage: image, BuilderImage: image, SupplyChainImage: image, AllowedGitHosts: []string{"git.example.com"}, AllowedRegistries: []string{"registry.example.com"}, EgressProxyURL: "http://proxy.kiki-system.svc:8080", EgressProxyCIDR: "10.20.0.10/32", RegistryAuthSecret: "registry-auth", SigningSecret: "artifact-signing", BuildTokenSecret: "infraops-auth", InfraOpsURL: "http://kiki-infraops:8090"}
	build := ModelBuild{ID: "model-0001", Source: Source{URL: "https://git.example.com/models/ops.git", Revision: revision}, ContextPath: "model", InputPath: "weights/model.gguf", InputFormat: "gguf", OutputFormat: "gguf", Quantization: "q4_k_m", Destination: "registry.example.com/models/ops", ArtifactPVC: "build-artifacts", LicenseID: "Apache-2.0"}
	job, err := RenderModelJob(build, config)
	if err != nil {
		t.Fatal(err)
	}
	spec := job["spec"].(map[string]any)["template"].(map[string]any)["spec"].(map[string]any)
	if spec["automountServiceAccountToken"] != false || spec["nodeSelector"].(map[string]any)["kiki.io/model-builder"] != "true" {
		t.Fatalf("unsafe model job: %#v", spec)
	}
	containers := spec["initContainers"].([]any)
	if len(containers) != 3 || !strings.Contains(valuesAsString(containers[2].(map[string]any)["args"].([]any)), "--quantization q4_k_m") {
		t.Fatalf("model pipeline missing: %#v", containers)
	}
	for _, volume := range spec["volumes"].([]any) {
		if _, ok := volume.(map[string]any)["hostPath"]; ok {
			t.Fatal("model job contains hostPath")
		}
	}
}

func TestRenderModelBuildRejectsUnsafeConversion(t *testing.T) {
	config := ModelConfig{GitImage: image, BuilderImage: image, SupplyChainImage: image, AllowedGitHosts: []string{"git.example.com"}, AllowedRegistries: []string{"registry.example.com"}, EgressProxyURL: "http://proxy:8080", EgressProxyCIDR: "10.20.0.10/32", RegistryAuthSecret: "registry-auth", SigningSecret: "signing", BuildTokenSecret: "infraops-auth", InfraOpsURL: "http://kiki-infraops:8090"}
	build := ModelBuild{ID: "model-0001", Source: Source{URL: "https://git.example.com/model.git", Revision: revision}, InputPath: "../secret", InputFormat: "gguf", OutputFormat: "gguf", Quantization: "none", Destination: "registry.example.com/models/ops", ArtifactPVC: "artifacts", LicenseID: "MIT"}
	if _, err := RenderModelJob(build, config); err == nil {
		t.Fatal("escaping model input accepted")
	}
}
