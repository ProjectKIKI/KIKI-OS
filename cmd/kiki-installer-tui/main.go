package main

import (
	"bufio"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

const (
	appVersion       = "0.1.0"
	defaultPlanPath  = "/run/kiki/install-plan.yaml"
	defaultMediaRoot = "/run/install-media"
)

type InstallPlan struct {
	Schema      string
	APIVersion  string
	Kind        string
	GeneratedBy string
	Mode        string
	Source      SourcePlan
	Target      TargetPlan
	Identity    IdentityPlan
	Network     NetworkPlan
	Users       UsersPlan
	Packages    PackagesPlan
	Services    ServicesPlan
	Boot        BootPlan
	Runtime     RuntimePlan
	Kubernetes  KubernetesPlan
	Firewall    FirewallPlan
	Artifacts   ArtifactsPlan
}

type SourcePlan struct {
	Type                string
	MediaRoot           string
	RepoIndex           string
	RepoURL             string
	Channel             string
	VerifyKey           string
	DisconnectedInstall bool
}

type TargetPlan struct {
	Disk           string
	Partitioning   string
	PartitionTable string
	DiskMiB        int
	MemoryMiB      int
	Filesystems    FilesystemsPlan
}

type FilesystemsPlan struct {
	ESP  FilesystemPlan
	Swap SwapPlan
	Root FilesystemPlan
}

type FilesystemPlan struct {
	Path       string
	Type       string
	Mountpoint string
	SizeMiB    int
	Label      string
}

type SwapPlan struct {
	Enabled bool
	Path    string
	SizeMiB int
	Label   string
	Policy  string
}

type IdentityPlan struct {
	Hostname string
}

type NetworkPlan struct {
	Manager        string
	Resolver       string
	Mode           string
	InterfaceMatch string
	DHCP4          bool
	IPv6AcceptRA   bool
	Address        string
	Gateway        string
	DNS            string
	NTP            string
}

type UsersPlan struct {
	Admin AdminUserPlan
	Root  RootUserPlan
}

type AdminUserPlan struct {
	Name                string
	PrimaryGroup        string
	SupplementaryGroups []string
	Shell               string
	Password            string
}

type RootUserPlan struct {
	Locked   bool
	Password string
}

type PackagesPlan struct {
	Profile              string
	DependencyResolution bool
	Selected             []string
}

type ServicesPlan struct {
	Enable []string
}

type BootPlan struct {
	Loader    string
	Kernel    string
	Initramfs string
	Root      string
}

type RuntimePlan struct {
	ContainerRuntime string
	CgroupDriver     string
	SwapPolicy       string
}

type KubernetesPlan struct {
	Role    string
	Kubeadm KubeadmPlan
}

type KubeadmPlan struct {
	ConfigAPI      string
	Action         string
	ConfigTemplate string
	ConfigOutput   string
	Command        string
	ControlPlane   bool
	CRISocket      string
}

type FirewallPlan struct {
	Backend    string
	Firewalld  bool
	BridgeTool string
}

type ArtifactsPlan struct {
	RuntimePlan   string
	InstalledPlan string
}

type Check struct {
	Name    string
	State   string
	Summary string
}

type TUI struct {
	Plan        InstallPlan
	PlanPath    string
	In          io.Reader
	Out         io.Writer
	Reviewed    bool
	PlanWritten bool
}

func main() {
	planPath := flag.String("plan", defaultPlanPath, "install plan path")
	profile := flag.String("profile", "minimal-systemd", "initial profile")
	renderOnly := flag.Bool("render", false, "render dashboard and exit")
	writeOnly := flag.Bool("write", false, "write install plan and exit")
	flag.Usage = usage
	flag.Parse()

	plan := NewDefaultPlan(*profile)
	plan.Artifacts.RuntimePlan = *planPath
	tui := &TUI{
		Plan:     plan,
		PlanPath: *planPath,
		In:       os.Stdin,
		Out:      os.Stdout,
	}

	if *renderOnly {
		tui.Render()
		return
	}
	if *writeOnly {
		plan.Artifacts.RuntimePlan = *planPath
		if err := WritePlanFile(*planPath, plan); err != nil {
			fmt.Fprintln(os.Stderr, "error:", err)
			os.Exit(1)
		}
		fmt.Println("wrote", *planPath)
		return
	}

	if err := tui.Run(); err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}

func usage() {
	fmt.Println("kiki-installer-tui - KIKI install plan TUI preview (v" + appVersion + ")")
	fmt.Println()
	fmt.Println("Usage:")
	fmt.Println("  kiki-installer-tui [--plan /run/kiki/install-plan.yaml] [--profile minimal-systemd|kiki-kube-bootstrap|kiki-kube-control|kiki-kube-compute]")
	fmt.Println("  kiki-installer-tui --render")
	fmt.Println("  kiki-installer-tui --write --plan ./install-plan.yaml")
}

func NewDefaultPlan(profile string) InstallPlan {
	plan := InstallPlan{
		Schema:      "kiki-install-plan-v1",
		APIVersion:  "kiki.io/v1alpha1",
		Kind:        "InstallPlan",
		GeneratedBy: "kiki-installer-tui",
		Mode:        "guided",
		Source: SourcePlan{
			Type:                "local-installer-media",
			MediaRoot:           defaultMediaRoot,
			RepoIndex:           localMediaRepoIndex(defaultMediaRoot),
			RepoURL:             "",
			Channel:             "stage2-v2",
			VerifyKey:           "",
			DisconnectedInstall: true,
		},
		Target: TargetPlan{
			Disk:           "/dev/sda",
			Partitioning:   "auto-whole-disk",
			PartitionTable: "mbr",
			DiskMiB:        0,
			MemoryMiB:      0,
			Filesystems: FilesystemsPlan{
				ESP: FilesystemPlan{
					Path:       "/dev/sda1",
					Type:       "vfat",
					Mountpoint: "/boot/efi",
					SizeMiB:    768,
					Label:      "KIKI_EFI",
				},
				Swap: SwapPlan{
					Enabled: true,
					Path:    "/dev/sda2",
					SizeMiB: 8192,
					Label:   "KIKI_SWAP",
					Policy:  "system",
				},
				Root: FilesystemPlan{
					Path:       "/dev/sda3",
					Type:       "ext4",
					Mountpoint: "/",
					SizeMiB:    0,
					Label:      "KIKI_ROOT",
				},
			},
		},
		Identity: IdentityPlan{
			Hostname: "localhost.localdomain",
		},
		Network: NetworkPlan{
			Manager:        "systemd-networkd",
			Resolver:       "systemd-resolved",
			Mode:           "dhcp",
			InterfaceMatch: "en* eth*",
			DHCP4:          true,
			IPv6AcceptRA:   true,
		},
		Users: UsersPlan{
			Admin: AdminUserPlan{
				Name:                "kiki",
				PrimaryGroup:        "kiki",
				SupplementaryGroups: []string{"sudo"},
				Shell:               "/bin/sh",
				Password:            "runtime-only",
			},
			Root: RootUserPlan{
				Locked:   true,
				Password: "disabled",
			},
		},
		Packages: PackagesPlan{
			Profile:              "minimal-systemd",
			DependencyResolution: true,
			Selected:             append([]string{}, minimalSystemdPackages...),
		},
		Services: ServicesPlan{
			Enable: append([]string{}, minimalSystemdServices...),
		},
		Boot: BootPlan{
			Loader:    "uefi-fallback-bootx64",
			Kernel:    "/boot/vmlinuz-kiki",
			Initramfs: "/boot/initramfs-kiki.img",
			Root:      "/dev/sda3",
		},
		Runtime: RuntimePlan{
			ContainerRuntime: "none",
			CgroupDriver:     "systemd",
			SwapPolicy:       "system",
		},
		Kubernetes: KubernetesPlan{
			Role: "none",
			Kubeadm: KubeadmPlan{
				ConfigAPI: "kubeadm.k8s.io/v1beta4",
			},
		},
		Firewall: FirewallPlan{
			Backend:    "nftables",
			Firewalld:  false,
			BridgeTool: "iproute2 bridge",
		},
		Artifacts: ArtifactsPlan{
			RuntimePlan:   defaultPlanPath,
			InstalledPlan: "/var/lib/ki2/install-plan.yaml",
		},
	}
	ApplyProfile(&plan, profile)
	return plan
}

var minimalSystemdPackages = []string{
	"base-files",
	"linux",
	"glibc",
	"libxcrypt",
	"zlib",
	"expat",
	"openssl",
	"libcap",
	"libseccomp",
	"acl",
	"attr",
	"ncurses",
	"util-linux",
	"cfdisk",
	"kmod",
	"dbus",
	"systemd",
	"bash",
	"busybox",
	"coreutils",
	"findutils",
	"grep",
	"sed",
	"gawk",
	"tar",
	"gzip",
	"xz",
	"zstd",
	"python",
	"e2fsprogs",
	"shadow",
	"sudo",
	"iproute2",
	"ca-certificates",
	"openssh",
	"curl",
	"ki2ctl",
	"kiki-agent",
	"kiki-installer-tui",
}

var kubernetesCommonPackages = []string{
	"bridge-utils",
	"cni-plugins",
	"cri-tools",
	"conntrack-tools",
	"firewalld",
	"nftables",
	"iptables",
	"socat",
	"kubelet",
	"kubectl",
	"kubeadm",
	"ethtool",
	"chrony",
}

var crioRuntimePackages = []string{
	"conmon",
	"crun",
	"cri-o",
	"kube-node-config",
}

var containerdRuntimePackages = []string{
	"runc",
	"containerd",
	"kube-node-config-containerd",
}

var containerdStandalonePackages = []string{
	"runc",
	"containerd",
	"cni-plugins",
	"cri-tools",
}

var minimalSystemdServices = []string{
	"dbus.service",
	"kiki-boot-prepare.service",
	"getty@tty1.service",
	"systemd-logind.service",
	"systemd-networkd.service",
	"systemd-resolved.service",
	"sshd.service",
	"kiki-agent.service",
}

var kubeNodeServices = []string{
	"crio.service",
	"kubelet.service",
	"chronyd.service",
}

var containerdServices = []string{
	"containerd.service",
}

var kubernetesProfiles = map[string]string{
	"kiki-kube-bootstrap":            "first cluster bootstrap node",
	"kiki-kube-bootstrap-containerd": "first cluster bootstrap node with containerd",
	"kiki-kube-control":              "additional control-plane node",
	"kiki-kube-control-containerd":   "additional control-plane node with containerd",
	"kiki-kube-compute":              "compute node",
	"kiki-kube-compute-containerd":   "compute node with containerd",
}

var legacyProfileAliases = map[string]string{
	"kiki-kube-controller": "kiki-kube-control",
	"kiki-kube-node":       "kiki-kube-compute",
}

func canonicalProfile(profile string) string {
	if next, ok := legacyProfileAliases[profile]; ok {
		return next
	}
	return profile
}

func isKubernetesProfile(profile string) bool {
	_, ok := kubernetesProfiles[canonicalProfile(profile)]
	return ok
}

func isKubernetesComputeProfile(profile string) bool {
	normalized := canonicalProfile(profile)
	return normalized == "kiki-kube-compute" || normalized == "kiki-kube-compute-containerd"
}

func kubeRoleForProfile(profile string) string {
	normalized := canonicalProfile(profile)
	switch normalized {
	case "kiki-kube-bootstrap", "kiki-kube-bootstrap-containerd":
		return "bootstrap-control-plane"
	case "kiki-kube-control", "kiki-kube-control-containerd":
		return "control-plane"
	case "kiki-kube-compute", "kiki-kube-compute-containerd":
		return "compute"
	default:
		return "none"
	}
}

func defaultRuntimeForProfile(profile string) string {
	if strings.HasSuffix(canonicalProfile(profile), "-containerd") {
		return "containerd"
	}
	return "cri-o"
}

func ApplyProfile(plan *InstallPlan, profile string) {
	normalized := strings.TrimSpace(profile)
	if normalized == "" {
		normalized = "minimal-systemd"
	}
	normalized = canonicalProfile(normalized)
	plan.Packages.Profile = normalized
	plan.Packages.Selected = append([]string{}, minimalSystemdPackages...)
	plan.Services.Enable = append([]string{}, minimalSystemdServices...)
	plan.Runtime.ContainerRuntime = "none"
	plan.Runtime.SwapPolicy = "system"
	plan.Kubernetes = KubernetesPlan{
		Role: "none",
		Kubeadm: KubeadmPlan{
			ConfigAPI: "kubeadm.k8s.io/v1beta4",
		},
	}
	plan.Target.Filesystems.Swap.Enabled = true
	plan.Target.Filesystems.Swap.Path = "/dev/sda2"
	plan.Target.Filesystems.Swap.Policy = "system"
	plan.Firewall.Firewalld = false

	if isKubernetesProfile(normalized) {
		plan.Runtime.SwapPolicy = "kubernetes-off"
		plan.Target.Filesystems.Swap.Enabled = false
		plan.Target.Filesystems.Swap.Path = ""
		plan.Target.Filesystems.Swap.Policy = "kubernetes-off"
		plan.Target.Filesystems.Root.Path = partitionPath(plan.Target.Disk, 2)
		plan.Boot.Root = partitionPath(plan.Target.Disk, 2)
		plan.Firewall.Firewalld = !isKubernetesComputeProfile(normalized)
		applyContainerRuntime(plan, defaultRuntimeForProfile(normalized))
		configureKubeadm(plan)
	}
}

func applyContainerRuntime(plan *InstallPlan, runtime string) {
	plan.Packages.Selected = removeItems(plan.Packages.Selected, crioRuntimePackages...)
	plan.Packages.Selected = removeItems(plan.Packages.Selected, containerdRuntimePackages...)
	plan.Packages.Selected = removeItems(plan.Packages.Selected, containerdStandalonePackages...)
	plan.Services.Enable = removeItems(plan.Services.Enable, "crio.service", "containerd.service")

	if runtime == "containerd" {
		plan.Runtime.ContainerRuntime = "containerd"
		if isKubernetesProfile(plan.Packages.Profile) {
			plan.Packages.Selected = appendUnique(plan.Packages.Selected, kubernetesCommonPackages...)
			plan.Packages.Selected = appendUnique(plan.Packages.Selected, containerdRuntimePackages...)
			plan.Services.Enable = appendUnique(plan.Services.Enable, containerdServices...)
			plan.Services.Enable = appendUnique(plan.Services.Enable, "kubelet.service", "chronyd.service")
			configureKubeadm(plan)
		} else {
			plan.Packages.Selected = appendUnique(plan.Packages.Selected, containerdStandalonePackages...)
			plan.Services.Enable = appendUnique(plan.Services.Enable, containerdServices...)
		}
		return
	}

	plan.Runtime.ContainerRuntime = "cri-o"
	plan.Packages.Selected = appendUnique(plan.Packages.Selected, crioRuntimePackages...)
	plan.Services.Enable = appendUnique(plan.Services.Enable, "crio.service")
	if isKubernetesProfile(plan.Packages.Profile) {
		plan.Packages.Selected = appendUnique(plan.Packages.Selected, kubernetesCommonPackages...)
		plan.Services.Enable = appendUnique(plan.Services.Enable, "kubelet.service", "chronyd.service")
		configureKubeadm(plan)
	}
}

func configureKubeadm(plan *InstallPlan) {
	role := kubeRoleForProfile(plan.Packages.Profile)
	runtime := plan.Runtime.ContainerRuntime
	criSocket := "unix:///var/run/crio/crio.sock"
	if runtime == "containerd" {
		criSocket = "unix:///run/containerd/containerd.sock"
	}
	kubeadm := KubeadmPlan{
		ConfigAPI:      "kubeadm.k8s.io/v1beta4",
		ConfigOutput:   "/etc/kubernetes/kiki/kubeadm.local.yaml",
		CRISocket:      criSocket,
		ControlPlane:   role == "bootstrap-control-plane" || role == "control-plane",
		ConfigTemplate: "/etc/kubernetes/kiki/kubeadm-join-compute.yaml",
		Action:         "join",
		Command:        "kubeadm join --config /etc/kubernetes/kiki/kubeadm.local.yaml",
	}
	if role == "bootstrap-control-plane" {
		kubeadm.Action = "init"
		kubeadm.ConfigTemplate = "/etc/kubernetes/kiki/kubeadm-init.yaml"
		kubeadm.Command = "kubeadm init --config /etc/kubernetes/kiki/kubeadm.local.yaml"
	} else if role == "control-plane" {
		kubeadm.ConfigTemplate = "/etc/kubernetes/kiki/kubeadm-join-control-plane.yaml"
	}
	plan.Kubernetes = KubernetesPlan{Role: role, Kubeadm: kubeadm}
}

func setLocalSource(plan *InstallPlan, mediaRoot string) {
	mediaRoot = strings.TrimRight(strings.TrimSpace(mediaRoot), "/")
	if mediaRoot == "" {
		mediaRoot = defaultMediaRoot
	}
	plan.Source.Type = "local-installer-media"
	plan.Source.MediaRoot = mediaRoot
	plan.Source.RepoIndex = localMediaRepoIndex(mediaRoot)
	plan.Source.RepoURL = ""
	plan.Source.DisconnectedInstall = true
}

func setRemoteSource(plan *InstallPlan, repoURL string) error {
	base := normalizeRepoBase(repoURL)
	if !strings.HasPrefix(base, "http://") && !strings.HasPrefix(base, "https://") {
		return fmt.Errorf("remote source requires http:// or https:// URL")
	}
	plan.Source.Type = "remote-repository"
	plan.Source.MediaRoot = ""
	plan.Source.RepoIndex = repoIndexFromBase(base)
	plan.Source.RepoURL = base
	plan.Source.DisconnectedInstall = false
	return nil
}

func setMirrorSource(plan *InstallPlan, repoBase string) error {
	base := normalizeRepoBase(repoBase)
	if base == "" {
		return fmt.Errorf("mirror source path or URL is empty")
	}
	plan.Source.Type = "mirror"
	plan.Source.MediaRoot = ""
	plan.Source.RepoIndex = repoIndexFromBase(base)
	plan.Source.RepoURL = base
	plan.Source.DisconnectedInstall = true
	return nil
}

func normalizeRepoBase(value string) string {
	value = strings.TrimRight(strings.TrimSpace(value), "/")
	if strings.HasPrefix(value, "/") {
		return "file://" + value
	}
	return value
}

func repoIndexFromBase(base string) string {
	return strings.TrimRight(base, "/") + "/repo/index.x86_64.json"
}

func localMediaRepoIndex(mediaRoot string) string {
	return strings.TrimRight(mediaRoot, "/") + "/kiki/repo/index.x86_64.json"
}

func (t *TUI) Run() error {
	if t.In == nil {
		t.In = os.Stdin
	}
	if t.Out == nil {
		t.Out = os.Stdout
	}
	scanner := bufio.NewScanner(t.In)
	t.Render()
	for {
		fmt.Fprint(t.Out, "\nkiki> ")
		if !scanner.Scan() {
			return scanner.Err()
		}
		done, err := t.ApplyCommand(scanner.Text())
		if err != nil {
			fmt.Fprintln(t.Out, "error:", err)
			continue
		}
		if done {
			return nil
		}
	}
}

func (t *TUI) ApplyCommand(line string) (bool, error) {
	if t.Out == nil {
		t.Out = io.Discard
	}
	line = strings.TrimSpace(line)
	if line == "" || line == "show" || line == "dashboard" {
		t.Render()
		return false, nil
	}
	fields := strings.Fields(line)
	switch fields[0] {
	case "help", "?":
		printHelp(t.Out)
	case "q", "quit", "exit":
		return true, nil
	case "1":
		fmt.Fprintln(t.Out, "Disk:", dashboardDiskSummary(t.Plan))
		fmt.Fprintln(t.Out, "Use: disk /dev/sda")
	case "2":
		fmt.Fprintln(t.Out, "Network:", dashboardNetworkSummary(t.Plan))
		fmt.Fprintln(t.Out, "Use: network dhcp [en* eth*], network static 192.168.122.50/24 192.168.122.1 1.1.1.1 [en* eth*], or network off")
	case "3":
		fmt.Fprintln(t.Out, "Account:", dashboardAccountSummary(t.Plan))
		fmt.Fprintln(t.Out, "Use: user kiki and hostname localhost.localdomain")
	case "4":
		fmt.Fprintln(t.Out, "Profile:", t.Plan.Packages.Profile)
		fmt.Fprintln(t.Out, "Use: profile minimal-systemd|kiki-kube-bootstrap|kiki-kube-control|kiki-kube-compute")
		fmt.Fprintln(t.Out, "     add -containerd to a Kubernetes profile to use containerd by default")
	case "5":
		fmt.Fprintln(t.Out, "Runtime:", t.Plan.Runtime.ContainerRuntime)
		fmt.Fprintln(t.Out, "Use: runtime none, runtime crio, or runtime containerd")
	case "6":
		t.Reviewed = true
		t.Render()
		fmt.Fprintln(t.Out)
		if ReviewReady(t.Plan) {
			fmt.Fprintln(t.Out, "Review: ready to write install plan.")
		} else {
			fmt.Fprintln(t.Out, "Review: blocked. Fix BLOCK items before install.")
		}
	case "7", "start", "install":
		t.Reviewed = true
		t.Render()
		fmt.Fprintln(t.Out)
		if !ReviewReady(t.Plan) {
			fmt.Fprintln(t.Out, "Start install blocked. Fix BLOCK items before install.")
			return false, nil
		}
		t.Plan.Artifacts.RuntimePlan = t.PlanPath
		if err := WritePlanFile(t.PlanPath, t.Plan); err != nil {
			return false, err
		}
		t.PlanWritten = true
		fmt.Fprintln(t.Out, "wrote", t.PlanPath)
		fmt.Fprintln(t.Out, "Stage-1 installer can consume this install plan.")
	case "profile":
		if len(fields) != 2 {
			return false, fmt.Errorf("usage: profile minimal-systemd|kiki-kube-bootstrap|kiki-kube-control|kiki-kube-compute[-containerd]")
		}
		ApplyProfile(&t.Plan, fields[1])
		t.Render()
	case "disk":
		if len(fields) != 2 {
			return false, fmt.Errorf("usage: disk /dev/sda")
		}
		if isPartitionPath(fields[1]) {
			return false, fmt.Errorf("target disk must be a whole disk, not %s", fields[1])
		}
		t.Plan.Target.Disk = fields[1]
		base := fields[1]
		t.Plan.Target.Filesystems.ESP.Path = partitionPath(base, 1)
		if t.Plan.Target.Filesystems.Swap.Enabled {
			t.Plan.Target.Filesystems.Swap.Path = partitionPath(base, 2)
			t.Plan.Target.Filesystems.Root.Path = partitionPath(base, 3)
			t.Plan.Boot.Root = partitionPath(base, 3)
		} else {
			t.Plan.Target.Filesystems.Root.Path = partitionPath(base, 2)
			t.Plan.Boot.Root = partitionPath(base, 2)
		}
		t.Render()
	case "swap":
		if len(fields) != 2 || (fields[1] != "on" && fields[1] != "off") {
			return false, fmt.Errorf("usage: swap on|off")
		}
		t.Plan.Target.Filesystems.Swap.Enabled = fields[1] == "on"
		if t.Plan.Target.Filesystems.Swap.Enabled {
			t.Plan.Target.Filesystems.Swap.Policy = "system"
			t.Plan.Runtime.SwapPolicy = "system"
			if t.Plan.Target.Filesystems.Swap.Path == "" {
				if needsPartitionP(t.Plan.Target.Disk) {
					t.Plan.Target.Filesystems.Swap.Path = t.Plan.Target.Disk + "p2"
				} else {
					t.Plan.Target.Filesystems.Swap.Path = t.Plan.Target.Disk + "2"
				}
			}
		} else {
			t.Plan.Target.Filesystems.Swap.Path = ""
			if isKubernetesProfile(t.Plan.Packages.Profile) {
				t.Plan.Target.Filesystems.Swap.Policy = "kubernetes-off"
				t.Plan.Runtime.SwapPolicy = "kubernetes-off"
			} else {
				t.Plan.Target.Filesystems.Swap.Policy = "disabled"
				t.Plan.Runtime.SwapPolicy = "disabled"
			}
		}
		t.Render()
	case "network":
		if len(fields) < 2 || (fields[1] != "dhcp" && fields[1] != "static" && fields[1] != "off") {
			return false, fmt.Errorf("usage: network dhcp|off [interface-match] | network static <address/prefix> <gateway|none> <dns|none> [interface-match]")
		}
		t.Plan.Network.Mode = fields[1]
		t.Plan.Network.DHCP4 = false
		t.Plan.Network.IPv6AcceptRA = false
		t.Plan.Network.Address = ""
		t.Plan.Network.Gateway = ""
		t.Plan.Network.DNS = ""
		t.Plan.Network.NTP = ""
		switch fields[1] {
		case "dhcp":
			t.Plan.Network.DHCP4 = true
			t.Plan.Network.IPv6AcceptRA = true
			if len(fields) > 2 {
				t.Plan.Network.InterfaceMatch = strings.Join(fields[2:], " ")
			}
		case "static":
			if len(fields) < 5 {
				return false, fmt.Errorf("usage: network static <address/prefix> <gateway|none> <dns|none> [interface-match]")
			}
			t.Plan.Network.Address = fields[2]
			if fields[3] != "none" {
				t.Plan.Network.Gateway = fields[3]
			}
			if fields[4] != "none" {
				t.Plan.Network.DNS = strings.ReplaceAll(fields[4], ",", " ")
			}
			if len(fields) > 5 {
				t.Plan.Network.InterfaceMatch = strings.Join(fields[5:], " ")
			}
		case "off":
			if len(fields) > 2 {
				t.Plan.Network.InterfaceMatch = strings.Join(fields[2:], " ")
			}
		}
		t.Render()
	case "source":
		if len(fields) < 2 || (fields[1] != "local" && fields[1] != "remote" && fields[1] != "mirror") {
			return false, fmt.Errorf("usage: source local [media-root] | remote http://repo.example/kiki | mirror /srv/kiki-mirror")
		}
		switch fields[1] {
		case "local":
			if len(fields) > 3 {
				return false, fmt.Errorf("usage: source local [media-root]")
			}
			mediaRoot := defaultMediaRoot
			if len(fields) == 3 {
				mediaRoot = fields[2]
			}
			setLocalSource(&t.Plan, mediaRoot)
		case "remote":
			if len(fields) != 3 {
				return false, fmt.Errorf("usage: source remote http://repo.example/kiki")
			}
			if err := setRemoteSource(&t.Plan, fields[2]); err != nil {
				return false, err
			}
		case "mirror":
			if len(fields) != 3 {
				return false, fmt.Errorf("usage: source mirror /srv/kiki-mirror")
			}
			if err := setMirrorSource(&t.Plan, fields[2]); err != nil {
				return false, err
			}
		}
		t.Render()
	case "verify-key":
		if len(fields) != 2 {
			return false, fmt.Errorf("usage: verify-key /etc/ki2/trust/stage2-v2-repo.hmac")
		}
		t.Plan.Source.VerifyKey = fields[1]
		t.Render()
	case "user":
		if len(fields) != 2 {
			return false, fmt.Errorf("usage: user kiki")
		}
		if !validUserName(fields[1]) {
			return false, fmt.Errorf("invalid user name: %s", fields[1])
		}
		t.Plan.Users.Admin.Name = fields[1]
		t.Plan.Users.Admin.PrimaryGroup = fields[1]
		t.Render()
	case "hostname":
		if len(fields) != 2 {
			return false, fmt.Errorf("usage: hostname localhost.localdomain")
		}
		t.Plan.Identity.Hostname = fields[1]
		t.Render()
	case "runtime":
		if len(fields) != 2 || (fields[1] != "none" && fields[1] != "crio" && fields[1] != "cri-o" && fields[1] != "containerd") {
			return false, fmt.Errorf("usage: runtime none|crio|containerd")
		}
		if fields[1] == "none" {
			if isKubernetesProfile(t.Plan.Packages.Profile) {
				return false, fmt.Errorf("Kubernetes profiles require a CRI runtime; use runtime crio or runtime containerd")
			}
			t.Plan.Runtime.ContainerRuntime = "none"
			runtimePackages := append([]string{}, kubernetesCommonPackages...)
			runtimePackages = append(runtimePackages, crioRuntimePackages...)
			runtimePackages = append(runtimePackages, containerdRuntimePackages...)
			runtimePackages = append(runtimePackages, containerdStandalonePackages...)
			t.Plan.Packages.Selected = removeItems(t.Plan.Packages.Selected, runtimePackages...)
			t.Plan.Services.Enable = removeItems(t.Plan.Services.Enable, kubeNodeServices...)
			t.Plan.Services.Enable = removeItems(t.Plan.Services.Enable, containerdServices...)
		} else {
			if fields[1] == "containerd" {
				applyContainerRuntime(&t.Plan, "containerd")
			} else {
				applyContainerRuntime(&t.Plan, "cri-o")
			}
		}
		t.Render()
	case "firewalld":
		if len(fields) != 2 || (fields[1] != "on" && fields[1] != "off") {
			return false, fmt.Errorf("usage: firewalld on|off")
		}
		t.Plan.Firewall.Firewalld = fields[1] == "on"
		if t.Plan.Firewall.Firewalld {
			t.Plan.Packages.Selected = appendUnique(t.Plan.Packages.Selected, "firewalld")
			t.Plan.Services.Enable = appendUnique(t.Plan.Services.Enable, "firewalld.service")
		} else {
			t.Plan.Services.Enable = removeItems(t.Plan.Services.Enable, "firewalld.service")
			t.Plan.Packages.Selected = removeItems(t.Plan.Packages.Selected, "firewalld")
		}
		t.Render()
	case "review":
		t.Reviewed = true
		t.Render()
		fmt.Fprintln(t.Out)
		if ReviewReady(t.Plan) {
			fmt.Fprintln(t.Out, "Review: ready to write install plan.")
		} else {
			fmt.Fprintln(t.Out, "Review: blocked. Fix BLOCK items before install.")
		}
	case "s", "shell":
		fmt.Fprintln(t.Out, "Shell handoff is provided by the stage-1 C installer. This Go TUI preview keeps the install plan in process.")
	case "write":
		path := t.PlanPath
		if len(fields) == 2 {
			path = fields[1]
		} else if len(fields) > 2 {
			return false, fmt.Errorf("usage: write [path]")
		}
		t.Plan.Artifacts.RuntimePlan = path
		if err := WritePlanFile(path, t.Plan); err != nil {
			return false, err
		}
		t.PlanWritten = true
		fmt.Fprintln(t.Out, "wrote", path)
	default:
		return false, fmt.Errorf("unknown command %q; type help", fields[0])
	}
	return false, nil
}

func (t *TUI) Render() {
	if t.Out == nil {
		t.Out = io.Discard
	}
	fmt.Fprintln(t.Out, "KIKI OS Installer")
	fmt.Fprintln(t.Out)
	fmt.Fprintln(t.Out, "Install Plan:", t.PlanPath)
	fmt.Fprintln(t.Out)
	for _, check := range t.dashboardRows() {
		fmt.Fprintf(t.Out, "[%s] %-10s %s\n", dashboardToken(check.State), check.Name, check.Summary)
	}
	fmt.Fprintln(t.Out)
	fmt.Fprintln(t.Out, "1) Disk")
	fmt.Fprintln(t.Out, "2) Network")
	fmt.Fprintln(t.Out, "3) Account")
	fmt.Fprintln(t.Out, "4) Profile")
	fmt.Fprintln(t.Out, "5) Runtime")
	fmt.Fprintln(t.Out, "6) Review install plan")
	fmt.Fprintln(t.Out, "7) Start install")
	fmt.Fprintln(t.Out, "s) Shell")
	fmt.Fprintln(t.Out, "q) Power off")
}

func (t *TUI) dashboardRows() []Check {
	disk := checkDisk(t.Plan)
	disk.Summary = dashboardDiskSummary(t.Plan)
	if disk.State == "OK" && t.Plan.Target.Partitioning == "auto-whole-disk" {
		disk.State = "WARN"
	}
	network := checkNetwork(t.Plan)
	network.Summary = dashboardNetworkSummary(t.Plan)
	account := checkAccount(t.Plan)
	account.Summary = dashboardAccountSummary(t.Plan)
	profile := Check{Name: "Profile", State: "PENDING", Summary: "minimal-systemd"}
	if t.Plan.Packages.Profile != "" {
		profile.Summary = t.Plan.Packages.Profile
	}
	runtime := Check{Name: "Runtime", State: "PENDING", Summary: "none"}
	if t.Plan.Runtime.ContainerRuntime == "cri-o" {
		runtime.State = "OK"
		runtime.Summary = "CRI-O, systemd cgroup"
	} else if t.Plan.Runtime.ContainerRuntime != "" && t.Plan.Runtime.ContainerRuntime != "none" {
		runtime.State = "OK"
		runtime.Summary = t.Plan.Runtime.ContainerRuntime
	}
	review := Check{Name: "Review", State: "PENDING", Summary: "not ready"}
	if t.Reviewed || t.PlanWritten {
		if ReviewReady(t.Plan) {
			review.State = "OK"
			review.Summary = "ready"
		} else {
			review.State = "BLOCK"
			review.Summary = "blocked"
		}
	}
	return []Check{disk, network, account, profile, runtime, review}
}

func dashboardToken(state string) string {
	switch state {
	case "OK":
		return "OK"
	case "PENDING":
		return " "
	default:
		return "!"
	}
}

func dashboardDiskSummary(plan InstallPlan) string {
	swap := "swap on"
	if !plan.Target.Filesystems.Swap.Enabled {
		if isKubernetesProfile(plan.Packages.Profile) {
			swap = "swap off for Kubernetes"
		} else {
			swap = "swap off"
		}
	}
	disk := plan.Target.Disk
	if disk == "" {
		disk = "not selected"
	}
	return fmt.Sprintf("auto partition: %s, ESP + root, %s", disk, swap)
}

func dashboardNetworkSummary(plan InstallPlan) string {
	mode := strings.ToUpper(plan.Network.Mode)
	if mode == "" {
		mode = "OFF"
	}
	if plan.Network.Mode == "static" && plan.Network.Address != "" {
		return fmt.Sprintf("%s, %s, %s", mode, plan.Network.Address, plan.Network.InterfaceMatch)
	}
	return fmt.Sprintf("%s, %s, %s", mode, plan.Network.Manager, plan.Network.InterfaceMatch)
}

func dashboardAccountSummary(plan InstallPlan) string {
	sudo := "sudo disabled"
	if contains(plan.Users.Admin.SupplementaryGroups, "sudo") {
		sudo = "sudo enabled"
	}
	root := "root unlocked"
	if plan.Users.Root.Locked {
		root = "root locked"
	}
	return fmt.Sprintf("user: %s, %s, %s", plan.Users.Admin.Name, sudo, root)
}

func printHelp(w io.Writer) {
	fmt.Fprintln(w, "Commands:")
	fmt.Fprintln(w, "  profile minimal-systemd|kiki-kube-bootstrap|kiki-kube-control|kiki-kube-compute")
	fmt.Fprintln(w, "  profile kiki-kube-bootstrap-containerd|kiki-kube-control-containerd|kiki-kube-compute-containerd")
	fmt.Fprintln(w, "    legacy aliases: kiki-kube-controller -> kiki-kube-control, kiki-kube-node -> kiki-kube-compute")
	fmt.Fprintln(w, "  disk /dev/sda")
	fmt.Fprintln(w, "  swap on|off")
	fmt.Fprintln(w, "  network dhcp|off [en* eth*]")
	fmt.Fprintln(w, "  network static <address/prefix> <gateway|none> <dns|none> [en* eth*]")
	fmt.Fprintln(w, "  source local [media-root]")
	fmt.Fprintln(w, "  source remote http://repo.example/kiki")
	fmt.Fprintln(w, "  source mirror /srv/kiki-mirror|file:///srv/kiki-mirror")
	fmt.Fprintln(w, "  verify-key /etc/ki2/trust/stage2-v2-repo.hmac")
	fmt.Fprintln(w, "  user kiki")
	fmt.Fprintln(w, "  hostname localhost.localdomain")
	fmt.Fprintln(w, "  runtime none|crio|containerd")
	fmt.Fprintln(w, "  firewalld on|off")
	fmt.Fprintln(w, "  review")
	fmt.Fprintln(w, "  write [path]")
	fmt.Fprintln(w, "  quit")
}

func PlanChecks(plan InstallPlan) []Check {
	checks := []Check{
		checkDisk(plan),
		checkNetwork(plan),
		checkAccount(plan),
		checkProfile(plan),
		checkRuntime(plan),
	}
	state := "OK"
	summary := "all required sections are valid"
	for _, check := range checks {
		if check.State == "BLOCK" {
			state = "BLOCK"
			summary = "fix blocking sections before install"
			break
		}
		if check.State == "WARN" && state == "OK" {
			state = "WARN"
			summary = "usable, but review warnings before install"
		}
	}
	checks = append(checks, Check{Name: "Review", State: state, Summary: summary})
	return checks
}

func checkDisk(plan InstallPlan) Check {
	if plan.Target.Disk == "" {
		return Check{Name: "Disk", State: "BLOCK", Summary: "target disk is not selected"}
	}
	if isPartitionPath(plan.Target.Disk) {
		return Check{Name: "Disk", State: "BLOCK", Summary: "target must be a whole disk, not a partition"}
	}
	swap := "off"
	if plan.Target.Filesystems.Swap.Enabled {
		swap = "on"
	}
	return Check{Name: "Disk", State: "OK", Summary: fmt.Sprintf("%s, %s, ESP + root, swap %s", plan.Target.Disk, plan.Target.Partitioning, swap)}
}

func checkNetwork(plan InstallPlan) Check {
	if plan.Network.Mode != "dhcp" && plan.Network.Mode != "static" && plan.Network.Mode != "off" {
		return Check{Name: "Network", State: "BLOCK", Summary: "network mode must be dhcp, static, or off"}
	}
	if plan.Network.Mode == "static" && plan.Network.Address == "" {
		return Check{Name: "Network", State: "BLOCK", Summary: "static network mode requires address/prefix"}
	}
	return Check{Name: "Network", State: "OK", Summary: fmt.Sprintf("%s via %s (%s)", plan.Network.Mode, plan.Network.Manager, plan.Network.InterfaceMatch)}
}

func checkAccount(plan InstallPlan) Check {
	if !validUserName(plan.Users.Admin.Name) {
		return Check{Name: "Account", State: "BLOCK", Summary: "admin user name is invalid"}
	}
	if !contains(plan.Users.Admin.SupplementaryGroups, "sudo") {
		return Check{Name: "Account", State: "WARN", Summary: "admin user is not in sudo group"}
	}
	return Check{Name: "Account", State: "OK", Summary: fmt.Sprintf("user %s, sudo enabled, root locked: %t", plan.Users.Admin.Name, plan.Users.Root.Locked)}
}

func checkProfile(plan InstallPlan) Check {
	if plan.Packages.Profile == "" || len(plan.Packages.Selected) == 0 {
		return Check{Name: "Profile", State: "BLOCK", Summary: "no package profile selected"}
	}
	return Check{Name: "Profile", State: "OK", Summary: fmt.Sprintf("%s (%d packages)", plan.Packages.Profile, len(plan.Packages.Selected))}
}

func checkRuntime(plan InstallPlan) Check {
	if isKubernetesProfile(plan.Packages.Profile) && plan.Target.Filesystems.Swap.Enabled {
		return Check{Name: "Runtime", State: "WARN", Summary: "Kubernetes profiles should keep swap off unless kubelet swap is configured"}
	}
	if plan.Runtime.ContainerRuntime == "cri-o" {
		return Check{Name: "Runtime", State: "OK", Summary: "CRI-O, cgroup driver systemd, firewall backend " + plan.Firewall.Backend}
	}
	if plan.Runtime.ContainerRuntime == "containerd" {
		return Check{Name: "Runtime", State: "OK", Summary: "containerd, cgroup driver systemd, firewall backend " + plan.Firewall.Backend}
	}
	return Check{Name: "Runtime", State: "OK", Summary: "no container runtime selected"}
}

func ReviewReady(plan InstallPlan) bool {
	for _, check := range PlanChecks(plan) {
		if check.State == "BLOCK" {
			return false
		}
	}
	return true
}

func WritePlanFile(path string, plan InstallPlan) error {
	if path == "" {
		return fmt.Errorf("plan path is empty")
	}
	if path == "-" {
		return WritePlanYAML(os.Stdout, plan)
	}
	dir := filepath.Dir(path)
	if dir != "." && dir != "" {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return err
		}
	}
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	return WritePlanYAML(f, plan)
}

