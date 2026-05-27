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
}

func TestKubeNodeProfileDisablesSwapAndEnablesCRIO(t *testing.T) {
	plan := NewDefaultPlan("kiki-kube-node")

	if plan.Target.Filesystems.Swap.Enabled {
		t.Fatal("kiki-kube-node should disable swap by default")
	}
	if plan.Runtime.ContainerRuntime != "cri-o" {
		t.Fatalf("runtime = %q, want cri-o", plan.Runtime.ContainerRuntime)
	}
	if plan.Target.Filesystems.Root.Path != "/dev/sda2" {
		t.Fatalf("root path = %q, want /dev/sda2 when swap is off", plan.Target.Filesystems.Root.Path)
	}
	for _, name := range []string{"cri-o", "kubelet", "kubeadm", "kubectl", "nftables", "iptables"} {
		if !contains(plan.Packages.Selected, name) {
			t.Fatalf("kiki-kube-node missing package %q", name)
		}
	}
	for _, unit := range []string{"crio.service", "kubelet.service"} {
		if !contains(plan.Services.Enable, unit) {
			t.Fatalf("kiki-kube-node missing service %q", unit)
		}
	}
}

func TestKubernetesBootstrapAndControllerProfiles(t *testing.T) {
	for _, profile := range []string{"kiki-kube-bootstrap", "kiki-kube-controller"} {
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
		"Install Plan: /run/kiki/install-plan.yaml",
		"[!] Disk",
		"[OK] Network",
		"[OK] Account",
		"[ ] Profile",
		"[ ] Runtime",
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
		"profile kiki-kube-node",
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
		`profile: "kiki-kube-node"`,
		`container_runtime: "cri-o"`,
		`firewalld: true`,
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

func TestStageTwoCommandsSelectRemoteRepoAndContainerd(t *testing.T) {
	tui := TUI{Plan: NewDefaultPlan("minimal-systemd")}

	if _, err := tui.ApplyCommand("source remote http://repo.example/kiki"); err != nil {
		t.Fatalf("source remote error = %v", err)
	}
	if _, err := tui.ApplyCommand("verify-key /etc/ki2/trust/stage2-repo.hmac"); err != nil {
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
	if tui.Plan.Source.VerifyKey != "/etc/ki2/trust/stage2-repo.hmac" {
		t.Fatalf("verify key = %q", tui.Plan.Source.VerifyKey)
	}
	if tui.Plan.Runtime.ContainerRuntime != "containerd" {
		t.Fatalf("runtime = %q, want containerd", tui.Plan.Runtime.ContainerRuntime)
	}
	if !contains(tui.Plan.Packages.Selected, "containerd") || !contains(tui.Plan.Packages.Selected, "runc") {
		t.Fatalf("containerd runtime packages missing: %#v", tui.Plan.Packages.Selected)
	}
	if !contains(tui.Plan.Services.Enable, "containerd.service") {
		t.Fatalf("containerd service missing: %#v", tui.Plan.Services.Enable)
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
