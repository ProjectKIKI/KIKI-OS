package buildsystem

import (
	"strings"
	"testing"
)

func TestRenderRestrictedOCIJob(t *testing.T) {
	job, err := RenderOCIJob(testOCIBuild(), testOCIConfig())
	if err != nil {
		t.Fatal(err)
	}
	spec := job["spec"].(map[string]any)["template"].(map[string]any)["spec"].(map[string]any)
	if spec["automountServiceAccountToken"] != false || spec["nodeSelector"].(map[string]any)["kiki.io/build-worker"] != "true" {
		t.Fatalf("unsafe pod: %#v", spec)
	}
	if len(spec["initContainers"].([]any)) != 3 {
		t.Fatalf("pipeline steps missing: %#v", spec["initContainers"])
	}
	buildctl := spec["initContainers"].([]any)[2].(map[string]any)
	args := valuesAsString(buildctl["args"].([]any))
	if !strings.Contains(args, "push=true") || !strings.Contains(args, "--metadata-file") {
		t.Fatalf("BuildKit output is not traceable: %s", args)
	}
	for _, volume := range spec["volumes"].([]any) {
		if _, exists := volume.(map[string]any)["hostPath"]; exists {
			t.Fatal("hostPath rendered")
		}
	}
	policy, err := RenderOCINetworkPolicy("build-oci-1", testOCIConfig())
	if err != nil {
		t.Fatal(err)
	}
	if got := len(policy["spec"].(map[string]any)["egress"].([]any)); got != 4 {
		t.Fatalf("expected DNS, proxy, InfraOps, and BuildKit egress, got %d", got)
	}
}

func TestRenderOCIJobRejectsUnsafeInputs(t *testing.T) {
	build := testOCIBuild()
	config := testOCIConfig()
	build.Source.Revision = "main"
	if _, err := RenderOCIJob(build, config); err == nil {
		t.Fatal("mutable revision accepted")
	}
	build = testOCIBuild()
	build.Destination = "evil.example/repo"
	if _, err := RenderOCIJob(build, config); err == nil || !strings.Contains(err.Error(), "not allowed") {
		t.Fatalf("untrusted registry accepted: %v", err)
	}
	build = testOCIBuild()
	config.BuildctlImage = "buildctl:latest"
	if _, err := RenderOCIJob(build, config); err == nil || !strings.Contains(err.Error(), "digest pinned") {
		t.Fatalf("mutable builder accepted: %v", err)
	}
	build = testOCIBuild()
	build.DefinitionPath = "../Containerfile"
	if _, err := RenderOCIJob(build, testOCIConfig()); err == nil {
		t.Fatal("escaping definition path accepted")
	}
}

func testOCIBuild() OCIBuild {
	return OCIBuild{ID: "build-oci-1", Source: Source{URL: "https://git.example.com/kiki/app.git", Revision: revision}, ContextPath: "app", DefinitionPath: "Containerfile", Destination: "registry.example.com/kiki/app", ArtifactPVC: "build-artifacts", Platforms: []string{"linux/amd64", "linux/arm64"}, PackageType: "cpm"}
}

func testOCIConfig() OCIConfig {
	return OCIConfig{GitImage: image, BuildctlImage: image, SupplyChainImage: image, AllowedGitHosts: []string{"git.example.com"}, AllowedRegistries: []string{"registry.example.com"}, BuildKitAddress: "tcp://buildkitd.kiki-build.svc:1234", BuildKitCIDR: "10.30.0.20/32", BuildKitPort: 1234, EgressProxyURL: "http://proxy.kiki-system.svc:8080", EgressProxyCIDR: "10.20.0.10/32", RegistryAuthSecret: "registry-auth", SigningSecret: "artifact-signing", BuildTokenSecret: "infraops-auth", InfraOpsURL: "http://kiki-infraops:8090"}
}

func valuesAsString(values []any) string {
	parts := make([]string, len(values))
	for index, value := range values {
		parts[index] = value.(string)
	}
	return strings.Join(parts, " ")
}