func WritePlanYAML(w io.Writer, plan InstallPlan) error {
	bw := bufio.NewWriter(w)
	line := func(format string, args ...any) {
		fmt.Fprintf(bw, format+"\n", args...)
	}

	line("install_plan:")
	line("  schema: %s", quoteYAML(plan.Schema))
	line("  api_version: %s", quoteYAML(plan.APIVersion))
	line("  kind: %s", quoteYAML(plan.Kind))
	line("  generated_by: %s", quoteYAML(plan.GeneratedBy))
	line("  mode: %s", quoteYAML(plan.Mode))
	line("  source:")
	line("    type: %s", quoteYAML(plan.Source.Type))
	line("    media_root: %s", quoteYAML(plan.Source.MediaRoot))
	line("    repo_index: %s", quoteYAML(plan.Source.RepoIndex))
	line("    repo_url: %s", quoteYAML(plan.Source.RepoURL))
	line("    channel: %s", quoteYAML(plan.Source.Channel))
	line("    verify_key: %s", quoteYAML(plan.Source.VerifyKey))
	line("    disconnected_install: %t", plan.Source.DisconnectedInstall)
	line("  target:")
	line("    disk: %s", quoteYAML(plan.Target.Disk))
	line("    partitioning: %s", quoteYAML(plan.Target.Partitioning))
	line("    partition_table: %s", quoteYAML(plan.Target.PartitionTable))
	line("    disk_mib: %d", plan.Target.DiskMiB)
	line("    memory_mib: %d", plan.Target.MemoryMiB)
	line("    filesystems:")
	writeFS := func(name string, fs FilesystemPlan) {
		line("      %s:", name)
		line("        path: %s", quoteYAML(fs.Path))
		line("        type: %s", quoteYAML(fs.Type))
		line("        mountpoint: %s", quoteYAML(fs.Mountpoint))
		line("        size_mib: %d", fs.SizeMiB)
		line("        label: %s", quoteYAML(fs.Label))
	}
	writeFS("esp", plan.Target.Filesystems.ESP)
	line("      swap:")
	line("        enabled: %t", plan.Target.Filesystems.Swap.Enabled)
	line("        path: %s", quoteYAML(plan.Target.Filesystems.Swap.Path))
	line("        size_mib: %d", plan.Target.Filesystems.Swap.SizeMiB)
	line("        label: %s", quoteYAML(plan.Target.Filesystems.Swap.Label))
	line("        policy: %s", quoteYAML(plan.Target.Filesystems.Swap.Policy))
	writeFS("root", plan.Target.Filesystems.Root)
	line("  identity:")
	line("    hostname: %s", quoteYAML(plan.Identity.Hostname))
	line("  network:")
	line("    manager: %s", quoteYAML(plan.Network.Manager))
	line("    resolver: %s", quoteYAML(plan.Network.Resolver))
	line("    mode: %s", quoteYAML(plan.Network.Mode))
	line("    interface_match: %s", quoteYAML(plan.Network.InterfaceMatch))
	line("    dhcp4: %t", plan.Network.DHCP4)
	line("    ipv6_accept_ra: %t", plan.Network.IPv6AcceptRA)
	line("    address: %s", quoteYAML(plan.Network.Address))
	line("    gateway: %s", quoteYAML(plan.Network.Gateway))
	line("    dns: %s", quoteYAML(plan.Network.DNS))
	line("    ntp: %s", quoteYAML(plan.Network.NTP))
	line("  users:")
	line("    admin:")
	line("      name: %s", quoteYAML(plan.Users.Admin.Name))
	line("      primary_group: %s", quoteYAML(plan.Users.Admin.PrimaryGroup))
	line("      supplementary_groups:")
	writeStringList(bw, "        ", plan.Users.Admin.SupplementaryGroups)
	line("      shell: %s", quoteYAML(plan.Users.Admin.Shell))
	line("      password: %s", quoteYAML(plan.Users.Admin.Password))
	line("    root:")
	line("      locked: %t", plan.Users.Root.Locked)
	line("      password: %s", quoteYAML(plan.Users.Root.Password))
	line("  packages:")
	line("    profile: %s", quoteYAML(plan.Packages.Profile))
	line("    dependency_resolution: %t", plan.Packages.DependencyResolution)
	line("    selected:")
	writeStringList(bw, "      ", plan.Packages.Selected)
	line("  services:")
	line("    enable:")
	writeStringList(bw, "      ", plan.Services.Enable)
	line("  boot:")
	line("    loader: %s", quoteYAML(plan.Boot.Loader))
	line("    kernel: %s", quoteYAML(plan.Boot.Kernel))
	line("    initramfs: %s", quoteYAML(plan.Boot.Initramfs))
	line("    root: %s", quoteYAML(plan.Boot.Root))
	line("  runtime:")
	line("    container_runtime: %s", quoteYAML(plan.Runtime.ContainerRuntime))
	line("    cgroup_driver: %s", quoteYAML(plan.Runtime.CgroupDriver))
	line("    swap_policy: %s", quoteYAML(plan.Runtime.SwapPolicy))
	line("  kubernetes:")
	line("    role: %s", quoteYAML(plan.Kubernetes.Role))
	line("    kubeadm:")
	line("      config_api: %s", quoteYAML(plan.Kubernetes.Kubeadm.ConfigAPI))
	line("      action: %s", quoteYAML(plan.Kubernetes.Kubeadm.Action))
	line("      config_template: %s", quoteYAML(plan.Kubernetes.Kubeadm.ConfigTemplate))
	line("      config_output: %s", quoteYAML(plan.Kubernetes.Kubeadm.ConfigOutput))
	line("      command: %s", quoteYAML(plan.Kubernetes.Kubeadm.Command))
	line("      control_plane: %t", plan.Kubernetes.Kubeadm.ControlPlane)
	line("      cri_socket: %s", quoteYAML(plan.Kubernetes.Kubeadm.CRISocket))
	line("  firewall:")
	line("    backend: %s", quoteYAML(plan.Firewall.Backend))
	line("    firewalld: %t", plan.Firewall.Firewalld)
	line("    bridge_tool: %s", quoteYAML(plan.Firewall.BridgeTool))
	line("  artifacts:")
	line("    runtime_plan: %s", quoteYAML(plan.Artifacts.RuntimePlan))
	line("    installed_plan: %s", quoteYAML(plan.Artifacts.InstalledPlan))
	return bw.Flush()
}

