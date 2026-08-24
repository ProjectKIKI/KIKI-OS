package stage3

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestLoadFilesMergesLayersAndUnwrapsInstallPlan(t *testing.T) {
	directory := t.TempDir()
	defaults := writeTestFile(t, directory, "defaults.yaml", `
runtime:
  container_runtime: cri-o
kubernetes:
  role: none
  cni:
    allowed_providers: [flannel, calico]
services: [sshd]
`)
	profile := writeTestFile(t, directory, "profile.yaml", `
kubernetes:
  role: compute
services:
  merge_strategy: append
  items: [kubelet]
`)
	plan := writeTestFile(t, directory, "plan.yaml", `
install_plan:
  runtime:
    container_runtime: containerd
  kubernetes:
    kubeadm:
      action: join
`)
	override := writeTestFile(t, directory, "override.yaml", `
kubernetes:
  cluster:
    control_plane_endpoint: 10.0.0.10:6443
services: [chronyd]
`)

	document, err := LoadFiles([]string{defaults, profile, plan, override})
	if err != nil {
		t.Fatal(err)
	}
	config, err := Decode(document)
	if err != nil {
		t.Fatal(err)
	}
	if config.Runtime.ContainerRuntime != "containerd" || config.Kubernetes.Role != "compute" || config.Kubernetes.Kubeadm.Action != "join" {
		t.Fatalf("unexpected merged config: %+v", config)
	}
	services, ok := document["services"].([]any)
	if !ok || len(services) != 1 || services[0] != "chronyd" {
		t.Fatalf("lists must be replaced by later ordinary layers: %#v", document["services"])
	}
}

func TestMergeAppendDirective(t *testing.T) {
	base := Document{"items": []any{"one"}}
	overlay := Document{"items": map[string]any{"merge_strategy": "append", "items": []any{"two"}}}
	merged := Merge(base, overlay)
	items := merged["items"].([]any)
	if len(items) != 2 || items[0] != "one" || items[1] != "two" {
		t.Fatalf("append merge = %#v", items)
	}
}

func TestWriteRenderedRedactsPlaintextSecrets(t *testing.T) {
	path := filepath.Join(t.TempDir(), "rendered", "stage3-plan.yaml")
	document := Document{
		"kubernetes": map[string]any{
			"join": map[string]any{
				"token":        "abcdef.0123456789abcdef",
				"token_ref":    "/run/secrets/kubeadm-token",
				"ca_cert_hash": "sha256:" + strings.Repeat("a", 64),
			},
		},
	}
	if err := WriteRendered(path, document); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	text := string(data)
	if strings.Contains(text, "abcdef.0123456789abcdef") || !strings.Contains(text, "<redacted>") {
		t.Fatalf("secret was not redacted:\n%s", text)
	}
	if !strings.Contains(text, "/run/secrets/kubeadm-token") || !strings.Contains(text, "sha256:") {
		t.Fatalf("safe references were unexpectedly redacted:\n%s", text)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("rendered mode = %o, want 600", info.Mode().Perm())
	}
}

func writeTestFile(t *testing.T, directory, name, contents string) string {
	t.Helper()
	path := filepath.Join(directory, name)
	if err := os.WriteFile(path, []byte(strings.TrimSpace(contents)+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}
