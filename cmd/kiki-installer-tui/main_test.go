package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestDefaultPlanUsesStageOneDefaults(t *testing.T) {
	plan := NewDefaultPlan("minimal-systemd")

	if plan.Users.Admin.Name != "kiki" {
		t.Fatalf("admin user = %q, want kiki", plan.Users.Admin.Name)
	}
	if !plan.Users.Root.Locked {
		t.Fatal("root account should be locked by default")
	}
	if plan.Network.Mode != "dhcp" || plan.Network.Manager != "systemd-networkd" {
		t.Fatalf("network = %s/%s, want dhcp/systemd-networkd", plan.Network.Mode, plan.Network.Manager)
	}
	if !plan.Target.Filesystems.Swap.Enabled {
		t.Fatal("minimal-systemd should keep system swap enabled")
	}
	if !contains(plan.Packages.Selected, "kiki-installer-tui") {
		t.Fatal("minimal-systemd should include kiki-installer-tui preview package")
	}
	if checkInit(plan).State != "OK" {
		t.Fatalf("default plan should be ready for systemd handoff init: %#v", checkInit(plan))
	}
}

func TestServerCoreProfileAddsGeneralServerPackages(t *testing.T) {
	plan := NewDefaultPlan("server-core")

	if plan.Packages.Profile != "server-core" {
		t.Fatalf("profile = %q, want server-core", plan.Packages.Profile)
	}
	if !plan.Target.Filesystems.Swap.Enabled {
		t.Fatal("server-core should keep normal system swap enabled")
	}
	if plan.Runtime.ContainerRuntime != "none" || plan.Kubernetes.Role != "none" {
		t.Fatalf("server-core should not enable container runtime or Kubernetes: runtime=%q role=%q", plan.Runtime.ContainerRuntime, plan.Kubernetes.Role)
	}
	for _, name := range []string{"nftables", "iptables", "conntrack-tools", "firewalld", "bridge-utils", "ethtool", "chrony", "kiki-netconfig"} {
		if !contains(plan.Packages.Selected, name) {
			t.Fatalf("server-core missing package %q", name)
		}
	}
	for _, name := range []string{"kubelet", "kubeadm", "kubectl", "cri-o", "containerd"} {
		if contains(plan.Packages.Selected, name) {
			t.Fatalf("server-core should not include Kubernetes/runtime package %q", name)
		}
	}
	for _, unit := range []string{"nftables.service", "firewalld.service", "chronyd.service"} {
		if !contains(plan.Services.Enable, unit) {
			t.Fatalf("server-core missing service %q", unit)
		}
	}
}

func TestKubeComputeProfileDisablesSwapAndEnablesCRIO(t *testing.T) {
	plan := NewDefaultPlan("kiki-kube-compute")

	if plan.Target.Filesystems.Swap.Enabled {
		t.Fatal("kiki-kube-compute should disable swap by default")
	}
	if plan.Runtime.ContainerRuntime != "cri-o" {
		t.Fatalf("runtime = %q, want cri-o", plan.Runtime.ContainerRuntime)
	}
	if plan.Firewall.Firewalld {
		t.Fatal("kiki-kube-compute should keep firewalld disabled by default")
	}
	if plan.Target.Filesystems.Root.Path != "/dev/sda2" {
		t.Fatalf("root path = %q, want /dev/sda2 when swap is off", plan.Target.Filesystems.Root.Path)
	}
	for _, name := range []string{"cri-o", "kubelet", "kubeadm", "kubectl", "nftables", "iptables"} {
		if !contains(plan.Packages.Selected, name) {
			t.Fatalf("kiki-kube-compute missing package %q", name)
		}
	}
	for _, unit := range []string{"crio.service", "kubelet.service"} {
		if !contains(plan.Services.Enable, unit) {
			t.Fatalf("kiki-kube-compute missing service %q", unit)
		}
	}
}

