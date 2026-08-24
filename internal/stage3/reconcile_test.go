package stage3

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

type recordingRunner struct {
	name      string
	arguments []string
	calls     []runnerCall
	err       error
	failAt    int
}

type runnerCall struct {
	name      string
	arguments []string
}

func (runner *recordingRunner) Run(_ context.Context, name string, arguments []string) error {
	runner.name = name
	runner.arguments = append([]string(nil), arguments...)
	runner.calls = append(runner.calls, runnerCall{name: name, arguments: append([]string(nil), arguments...)})
	if runner.failAt > 0 {
		if len(runner.calls) == runner.failAt {
			return runner.err
		}
		return nil
	}
	return runner.err
}

func TestReconcileComputeDryRunUsesTokenReference(t *testing.T) {
	root := t.TempDir()
	tokenPath := filepath.Join(root, "run/secrets/kubeadm-token")
	if err := os.MkdirAll(filepath.Dir(tokenPath), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(tokenPath, []byte("abcdef.0123456789abcdef\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	config := computeConfig()
	runner := &recordingRunner{}
	result, err := Reconcile(context.Background(), config, ReconcileOptions{
		Root:          root,
		PlanPath:      filepath.Join(root, "var/lib/kiki/rendered/stage3-plan.yaml"),
		KikiKubeadm:   "/usr/bin/kiki-kubeadm",
		DryRun:        true,
		SkipPreflight: true,
		Runner:        runner,
	})
	if err != nil {
		t.Fatal(err)
	}
	joined := strings.Join(runner.arguments, " ")
	for _, expected := range []string{"join", "--role compute", "--action join", "--endpoint 10.0.0.10:6443", "--token-file /run/secrets/kubeadm-token", "--dry-run"} {
		if !strings.Contains(joined, expected) {
			t.Fatalf("command %q does not contain %q", joined, expected)
		}
	}
	if strings.Contains(joined, "abcdef.0123456789abcdef") {
		t.Fatalf("join token leaked into command arguments: %q", joined)
	}
	if result.Role != "compute" || result.Action != "join" || runner.name != "/usr/bin/kiki-kubeadm" {
		t.Fatalf("unexpected result: %+v runner=%+v", result, runner)
	}
}

func TestReconcileRejectsJoinWithoutDiscoveryInputs(t *testing.T) {
	config := computeConfig()
	config.Kubernetes.Cluster.ControlPlaneEndpoint = ""
	_, err := Reconcile(context.Background(), config, ReconcileOptions{Root: t.TempDir(), PlanPath: "/tmp/plan", DryRun: true, SkipPreflight: true, Runner: &recordingRunner{}})
	if err == nil || !strings.Contains(err.Error(), "control_plane_endpoint") {
		t.Fatalf("error = %v", err)
	}
}

func TestReconcileRejectsUnapprovedCNI(t *testing.T) {
	config := computeConfig()
	config.Kubernetes.CNI.Enabled = true
	config.Kubernetes.CNI.Provider = "unknown"
	config.Kubernetes.CNI.ManifestURL = "https://example.invalid/cni.yaml"
	_, err := Reconcile(context.Background(), config, ReconcileOptions{Root: t.TempDir(), PlanPath: "/tmp/plan", DryRun: true, SkipPreflight: true, Runner: &recordingRunner{}})
	if err == nil || !strings.Contains(err.Error(), "not allowed") {
		t.Fatalf("error = %v", err)
	}
}

func TestReconcileServerCoreIsNoop(t *testing.T) {
	var config Config
	config.Kubernetes.Role = "server-core"
	runner := &recordingRunner{}
	result, err := Reconcile(context.Background(), config, ReconcileOptions{PlanPath: "/tmp/plan", Runner: runner})
	if err != nil {
		t.Fatal(err)
	}
	if result.Action != "none" || runner.name != "" {
		t.Fatalf("unexpected no-op result: %+v runner=%+v", result, runner)
	}
}

func TestReconcileAppliesOnlyExplicitAllowedCNI(t *testing.T) {
	root := t.TempDir()
	tokenPath := filepath.Join(root, "run/secrets/kubeadm-token")
	if err := os.MkdirAll(filepath.Dir(tokenPath), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(tokenPath, []byte("abcdef.0123456789abcdef\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	config := computeConfig()
	config.Kubernetes.CNI.Enabled = true
	config.Kubernetes.CNI.Provider = "flannel"
	config.Kubernetes.CNI.ManifestPath = "/srv/kiki/cni/flannel.yaml"
	runner := &recordingRunner{}
	result, err := Reconcile(context.Background(), config, ReconcileOptions{Root: root, PlanPath: "/tmp/plan", KikiKubeadm: "/usr/bin/kiki-kubeadm", Kubectl: "/usr/bin/kubectl", SkipPreflight: true, Runner: runner})
	if err != nil {
		t.Fatal(err)
	}
	if len(runner.calls) != 2 || runner.calls[1].name != "/usr/bin/kubectl" {
		t.Fatalf("runner calls = %#v", runner.calls)
	}
	joined := strings.Join(runner.calls[1].arguments, " ")
	if !strings.Contains(joined, "apply -f "+filepath.Join(root, "srv/kiki/cni/flannel.yaml")) {
		t.Fatalf("CNI command = %q", joined)
	}
	if !result.CNIReady {
		t.Fatal("CNI result was not marked ready")
	}
}

func TestReconcileSkipsMatchingSuccessfulKubeadmState(t *testing.T) {
	root := t.TempDir()
	writeJoinToken(t, root)
	statePath := filepath.Join(root, "var/lib/kiki/kubernetes/state.json")
	if err := os.MkdirAll(filepath.Dir(statePath), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(statePath, []byte(`{"status":"succeeded","role":"compute","action":"join"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	runner := &recordingRunner{}
	result, err := Reconcile(context.Background(), computeConfig(), ReconcileOptions{Root: root, PlanPath: "/tmp/plan", SkipPreflight: true, Runner: runner})
	if err != nil {
		t.Fatal(err)
	}
	if !result.KubeadmSkipped || len(runner.calls) != 0 {
		t.Fatalf("result=%+v calls=%#v", result, runner.calls)
	}
}

func TestReconcileRejectsAutomaticCertificateUploadByDefault(t *testing.T) {
	root := t.TempDir()
	writeJoinToken(t, root)
	config := computeConfig()
	config.Kubernetes.Role = "control-plane"
	config.Kubernetes.Kubeadm.JoinControlPlaneTemplate = "/etc/kubernetes/kiki/kubeadm-join-control-plane.yaml"
	config.Kubernetes.Join.ControlPlaneCertificatePolicy = "upload"
	_, err := Reconcile(context.Background(), config, ReconcileOptions{Root: root, PlanPath: "/tmp/plan", SkipPreflight: true, Runner: &recordingRunner{}})
	if err == nil || !strings.Contains(err.Error(), "allow_control_plane_cert_upload") {
		t.Fatalf("error = %v", err)
	}
}

func TestReconcileRejectsUnsafeCNIURL(t *testing.T) {
	config := computeConfig()
	config.Kubernetes.CNI.Enabled = true
	config.Kubernetes.CNI.Provider = "flannel"
	config.Kubernetes.CNI.ManifestURL = "file:///etc/passwd"
	_, err := Reconcile(context.Background(), config, ReconcileOptions{Root: t.TempDir(), PlanPath: "/tmp/plan", SkipPreflight: true, Runner: &recordingRunner{}})
	if err == nil || !strings.Contains(err.Error(), "http or https") {
		t.Fatalf("error = %v", err)
	}
}

func TestReconcileChecksKubeletAfterRealRootExecution(t *testing.T) {
	root := t.TempDir()
	var config Config
	config.Runtime.ContainerRuntime = "containerd"
	config.Runtime.CRISockets = map[string]string{"containerd": "unix:///run/containerd/containerd.sock"}
	config.Kubernetes.Role = "bootstrap"
	config.Kubernetes.Kubeadm.Action = "init"
	config.Kubernetes.Kubeadm.InitTemplate = "/etc/kubernetes/kiki/kubeadm-init.yaml"
	runner := &recordingRunner{}
	result, err := Reconcile(context.Background(), config, ReconcileOptions{
		Root:          root,
		PlanPath:      filepath.Join(root, "var/lib/kiki/rendered/stage3-plan.yaml"),
		KikiKubeadm:   "/usr/bin/kiki-kubeadm",
		Systemctl:     "/usr/bin/systemctl",
		SkipPreflight: true,
		CheckKubelet:  true,
		Runner:        runner,
	})
	if err != nil {
		t.Fatal(err)
	}
	if !result.KubeletReady || len(runner.calls) != 2 {
		t.Fatalf("result=%+v calls=%#v", result, runner.calls)
	}
	if runner.calls[1].name != "/usr/bin/systemctl" || strings.Join(runner.calls[1].arguments, " ") != "is-active --quiet kubelet.service" {
		t.Fatalf("health check call=%#v", runner.calls[1])
	}
}

func TestReconcileFailsWhenKubeletIsNotActive(t *testing.T) {
	root := t.TempDir()
	var config Config
	config.Runtime.ContainerRuntime = "containerd"
	config.Runtime.CRISockets = map[string]string{"containerd": "unix:///run/containerd/containerd.sock"}
	config.Kubernetes.Role = "bootstrap"
	config.Kubernetes.Kubeadm.Action = "init"
	config.Kubernetes.Kubeadm.InitTemplate = "/etc/kubernetes/kiki/kubeadm-init.yaml"
	runner := &recordingRunner{err: errors.New("inactive"), failAt: 2}
	_, err := Reconcile(context.Background(), config, ReconcileOptions{
		Root:          root,
		PlanPath:      filepath.Join(root, "var/lib/kiki/rendered/stage3-plan.yaml"),
		SkipPreflight: true,
		CheckKubelet:  true,
		Runner:        runner,
	})
	if err == nil || !strings.Contains(err.Error(), "kubelet health check failed") {
		t.Fatalf("error=%v calls=%#v", err, runner.calls)
	}
}

func writeJoinToken(t *testing.T, root string) {
	t.Helper()
	tokenPath := filepath.Join(root, "run/secrets/kubeadm-token")
	if err := os.MkdirAll(filepath.Dir(tokenPath), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(tokenPath, []byte("abcdef.0123456789abcdef\n"), 0o600); err != nil {
		t.Fatal(err)
	}
}

func computeConfig() Config {
	var config Config
	config.Runtime.ContainerRuntime = "containerd"
	config.Runtime.CRISockets = map[string]string{"containerd": "unix:///run/containerd/containerd.sock"}
	config.Kubernetes.Role = "compute"
	config.Kubernetes.Kubeadm.Action = "join"
	config.Kubernetes.Kubeadm.ConfigOutput = "/etc/kubernetes/kiki/kubeadm.local.yaml"
	config.Kubernetes.Kubeadm.JoinComputeTemplate = "/etc/kubernetes/kiki/kubeadm-join-compute.yaml"
	config.Kubernetes.Cluster.ControlPlaneEndpoint = "10.0.0.10:6443"
	config.Kubernetes.Join.TokenRef = "/run/secrets/kubeadm-token"
	config.Kubernetes.Join.CACertHash = "sha256:" + strings.Repeat("a", 64)
	config.Kubernetes.CNI.AllowedProviders = []string{"flannel", "calico", "cilium"}
	config.Safety.RequireJoinToken = true
	config.Safety.RequireCACertHash = true
	return config
}
