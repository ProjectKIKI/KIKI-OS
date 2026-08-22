package buildsystem

import (
	"encoding/base64"
	"encoding/json"
	"strings"
	"testing"
)

const image = "registry.local/kiki/builder@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
const revision = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

func TestRenderRestrictedBOSJob(t *testing.T) {
	job, err := RenderBOSJob(BOSBuild{ID: "build-0001", Source: Source{URL: "https://git.example.com/kiki/pkg.git", Revision: revision}, ContextPath: "package", OutputName: "pkg.bos", ArtifactPVC: "build-artifacts", Platforms: []string{"linux/amd64"}}, testConfig())
	if err != nil {
		t.Fatal(err)
	}
	spec := job["spec"].(map[string]any)["template"].(map[string]any)["spec"].(map[string]any)
	if spec["automountServiceAccountToken"] != false || spec["nodeSelector"].(map[string]any)["kiki.io/build-worker"] != "true" {
		t.Fatalf("unsafe placement: %#v", spec)
	}
	container := spec["containers"].([]any)[0].(map[string]any)
	security := container["securityContext"].(map[string]any)
	if security["allowPrivilegeEscalation"] != false || security["readOnlyRootFilesystem"] != true {
		t.Fatalf("unsafe security context: %#v", security)
	}
	if len(spec["initContainers"].([]any)) != 3 || container["name"] != "supply-chain" {
		t.Fatal("BOS supply-chain stage is missing")
	}
	buildContainer := spec["initContainers"].([]any)[2].(map[string]any)
	if strings.Contains(valuesAsString(buildContainer["args"].([]any)), "build-token") || hasVolumeMount(buildContainer, "build-token") || hasVolumeMount(buildContainer, "signing") {
		t.Fatal("BOS builder received reporting token")
	}
	if !hasVolumeMount(container, "build-token") || !hasVolumeMount(container, "signing") {
		t.Fatal("trusted supply-chain container is missing reporting or signing credentials")
	}
	for _, volume := range spec["volumes"].([]any) {
		if _, exists := volume.(map[string]any)["hostPath"]; exists {
			t.Fatal("hostPath volume rendered")
		}
	}
}

func TestRenderBOSRecipeJobBuildsOneImmutablePackage(t *testing.T) {
	config := testConfig()
	config.AllowedSourceHosts = []string{"sources.example.com"}
	build := BOSBuild{ID: "hello-build", Source: Source{URL: "https://sources.example.com/hello-1.0.tar.gz", Revision: strings.Repeat("c", 64)}, OutputName: "hello-1.0-1.bos", ArtifactPVC: "artifacts", Platforms: []string{"linux/amd64"}, Recipe: &BOSRecipe{Name: "hello", Version: "1.0", Release: "1", Summary: "hello package", License: "MIT", Arch: "amd64", SourceURL: "https://sources.example.com/hello-1.0.tar.gz", SourceSHA256: strings.Repeat("c", 64), Build: []string{"make"}, Install: []string{"make DESTDIR=$DESTDIR install"}, Files: []string{"/usr/bin/hello"}}}
	job, err := RenderBOSJob(build, config)
	if err != nil {
		t.Fatal(err)
	}
	spec := job["spec"].(map[string]any)["template"].(map[string]any)["spec"].(map[string]any)
	init := spec["initContainers"].([]any)
	if len(init) != 1 || init[0].(map[string]any)["name"] != "bos-recipe-build" {
		t.Fatalf("recipe job contains unexpected stages: %#v", init)
	}
	args := init[0].(map[string]any)["args"].([]any)
	encoded := args[1].(string)
	data, err := base64.RawURLEncoding.DecodeString(encoded)
	if err != nil {
		t.Fatal(err)
	}
	var recipe BOSRecipe
	if err := json.Unmarshal(data, &recipe); err != nil {
		t.Fatal(err)
	}
	if recipe.Name != "hello" || recipe.SourceSHA256 != build.Source.Revision {
		t.Fatalf("recipe was not preserved: %#v", recipe)
	}
}

func TestRenderBOSRecipeRejectsSourceMismatch(t *testing.T) {
	config := testConfig()
	config.AllowedSourceHosts = []string{"sources.example.com"}
	build := BOSBuild{ID: "hello-build", Source: Source{URL: "https://sources.example.com/hello.tar.gz", Revision: strings.Repeat("c", 64)}, OutputName: "hello.bos", ArtifactPVC: "artifacts", Platforms: []string{"linux/amd64"}, Recipe: &BOSRecipe{Name: "hello", Version: "1", Release: "1", Summary: "hello", License: "MIT", Arch: "amd64", SourceURL: "https://sources.example.com/other.tar.gz", SourceSHA256: strings.Repeat("c", 64), Install: []string{"install"}, Files: []string{"/usr/bin/hello"}}}
	if _, err := RenderBOSJob(build, config); err == nil || !strings.Contains(err.Error(), "must match") {
		t.Fatalf("source mismatch accepted: %v", err)
	}
}

func hasVolumeMount(container map[string]any, name string) bool {
	for _, item := range container["volumeMounts"].([]any) {
		if item.(map[string]any)["name"] == name {
			return true
		}
	}
	return false
}

func TestRenderBOSJobRejectsMutableOrUntrustedInputs(t *testing.T) {
	base := BOSBuild{ID: "build-0001", Source: Source{URL: "https://evil.example/pkg.git", Revision: revision}, OutputName: "pkg.bos", ArtifactPVC: "artifacts", Platforms: []string{"linux/amd64"}}
	config := testConfig()
	_, err := RenderBOSJob(base, config)
	if err == nil || !strings.Contains(err.Error(), "not allowed") {
		t.Fatalf("untrusted host accepted: %v", err)
	}
	base.Source.URL = "https://git.example.com/pkg.git"
	base.Source.Revision = "main"
	_, err = RenderBOSJob(base, config)
	if err == nil || !strings.Contains(err.Error(), "commit SHA") {
		t.Fatalf("mutable revision accepted: %v", err)
	}
	base.Source.Revision = revision
	config.GitImage = "builder:latest"
	_, err = RenderBOSJob(base, config)
	if err == nil || !strings.Contains(err.Error(), "digest pinned") {
		t.Fatalf("mutable image accepted: %v", err)
	}
}

func TestRenderBuildNetworkPolicy(t *testing.T) {
	policy, err := RenderBuildNetworkPolicy("build-0001", "10.20.0.10/32")
	if err != nil {
		t.Fatal(err)
	}
	spec := policy["spec"].(map[string]any)
	if len(spec["ingress"].([]any)) != 0 || len(spec["egress"].([]any)) != 3 {
		t.Fatalf("unexpected network policy: %#v", policy)
	}
}

func testConfig() Config {
	return Config{GitImage: image, BOSBuilderImage: image, SupplyChainImage: image, AllowedGitHosts: []string{"git.example.com"}, EgressProxyURL: "http://egress-proxy.kiki-system.svc:8080", EgressProxyCIDR: "10.20.0.10/32", SigningSecret: "signing", BuildTokenSecret: "infraops-auth", InfraOpsURL: "http://kiki-infraops:8090"}
}