func TestKubernetesBootstrapAndControlProfiles(t *testing.T) {
	for _, profile := range []string{"kiki-kube-bootstrap", "kiki-kube-control"} {
		plan := NewDefaultPlan(profile)

		if plan.Packages.Profile != profile {
			t.Fatalf("profile = %q, want %q", plan.Packages.Profile, profile)
		}
		if plan.Target.Filesystems.Swap.Enabled {
			t.Fatalf("%s should disable swap by default", profile)
		}
		if plan.Runtime.ContainerRuntime != "cri-o" {
			t.Fatalf("%s runtime = %q, want cri-o", profile, plan.Runtime.ContainerRuntime)
		}
		if !plan.Firewall.Firewalld {
			t.Fatalf("%s should include firewalld policy", profile)
		}
		for _, name := range []string{"cri-o", "kubelet", "kubeadm", "kubectl", "firewalld", "bridge-utils"} {
			if !contains(plan.Packages.Selected, name) {
				t.Fatalf("%s missing package %q", profile, name)
			}
		}
	}
}

func TestKubernetesContainerdProfiles(t *testing.T) {
	for _, profile := range []string{"kiki-kube-bootstrap-containerd", "kiki-kube-control-containerd", "kiki-kube-compute-containerd"} {
		plan := NewDefaultPlan(profile)

		if plan.Packages.Profile != profile {
			t.Fatalf("profile = %q, want %q", plan.Packages.Profile, profile)
		}
		if plan.Runtime.ContainerRuntime != "containerd" {
			t.Fatalf("%s runtime = %q, want containerd", profile, plan.Runtime.ContainerRuntime)
		}
		if plan.Target.Filesystems.Swap.Enabled {
			t.Fatalf("%s should disable swap by default", profile)
		}
		for _, name := range []string{"containerd", "runc", "kube-node-config-containerd", "kubelet", "kubeadm", "kubectl"} {
			if !contains(plan.Packages.Selected, name) {
				t.Fatalf("%s missing package %q", profile, name)
			}
		}
		for _, name := range []string{"cri-o", "conmon", "crun", "kube-node-config"} {
			if contains(plan.Packages.Selected, name) {
				t.Fatalf("%s should not include CRI-O package %q when containerd is selected", profile, name)
			}
		}
		if !contains(plan.Services.Enable, "containerd.service") || !contains(plan.Services.Enable, "kubelet.service") {
			t.Fatalf("%s missing containerd/kubelet services: %#v", profile, plan.Services.Enable)
		}
		if contains(plan.Services.Enable, "crio.service") {
			t.Fatalf("%s should not enable crio.service with containerd", profile)
		}
	}
}

func TestLegacyKubernetesProfileAliases(t *testing.T) {
	tests := map[string]string{
		"kiki-kube-controller": "kiki-kube-control",
		"kiki-kube-node":       "kiki-kube-compute",
	}
	for input, want := range tests {
		plan := NewDefaultPlan(input)
		if plan.Packages.Profile != want {
			t.Fatalf("profile alias %q = %q, want %q", input, plan.Packages.Profile, want)
		}
	}
}

func TestKubernetesProfileRejectsRuntimeNone(t *testing.T) {
	tui := TUI{Plan: NewDefaultPlan("kiki-kube-bootstrap")}

	_, err := tui.ApplyCommand("runtime none")
	if err == nil {
		t.Fatal("runtime none on Kubernetes profile error = nil")
	}
	if !strings.Contains(err.Error(), "Kubernetes profiles require") {
		t.Fatalf("error = %q, want Kubernetes runtime requirement", err)
	}
}