func writeStringList(w io.Writer, indent string, items []string) {
	if len(items) == 0 {
		fmt.Fprintf(w, "%s[]\n", indent)
		return
	}
	for _, item := range items {
		fmt.Fprintf(w, "%s- %s\n", indent, quoteYAML(item))
	}
}

func quoteYAML(value string) string {
	if value == "" {
		return "null"
	}
	escaped := strings.ReplaceAll(value, "\\", "\\\\")
	escaped = strings.ReplaceAll(escaped, "\"", "\\\"")
	return "\"" + escaped + "\""
}

func appendUnique(items []string, add ...string) []string {
	seen := map[string]bool{}
	out := make([]string, 0, len(items)+len(add))
	for _, item := range items {
		if item == "" || seen[item] {
			continue
		}
		seen[item] = true
		out = append(out, item)
	}
	for _, item := range add {
		if item == "" || seen[item] {
			continue
		}
		seen[item] = true
		out = append(out, item)
	}
	return out
}

func removeItems(items []string, remove ...string) []string {
	drop := map[string]bool{}
	for _, item := range remove {
		drop[item] = true
	}
	out := items[:0]
	for _, item := range items {
		if !drop[item] {
			out = append(out, item)
		}
	}
	return out
}

func contains(items []string, value string) bool {
	for _, item := range items {
		if item == value {
			return true
		}
	}
	return false
}