func TestNetworkStaticCommandWritesPlanFields(t *testing.T) {
	tui := TUI{Plan: NewDefaultPlan("minimal-systemd")}

	if _, err := tui.ApplyCommand("network static 192.168.122.50/24 192.168.122.1 1.1.1.1,8.8.8.8 eth0"); err != nil {
		t.Fatalf("network static error = %v", err)
	}

	if tui.Plan.Network.Mode != "static" || tui.Plan.Network.DHCP4 || tui.Plan.Network.IPv6AcceptRA {
		t.Fatalf("network flags = %#v, want static without DHCP/RA", tui.Plan.Network)
	}
	if tui.Plan.Network.Address != "192.168.122.50/24" || tui.Plan.Network.Gateway != "192.168.122.1" {
		t.Fatalf("network address/gateway = %#v", tui.Plan.Network)
	}
	if tui.Plan.Network.DNS != "1.1.1.1 8.8.8.8" || tui.Plan.Network.InterfaceMatch != "eth0" {
		t.Fatalf("network dns/match = %#v", tui.Plan.Network)
	}

	var out bytes.Buffer
	if err := WritePlanYAML(&out, tui.Plan); err != nil {
		t.Fatalf("WritePlanYAML error = %v", err)
	}
	text := out.String()
	for _, want := range []string{
		`mode: "static"`,
		`address: "192.168.122.50/24"`,
		`gateway: "192.168.122.1"`,
		`dns: "1.1.1.1 8.8.8.8"`,
	} {
		if !strings.Contains(text, want) {
			t.Fatalf("plan missing %q:\n%s", want, text)
		}
	}
}

func TestRenderDashboardShowsPlanStatus(t *testing.T) {
	var out bytes.Buffer
	tui := TUI{
		Plan:     NewDefaultPlan("minimal-systemd"),
		PlanPath: "/run/kiki/install-plan.yaml",
		Out:      &out,
	}

	tui.Render()
	text := out.String()
	for _, want := range []string{
		"KIKI OS Installer",
		"Stage 3 plan authoring",
		"Install Plan: /run/kiki/install-plan.yaml",
		"[!] Disk",
		"[OK] Network",
		"[OK] Account",
		"[ ] Profile",
		"[ ] Runtime",
		"[OK] Init",
		"[ ] Review",
		"7) Start install",
		"s) Shell",
		"q) Power off",
	} {
		if !strings.Contains(text, want) {
			t.Fatalf("dashboard missing %q:\n%s", want, text)
		}
	}
}

func TestCommandLoopWritesPlan(t *testing.T) {
	dir := t.TempDir()
	planPath := filepath.Join(dir, "install-plan.yaml")
	input := strings.Join([]string{
		"profile kiki-kube-compute",
		"firewalld on",
		"write " + planPath,
		"quit",
		"",
	}, "\n")
	var out bytes.Buffer
	tui := TUI{
		Plan:     NewDefaultPlan("minimal-systemd"),
		PlanPath: planPath,
		In:       strings.NewReader(input),
		Out:      &out,
	}

	if err := tui.Run(); err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	data, err := os.ReadFile(planPath)
	if err != nil {
		t.Fatalf("ReadFile(plan) error = %v", err)
	}
	text := string(data)
	for _, want := range []string{
		`profile: "kiki-kube-compute"`,
		`container_runtime: "cri-o"`,
		`role: "compute"`,
		`config_api: "kubeadm.k8s.io/v1beta4"`,
		`config_template: "/etc/kubernetes/kiki/kubeadm-join-compute.yaml"`,
		`command: "kubeadm join --config /etc/kubernetes/kiki/kubeadm.local.yaml"`,
		`cri_socket: "unix:///var/run/crio/crio.sock"`,
		`firewalld: true`,
		`runtime_plan: "` + planPath + `"`,
		`installed_plan: "/var/lib/ki2/install-plan.yaml"`,
		`password: "runtime-only"`,
		`password: "disabled"`,
	} {
		if !strings.Contains(text, want) {
			t.Fatalf("plan missing %q:\n%s", want, text)
		}
	}
	if strings.Contains(text, "kiki/kiki") {
		t.Fatalf("plan should not store plaintext password:\n%s", text)
	}
}

func TestStartInstallWritesReadyPlan(t *testing.T) {
	dir := t.TempDir()
	planPath := filepath.Join(dir, "install-plan.yaml")
	input := strings.Join([]string{
		"profile kiki-kube-compute-containerd",
		"start",
		"quit",
		"",
	}, "\n")
	var out bytes.Buffer
	tui := TUI{
		Plan:     NewDefaultPlan("minimal-systemd"),
		PlanPath: planPath,
		In:       strings.NewReader(input),
		Out:      &out,
	}

	if err := tui.Run(); err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	if !tui.PlanWritten {
		t.Fatal("start should mark the plan as written")
	}
	text := out.String()
	if !strings.Contains(text, "Stage-1 installer and Stage-3 executor can consume this install plan") {
		t.Fatalf("start output missing handoff message:\n%s", text)
	}
	data, err := os.ReadFile(planPath)
	if err != nil {
		t.Fatalf("ReadFile(plan) error = %v", err)
	}
	plan := string(data)
	for _, want := range []string{
		`profile: "kiki-kube-compute-containerd"`,
		`container_runtime: "containerd"`,
		`role: "compute"`,
		`cri_socket: "unix:///run/containerd/containerd.sock"`,
		`runtime_plan: "` + planPath + `"`,
		`installed_plan: "/var/lib/ki2/install-plan.yaml"`,
	} {
		if !strings.Contains(plan, want) {
			t.Fatalf("plan missing %q:\n%s", want, plan)
		}
	}
}

func TestStageTwoCommandsSelectRemoteRepoAndContainerd(t *testing.T) {
	tui := TUI{Plan: NewDefaultPlan("minimal-systemd")}

	if _, err := tui.ApplyCommand("source remote http://repo.example/kiki"); err != nil {
		t.Fatalf("source remote error = %v", err)
	}
	if _, err := tui.ApplyCommand("verify-key /etc/ki2/trust/stage2-v2-repo.hmac"); err != nil {
		t.Fatalf("verify-key error = %v", err)
	}
	if _, err := tui.ApplyCommand("runtime containerd"); err != nil {
		t.Fatalf("runtime containerd error = %v", err)
	}

	if tui.Plan.Source.Type != "remote-repository" || tui.Plan.Source.DisconnectedInstall {
		t.Fatalf("source = %#v, want remote connected", tui.Plan.Source)
	}
	if tui.Plan.Source.RepoIndex != "http://repo.example/kiki/repo/index.x86_64.json" {
		t.Fatalf("repo index = %q", tui.Plan.Source.RepoIndex)
	}
	if tui.Plan.Source.VerifyKey != "/etc/ki2/trust/stage2-v2-repo.hmac" {
		t.Fatalf("verify key = %q", tui.Plan.Source.VerifyKey)
	}
	if tui.Plan.Runtime.ContainerRuntime != "containerd" {
		t.Fatalf("runtime = %q, want containerd", tui.Plan.Runtime.ContainerRuntime)
	}
	if !contains(tui.Plan.Packages.Selected, "containerd") || !contains(tui.Plan.Packages.Selected, "runc") {
		t.Fatalf("containerd runtime packages missing: %#v", tui.Plan.Packages.Selected)
	}
	if contains(tui.Plan.Packages.Selected, "cri-o") {
		t.Fatalf("containerd runtime should not keep cri-o package: %#v", tui.Plan.Packages.Selected)
	}
	if !contains(tui.Plan.Services.Enable, "containerd.service") {
		t.Fatalf("containerd service missing: %#v", tui.Plan.Services.Enable)
	}
}

func TestStageTwoRuntimeContainerdOnKubernetesProfile(t *testing.T) {
	tui := TUI{Plan: NewDefaultPlan("kiki-kube-compute")}

	if _, err := tui.ApplyCommand("runtime containerd"); err != nil {
		t.Fatalf("runtime containerd error = %v", err)
	}

	if tui.Plan.Runtime.ContainerRuntime != "containerd" {
		t.Fatalf("runtime = %q, want containerd", tui.Plan.Runtime.ContainerRuntime)
	}
	if tui.Plan.Kubernetes.Kubeadm.CRISocket != "unix:///run/containerd/containerd.sock" {
		t.Fatalf("kubeadm CRI socket = %q", tui.Plan.Kubernetes.Kubeadm.CRISocket)
	}
	if tui.Plan.Kubernetes.Kubeadm.ConfigTemplate != "/etc/kubernetes/kiki/kubeadm-join-compute.yaml" {
		t.Fatalf("kubeadm template = %q", tui.Plan.Kubernetes.Kubeadm.ConfigTemplate)
	}
	for _, name := range []string{"containerd", "runc", "kube-node-config-containerd", "kubelet"} {
		if !contains(tui.Plan.Packages.Selected, name) {
			t.Fatalf("containerd Kubernetes plan missing package %q", name)
		}
	}
	for _, name := range []string{"cri-o", "conmon", "crun", "kube-node-config"} {
		if contains(tui.Plan.Packages.Selected, name) {
			t.Fatalf("containerd Kubernetes plan should not include %q", name)
		}
	}
	if !contains(tui.Plan.Services.Enable, "containerd.service") || contains(tui.Plan.Services.Enable, "crio.service") {
		t.Fatalf("containerd Kubernetes services wrong: %#v", tui.Plan.Services.Enable)
	}
}