func validUserName(value string) bool {
	if value == "" || value == "root" {
		return false
	}
	for i := 0; i < len(value); i++ {
		ch := value[i]
		if (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9') || ch == '_' || ch == '-' {
			continue
		}
		return false
	}
	return value[0] >= 'a' && value[0] <= 'z'
}

func isPartitionPath(value string) bool {
	base := filepath.Base(value)
	if base == "." || base == string(filepath.Separator) || base == "" {
		return false
	}
	if strings.HasPrefix(base, "nvme") || strings.HasPrefix(base, "mmcblk") {
		p := strings.LastIndex(base, "p")
		return p >= 0 && p < len(base)-1 && allDigits(base[p+1:])
	}
	return len(base) > 0 && base[len(base)-1] >= '0' && base[len(base)-1] <= '9'
}

func needsPartitionP(value string) bool {
	base := filepath.Base(value)
	return strings.HasPrefix(base, "nvme") || strings.HasPrefix(base, "mmcblk")
}

func partitionPath(disk string, number int) string {
	if needsPartitionP(disk) {
		return fmt.Sprintf("%sp%d", disk, number)
	}
	return fmt.Sprintf("%s%d", disk, number)
}

func allDigits(value string) bool {
	for i := 0; i < len(value); i++ {
		if value[i] < '0' || value[i] > '9' {
			return false
		}
	}
	return value != ""
}