func TestStageTwoSourceLocalResetsRemoteRepository(t *testing.T) {
	tui := TUI{Plan: NewDefaultPlan("minimal-systemd")}

	if _, err := tui.ApplyCommand("source remote http://repo.example/kiki"); err != nil {
		t.Fatalf("source remote error = %v", err)
	}
	if _, err := tui.ApplyCommand("source local /run/install-media"); err != nil {
		t.Fatalf("source local error = %v", err)
	}

	if tui.Plan.Source.Type != "local-installer-media" {
		t.Fatalf("source type = %q, want local-installer-media", tui.Plan.Source.Type)
	}
	if !tui.Plan.Source.DisconnectedInstall {
		t.Fatal("local installer media should be disconnected")
	}
	if tui.Plan.Source.RepoURL != "" {
		t.Fatalf("repo URL = %q, want empty for local media", tui.Plan.Source.RepoURL)
	}
	if tui.Plan.Source.RepoIndex != "/run/install-media/kiki/repo/index.x86_64.json" {
		t.Fatalf("repo index = %q", tui.Plan.Source.RepoIndex)
	}
}

func TestStageTwoSourceMirrorSupportsLocalPath(t *testing.T) {
	tui := TUI{Plan: NewDefaultPlan("minimal-systemd")}

	if _, err := tui.ApplyCommand("source mirror /srv/kiki-mirror"); err != nil {
		t.Fatalf("source mirror error = %v", err)
	}

	if tui.Plan.Source.Type != "mirror" || !tui.Plan.Source.DisconnectedInstall {
		t.Fatalf("source = %#v, want disconnected mirror", tui.Plan.Source)
	}
	if tui.Plan.Source.RepoURL != "file:///srv/kiki-mirror" {
		t.Fatalf("repo URL = %q, want file:///srv/kiki-mirror", tui.Plan.Source.RepoURL)
	}
	if tui.Plan.Source.RepoIndex != "file:///srv/kiki-mirror/repo/index.x86_64.json" {
		t.Fatalf("repo index = %q", tui.Plan.Source.RepoIndex)
	}
}

func TestRejectsPartitionAsTargetDisk(t *testing.T) {
	tui := TUI{Plan: NewDefaultPlan("minimal-systemd")}

	_, err := tui.ApplyCommand("disk /dev/sda1")
	if err == nil {
		t.Fatal("ApplyCommand(disk /dev/sda1) error = nil")
	}
	if !strings.Contains(err.Error(), "whole disk") {
		t.Fatalf("error = %q, want whole disk", err)
	}
}

func TestNVMePartitionNaming(t *testing.T) {
	tui := TUI{Plan: NewDefaultPlan("minimal-systemd")}

	if _, err := tui.ApplyCommand("disk /dev/nvme0n1"); err != nil {
		t.Fatalf("ApplyCommand(nvme disk) error = %v", err)
	}
	if got := tui.Plan.Target.Filesystems.Root.Path; got != "/dev/nvme0n1p3" {
		t.Fatalf("root path = %q, want /dev/nvme0n1p3", got)
	}
	if _, err := tui.ApplyCommand("disk /dev/nvme0n1p1"); err == nil {
		t.Fatal("ApplyCommand(nvme partition) error = nil")
	}
}
