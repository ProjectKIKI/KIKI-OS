package main

import (
	"bufio"
	"bytes"
	"flag"
	"fmt"
	"io"
	"net"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"unsafe"
)

const (
	appVersion       = "0.5.0"
	defaultPlanPath  = "/run/kiki/install-plan.yaml"
	defaultMediaRoot = "/run/install-media"
)

type InstallPlan struct {
	Schema       string
	APIVersion   string
	Kind         string
	GeneratedBy  string
	Mode         string
	Source       SourcePlan
	Target       TargetPlan
	Identity     IdentityPlan
	Localization LocalizationPlan
	Network      NetworkPlan
	Users        UsersPlan
	Packages     PackagesPlan
	Services     ServicesPlan
	Boot         BootPlan
	Runtime      RuntimePlan
	AI           AIPlan
	Kubernetes   KubernetesPlan
	Firewall     FirewallPlan
	Artifacts    ArtifactsPlan
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

type LocalizationPlan struct {
	Locale   string
	Keymap   string
	Timezone string
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
	Groups               []string
	DependencyResolution bool
	Selected             []string
}

type ServicesPlan struct {
	Disable       []string
	Enable        []string
	DefaultTarget string
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

type AIPlan struct {
	Mode            string
	Endpoint        string
	Model           string
	ConsoleTTY      string
	RequireApproval bool
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
	ASCII       bool
}

func main() {
	planPath := flag.String("plan", defaultPlanPath, "install plan path")
	profile := flag.String("profile", "minimal-systemd", "initial profile")
	packageGroups := flag.String("groups", "", "comma-separated additional package groups")
	mode := flag.String("mode", "guided", "install mode: guided or unattended")
	disk := flag.String("disk", "/dev/sda", "target whole disk")
	swapMode := flag.String("swap", "auto", "swap policy: auto, on, or off")
	hostname := flag.String("hostname", "localhost.localdomain", "installed hostname")
	adminUser := flag.String("user", "kiki", "administrator user")
	locale := flag.String("locale", "ko_KR.UTF-8", "installed locale")
	keymap := flag.String("keymap", "kr", "console keymap")
	timezone := flag.String("timezone", "Asia/Seoul", "installed timezone")
	runtimeName := flag.String("runtime", "", "container runtime override: none, crio, or containerd")
	networkMode := flag.String("network", "dhcp", "network mode: dhcp, static, or off")
	networkInterface := flag.String("network-interface", "en* eth*", "systemd-networkd interface match")
	address := flag.String("address", "", "static address with prefix")
	gateway := flag.String("gateway", "", "static gateway")
	dns := flag.String("dns", "", "space-separated DNS servers")
	sourceType := flag.String("source", "local", "package source: local, remote, or mirror")
	sourceLocation := flag.String("source-location", defaultMediaRoot, "media root, repository URL, or mirror path")
	verifyKey := flag.String("verify-key", "", "repository verification key")
	aiMode := flag.String("ai", "profile-default", "AI mode: profile-default, local, remote, or off")
	aiEndpoint := flag.String("ai-endpoint", "", "OpenAI-compatible endpoint override")
	renderOnly := flag.Bool("render", false, "render dashboard and exit")
	writeOnly := flag.Bool("write", false, "write install plan and exit")
	fullscreen := flag.Bool("fullscreen", false, "run the full-screen keyboard-driven TUI")
	asciiMode := flag.Bool("ascii", false, "use an ASCII-only full-screen UI for the Linux kernel VT")
	flag.Usage = usage
	flag.Parse()
	if *mode != "guided" && *mode != "quick-vm" && *mode != "unattended" {
		fatalFlag(fmt.Errorf("mode must be guided, quick-vm, or unattended"))
	}

	plan := NewDefaultPlan(*profile)
	plan.Mode = *mode
	if err := applyDisk(&plan, *disk); err != nil {
		fatalFlag(err)
	}
	if *swapMode != "auto" {
		if err := applySwap(&plan, *swapMode); err != nil {
			fatalFlag(err)
		}
		if err := applyDisk(&plan, *disk); err != nil {
			fatalFlag(err)
		}
	}
	if !validUserName(*adminUser) {
		fatalFlag(fmt.Errorf("invalid user name: %s", *adminUser))
	}
	plan.Users.Admin.Name = *adminUser
	plan.Users.Admin.PrimaryGroup = *adminUser
	plan.Identity.Hostname = *hostname
	plan.Localization = LocalizationPlan{Locale: *locale, Keymap: *keymap, Timezone: *timezone}
	if err := applyNetwork(&plan, *networkMode, *networkInterface, *address, *gateway, *dns); err != nil {
		fatalFlag(err)
	}
	if err := applySource(&plan, *sourceType, *sourceLocation); err != nil {
		fatalFlag(err)
	}
	plan.Source.VerifyKey = *verifyKey
	if *runtimeName != "" {
		if err := applyRuntime(&plan, *runtimeName); err != nil {
			fatalFlag(err)
		}
	}
	requestedAI := *aiMode
	if requestedAI == "profile-default" {
		requestedAI = plan.AI.Mode
	}
	if err := applyAI(&plan, requestedAI, *aiEndpoint); err != nil {
		fatalFlag(err)
	}
	if *packageGroups != "" {
		for _, groupID := range strings.Split(*packageGroups, ",") {
			if err := applyPackageGroup(&plan, strings.TrimSpace(groupID), true); err != nil {
				fatalFlag(err)
			}
		}
	}
	plan.Artifacts.RuntimePlan = *planPath
	tui := &TUI{
		Plan:     plan,
		PlanPath: *planPath,
		In:       os.Stdin,
		Out:      os.Stdout,
		ASCII:    *asciiMode,
	}

	if *renderOnly {
		tui.Render()
		return
	}
	if *writeOnly {
		for _, check := range PlanChecks(plan) {
			if check.State == "BLOCK" {
				fatalFlag(fmt.Errorf("%s: %s", check.Name, check.Summary))
			}
		}
		plan.Artifacts.RuntimePlan = *planPath
		if err := WritePlanFile(*planPath, plan); err != nil {
			fmt.Fprintln(os.Stderr, "error:", err)
			os.Exit(1)
		}
		fmt.Println("wrote", *planPath)
		return
	}
	if *fullscreen {
		if err := tui.RunFullscreen(); err != nil {
			fmt.Fprintln(os.Stderr, "error:", err)
			os.Exit(1)
		}
		return
	}

	if err := tui.Run(); err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}

func fatalFlag(err error) {
	fmt.Fprintln(os.Stderr, "error:", err)
	os.Exit(2)
}

func usage() {
	fmt.Println("kiki-installer-tui - KIKI Stage 3 install plan TUI (v" + appVersion + ")")
	fmt.Println()
	fmt.Println("Usage:")
	fmt.Println("  kiki-installer-tui --fullscreen [--plan /run/kiki/install-plan.yaml]")
	fmt.Println("  kiki-installer-tui [--plan /run/kiki/install-plan.yaml] [--profile minimal-systemd|server-core|desktop-gnome|kiki-kube-bootstrap|kiki-kube-control|kiki-kube-compute]")
	fmt.Println("  kiki-installer-tui --render")
	fmt.Println("  kiki-installer-tui --write --plan ./install-plan.yaml [--disk /dev/sda] [--locale ko_KR.UTF-8] [--timezone Asia/Seoul]")
	fmt.Println("  kiki-installer-tui --write --mode unattended --profile server-core --ai local --source local")
	fmt.Println("  kiki-installer-tui --write --profile minimal-systemd --groups development,container-containerd")
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
			PartitionTable: "gpt",
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
		Localization: LocalizationPlan{
			Locale:   "ko_KR.UTF-8",
			Keymap:   "kr",
			Timezone: "Asia/Seoul",
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
			Groups:               []string{"minimal", "ai-console"},
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
		AI: AIPlan{
			Mode:            "local",
			Endpoint:        "http://127.0.0.1:8080/v1/chat/completions",
			Model:           "kiki-ops",
			ConsoleTTY:      "tty1",
			RequireApproval: true,
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

var containerdRuntimePackages = []string{
	"runc",
	"containerd",
	"kube-node-config-containerd",
}

var kubeNodeServices = []string{
	"crio.service",
	"kubelet.service",
	"chronyd.service",
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
	plan.Services.Disable = nil
	plan.Packages.Profile = normalized
	plan.Packages.Groups = []string{"minimal"}
	if definition, ok := catalogProfiles[normalized]; ok {
		plan.Packages.Groups = appendUnique(plan.Packages.Groups, definition.Groups...)
	}
	plan.Packages.Selected = append([]string{}, minimalSystemdPackages...)
	plan.Services.Enable = append([]string{}, minimalSystemdServices...)
	plan.Services.DefaultTarget = "multi-user.target"
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

	if normalized == "server-core" {
		plan.Packages.Groups = appendUnique(plan.Packages.Groups, "server")
		plan.Packages.Selected = appendUnique(plan.Packages.Selected, serverCorePackages...)
		plan.Services.Enable = appendUnique(plan.Services.Enable, serverCoreServices...)
		plan.Firewall.Firewalld = true
	}

	if isKubernetesProfile(normalized) {
		plan.Packages.Groups = appendUnique(plan.Packages.Groups, "kubernetes-node")
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
	rebuildCatalogGroups(plan)
	_ = applyAI(plan, plan.AI.Mode, plan.AI.Endpoint)
	if normalized == "desktop-gnome" {
		_ = applyPackageGroup(plan, "desktop-gnome", true)
	}
}

func applyContainerRuntime(plan *InstallPlan, runtime string) {
	plan.Packages.Selected = removeItems(plan.Packages.Selected, crioRuntimePackages...)
	plan.Packages.Selected = removeItems(plan.Packages.Selected, containerdRuntimePackages...)
	plan.Packages.Selected = removeItems(plan.Packages.Selected, containerdStandalonePackages...)
	plan.Services.Enable = removeItems(plan.Services.Enable, "crio.service", "containerd.service")
	plan.Packages.Groups = removeItems(plan.Packages.Groups, "container-crio", "container-containerd")

	if runtime == "containerd" {
		plan.Packages.Groups = appendUnique(plan.Packages.Groups, "container-containerd")
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
	plan.Packages.Groups = appendUnique(plan.Packages.Groups, "container-crio")
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

func applyDisk(plan *InstallPlan, disk string) error {
	disk = strings.TrimSpace(disk)
	if disk == "" || !strings.HasPrefix(disk, "/dev/") || isPartitionPath(disk) {
		return fmt.Errorf("target disk must be a whole /dev device, not %q", disk)
	}
	plan.Target.Disk = disk
	plan.Target.Filesystems.ESP.Path = partitionPath(disk, 1)
	if plan.Target.Filesystems.Swap.Enabled {
		plan.Target.Filesystems.Swap.Path = partitionPath(disk, 2)
		plan.Target.Filesystems.Root.Path = partitionPath(disk, 3)
	} else {
		plan.Target.Filesystems.Swap.Path = ""
		plan.Target.Filesystems.Root.Path = partitionPath(disk, 2)
	}
	plan.Boot.Root = plan.Target.Filesystems.Root.Path
	return nil
}

func applySwap(plan *InstallPlan, mode string) error {
	if mode != "on" && mode != "off" {
		return fmt.Errorf("swap must be auto, on, or off")
	}
	plan.Target.Filesystems.Swap.Enabled = mode == "on"
	if mode == "on" {
		plan.Target.Filesystems.Swap.Policy = "system"
		plan.Runtime.SwapPolicy = "system"
	} else if isKubernetesProfile(plan.Packages.Profile) {
		plan.Target.Filesystems.Swap.Policy = "kubernetes-off"
		plan.Runtime.SwapPolicy = "kubernetes-off"
	} else {
		plan.Target.Filesystems.Swap.Policy = "disabled"
		plan.Runtime.SwapPolicy = "disabled"
	}
	return nil
}

func applyNetwork(plan *InstallPlan, mode, interfaceMatch, address, gateway, dns string) error {
	if mode != "dhcp" && mode != "static" && mode != "off" {
		return fmt.Errorf("network must be dhcp, static, or off")
	}
	if mode == "static" && strings.TrimSpace(address) == "" {
		return fmt.Errorf("static network requires --address")
	}
	plan.Network.Mode = mode
	plan.Network.InterfaceMatch = strings.TrimSpace(interfaceMatch)
	plan.Network.DHCP4 = mode == "dhcp"
	plan.Network.IPv6AcceptRA = mode == "dhcp"
	plan.Network.Address = ""
	plan.Network.Gateway = ""
	plan.Network.DNS = ""
	if mode != "off" {
		plan.Network.DNS = strings.ReplaceAll(strings.TrimSpace(dns), ",", " ")
	}
	if mode == "static" {
		plan.Network.Address = strings.TrimSpace(address)
		plan.Network.Gateway = strings.TrimSpace(gateway)
	}
	return nil
}

func applySource(plan *InstallPlan, sourceType, location string) error {
	switch strings.TrimSpace(sourceType) {
	case "local":
		setLocalSource(plan, location)
		return nil
	case "remote":
		return setRemoteSource(plan, location)
	case "mirror":
		return setMirrorSource(plan, location)
	default:
		return fmt.Errorf("source must be local, remote, or mirror")
	}
}

func applyRuntime(plan *InstallPlan, runtime string) error {
	runtime = strings.TrimSpace(runtime)
	if runtime == "cri-o" {
		runtime = "crio"
	}
	if runtime != "none" && runtime != "crio" && runtime != "containerd" {
		return fmt.Errorf("runtime must be none, crio, or containerd")
	}
	if runtime == "none" {
		if isKubernetesProfile(plan.Packages.Profile) {
			return fmt.Errorf("Kubernetes profiles require crio or containerd")
		}
		plan.Runtime.ContainerRuntime = "none"
		plan.Packages.Groups = removeItems(plan.Packages.Groups, "container-crio", "container-containerd")
		plan.Packages.Selected = removeItems(plan.Packages.Selected, append(append(append([]string{}, kubernetesCommonPackages...), crioRuntimePackages...), append(containerdRuntimePackages, containerdStandalonePackages...)...)...)
		plan.Services.Enable = removeItems(plan.Services.Enable, append(append([]string{}, kubeNodeServices...), containerdServices...)...)
		return nil
	}
	if runtime == "crio" {
		applyContainerRuntime(plan, "cri-o")
	} else {
		applyContainerRuntime(plan, runtime)
	}
	return nil
}

func applyAI(plan *InstallPlan, mode, endpoint string) error {
	if mode != "off" && contains(plan.Packages.Groups, "desktop-gnome") {
		return fmt.Errorf("GNOME uses the graphical login; disable desktop-gnome before enabling the tty1 AI console")
	}
	mode = strings.TrimSpace(mode)
	if mode != "local" && mode != "remote" && mode != "off" {
		return fmt.Errorf("AI mode must be local, remote, or off")
	}
	plan.AI.Mode = mode
	plan.AI.RequireApproval = true
	plan.AI.ConsoleTTY = "tty1"
	plan.Packages.Groups = removeItems(plan.Packages.Groups, "ai-console", "ai-console-remote")
	if mode == "local" {
		plan.Packages.Groups = appendUnique(plan.Packages.Groups, "ai-console")
		plan.AI.Endpoint = "http://127.0.0.1:8080/v1/chat/completions"
		plan.AI.Model = "kiki-ops"
		plan.Packages.Selected = appendUnique(plan.Packages.Selected, "llama-cpp", "kiki-ai-console", "kiki-kmscon")
		plan.Services.Enable = appendUnique(plan.Services.Enable, "kiki-llama-server.service", "kiki-ai-console-kmscon@tty1.service", "getty@tty2.service")
		plan.Services.Enable = removeItems(plan.Services.Enable, "getty@tty1.service", "kiki-ai-console@tty1.service")
	} else if mode == "remote" {
		if strings.TrimSpace(endpoint) == "" {
			return fmt.Errorf("remote AI mode requires --ai-endpoint or: ai remote <endpoint>")
		}
		if !strings.HasPrefix(endpoint, "http://") && !strings.HasPrefix(endpoint, "https://") {
			return fmt.Errorf("remote AI endpoint must use http:// or https://")
		}
		plan.AI.Endpoint = endpoint
		plan.Packages.Groups = appendUnique(plan.Packages.Groups, "ai-console-remote")
		plan.AI.Model = "kiki-ops"
		plan.Packages.Selected = appendUnique(plan.Packages.Selected, "kiki-ai-console", "kiki-kmscon")
		plan.Packages.Selected = removeItems(plan.Packages.Selected, "llama-cpp")
		plan.Services.Enable = removeItems(plan.Services.Enable, "kiki-llama-server.service", "getty@tty1.service", "kiki-ai-console@tty1.service")
		plan.Services.Enable = appendUnique(plan.Services.Enable, "kiki-ai-console-kmscon@tty1.service", "getty@tty2.service")
	} else {
		plan.AI.Endpoint = ""
		plan.AI.Model = ""
		plan.Packages.Selected = removeItems(plan.Packages.Selected, "llama-cpp", "kiki-ai-console", "kiki-kmscon")
		plan.Services.Enable = removeItems(plan.Services.Enable, "kiki-llama-server.service", "kiki-ai-console@tty1.service", "kiki-ai-console-kmscon@tty1.service")
		plan.Services.Enable = appendUnique(plan.Services.Enable, "getty@tty1.service", "getty@tty2.service")
	}
	if endpoint != "" && mode == "local" {
		plan.AI.Endpoint = endpoint
	}
	return nil
}

func applyPackageGroup(plan *InstallPlan, groupID string, enabled bool) error {
	groupID = strings.TrimSpace(groupID)
	if !contains(selectablePackageGroups, groupID) {
		return fmt.Errorf("unknown package group %q", groupID)
	}
	if !enabled && groupID == "minimal" {
		return fmt.Errorf("the minimal package group cannot be removed from an install plan")
	}
	if enabled {
		plan.Packages.Groups = appendUnique(plan.Packages.Groups, groupID)
	} else {
		plan.Packages.Groups = removeItems(plan.Packages.Groups, groupID)
	}

	switch groupID {
	case "ai-console":
		if enabled {
			return applyAI(plan, "local", "")
		}
		return applyAI(plan, "off", "")
	case "ai-console-remote":
		if enabled {
			return applyAI(plan, "remote", plan.AI.Endpoint)
		}
		return applyAI(plan, "off", "")
	case "container-containerd", "container-crio":
		if !enabled {
			return applyRuntime(plan, "none")
		}
		if groupID == "container-containerd" {
			return applyRuntime(plan, "containerd")
		}
		return applyRuntime(plan, "crio")
	}
	if enabled && groupID == "desktop-gnome" {
		_ = applyAI(plan, "off", "")
	}
	rebuildCatalogGroups(plan)
	plan.Firewall.Firewalld = contains(plan.Packages.Groups, "server") || (isKubernetesProfile(plan.Packages.Profile) && !isKubernetesComputeProfile(plan.Packages.Profile))
	return nil
}

// Recompute the union so removing a group cannot remove another group's packages.
func rebuildCatalogGroups(plan *InstallPlan) {
	var packages, enable, disable []string
	visited := map[string]bool{}
	target := "multi-user.target"
	var visit func(string)
	visit = func(id string) {
		if visited[id] {
			return
		}
		visited[id] = true
		g := catalogGroups[id]
		for _, dep := range g.Requires {
			visit(dep)
		}
		packages = appendUnique(packages, g.Packages...)
		enable = appendUnique(enable, g.Enable...)
		disable = appendUnique(disable, g.Disable...)
		if g.DefaultTarget != "" {
			target = g.DefaultTarget
		}
	}
	for _, id := range plan.Packages.Groups {
		visit(id)
	}
	if isKubernetesProfile(plan.Packages.Profile) && plan.Runtime.ContainerRuntime == "containerd" {
		packages = appendUnique(packages, "kube-node-config-containerd")
	}
	plan.Packages.Selected = packages
	plan.Services.Enable = removeItems(enable, disable...)
	plan.Services.Disable = disable
	plan.Services.DefaultTarget = target
}

var fullscreenMenuLabels = []string{
	"언어 / 키보드 / 시간대",
	"설치 디스크",
	"네트워크",
	"관리자 계정",
	"패키지 소스 / 신뢰",
	"설치 프로필",
	"컨테이너 런타임",
	"AI 관리 콘솔",
	"설치 계획 검토",
	"설치 계획 저장",
}

var fullscreenMenuLabelsASCII = []string{
	"Language / keymap / timezone",
	"Installation disk",
	"Network",
	"Administrator account",
	"Package source / trust",
	"Installation profile",
	"Container runtime",
	"AI management console",
	"Review install plan",
	"Save install plan",
}

func terminalAttributes(fd uintptr) (*syscall.Termios, error) {
	state := &syscall.Termios{}
	_, _, errno := syscall.Syscall6(syscall.SYS_IOCTL, fd, uintptr(syscall.TCGETS), uintptr(unsafe.Pointer(state)), 0, 0, 0)
	if errno != 0 {
		return nil, errno
	}
	return state, nil
}

func setTerminalAttributes(fd uintptr, state *syscall.Termios) error {
	_, _, errno := syscall.Syscall6(syscall.SYS_IOCTL, fd, uintptr(syscall.TCSETS), uintptr(unsafe.Pointer(state)), 0, 0, 0)
	if errno != 0 {
		return errno
	}
	return nil
}

func enableRawTerminal(fd uintptr) (*syscall.Termios, error) {
	original, err := terminalAttributes(fd)
	if err != nil {
		return nil, err
	}
	raw := *original
	raw.Iflag &^= syscall.IGNBRK | syscall.BRKINT | syscall.PARMRK | syscall.ISTRIP | syscall.INLCR | syscall.IGNCR | syscall.ICRNL | syscall.IXON
	raw.Oflag &^= syscall.OPOST
	raw.Lflag &^= syscall.ECHO | syscall.ECHONL | syscall.ICANON | syscall.ISIG | syscall.IEXTEN
	raw.Cflag &^= syscall.CSIZE | syscall.PARENB
	raw.Cflag |= syscall.CS8
	raw.Cc[syscall.VMIN] = 1
	raw.Cc[syscall.VTIME] = 0
	if err := setTerminalAttributes(fd, &raw); err != nil {
		return nil, err
	}
	return original, nil
}

func readFullscreenKey(reader io.Reader) (string, error) {
	var key [1]byte
	if _, err := io.ReadFull(reader, key[:]); err != nil {
		return "", err
	}
	if key[0] != 0x1b {
		return string(key[:]), nil
	}
	var sequence [2]byte
	if _, err := io.ReadFull(reader, sequence[:]); err != nil {
		return "escape", nil
	}
	if sequence[0] == '[' {
		switch sequence[1] {
		case 'A':
			return "up", nil
		case 'B':
			return "down", nil
		case 'C':
			return "right", nil
		case 'D':
			return "left", nil
		}
	}
	return "escape", nil
}

func readFullscreenCommand(reader io.Reader, writer io.Writer, ascii bool) (string, bool, error) {
	var command []byte
	if ascii {
		fmt.Fprint(writer, "\r\ncommand> ")
	} else {
		fmt.Fprint(writer, "\r\n명령> ")
	}
	for {
		var value [1]byte
		if _, err := io.ReadFull(reader, value[:]); err != nil {
			return "", false, err
		}
		switch value[0] {
		case '\r', '\n':
			fmt.Fprint(writer, "\r\n")
			return string(command), true, nil
		case 0x1b, 0x03:
			return "", false, nil
		case 0x7f, 0x08:
			if len(command) > 0 {
				command = command[:len(command)-1]
				fmt.Fprint(writer, "\b \b")
			}
		default:
			if value[0] >= 0x20 {
				command = append(command, value[0])
				_, _ = writer.Write(value[:])
			}
		}
	}
}

func lastFullscreenMessage(output string, ascii bool) string {
	lines := strings.Split(strings.TrimSpace(output), "\n")
	for index := len(lines) - 1; index >= 0; index-- {
		line := strings.TrimSpace(lines[index])
		if line != "" {
			return line
		}
	}
	if ascii {
		return "The setting was applied."
	}
	return "설정이 반영되었습니다."
}

func optionIndex(options []string, current string) int {
	for index, option := range options {
		if option == current {
			return index
		}
	}
	return 0
}

func readFullscreenValue(reader io.Reader, writer io.Writer, label, current string) (string, bool, error) {
	fmt.Fprintf(writer, "\r\n%s", label)
	if current != "" {
		fmt.Fprintf(writer, " [%s]", current)
	}
	fmt.Fprint(writer, ": ")
	var value []byte
	for {
		var input [1]byte
		if _, err := io.ReadFull(reader, input[:]); err != nil {
			return "", false, err
		}
		switch input[0] {
		case '\r', '\n':
			fmt.Fprint(writer, "\r\n")
			if len(value) == 0 {
				return current, true, nil
			}
			return string(value), true, nil
		case 0x1b, 0x03:
			return "", false, nil
		case 0x7f, 0x08:
			if len(value) > 0 {
				value = value[:len(value)-1]
				fmt.Fprint(writer, "\b \b")
			}
		default:
			if input[0] >= 0x20 {
				value = append(value, input[0])
				_, _ = writer.Write(input[:])
			}
		}
	}
}

func chooseFullscreenOption(reader io.Reader, writer io.Writer, title string, options []string, current string) (string, bool, error) {
	selected := optionIndex(options, current)
	for {
		fmt.Fprint(writer, "\x1b[2J\x1b[H")
		fmt.Fprintf(writer, "%s\r\n", title)
		fmt.Fprint(writer, "--------------------------------------------------------------------\r\n")
		for index, option := range options {
			prefix := "  "
			suffix := ""
			if index == selected {
				prefix = "\x1b[7m> "
				suffix = "\x1b[0m"
			}
			fmt.Fprintf(writer, "%s%2d. %s%s\r\n", prefix, index+1, option, suffix)
		}
		fmt.Fprint(writer, "\r\nUp/Down or j/k: move   Enter: apply   Esc: cancel\r\n")
		key, err := readFullscreenKey(reader)
		if err != nil {
			return "", false, err
		}
		switch key {
		case "up", "k", "K":
			selected = (selected + len(options) - 1) % len(options)
		case "down", "j", "J":
			selected = (selected + 1) % len(options)
		case "\r", "\n", "right", " ":
			return options[selected], true, nil
		case "escape", "c", "C", "q", "Q":
			return "", false, nil
		default:
			if len(key) == 1 && key[0] >= '1' && key[0] <= '9' {
				index := int(key[0] - '1')
				if index < len(options) {
					selected = index
				}
			}
		}
	}
}

var fullscreenProfiles = []string{
	"server-core",
	"minimal-systemd",
	"kiki-kube-bootstrap",
	"kiki-kube-bootstrap-containerd",
	"kiki-kube-control",
	"kiki-kube-control-containerd",
	"kiki-kube-compute",
	"kiki-kube-compute-containerd",
	"desktop-gnome",
}

func (t *TUI) editFullscreenItem(selected int) (string, bool, error) {
	cancelled := func() (string, bool, error) { return "Selection cancelled.", false, nil }
	choose := func(title string, options []string, current string) (string, bool, error) {
		return chooseFullscreenOption(t.In, t.Out, title, options, current)
	}
	prompt := func(label, current string) (string, bool, error) {
		return readFullscreenValue(t.In, t.Out, label, current)
	}

	switch selected {
	case 0:
		preset, accepted, err := choose("Language / keymap / timezone", []string{"Korean (ko_KR.UTF-8 / kr / Asia/Seoul)", "English (en_US.UTF-8 / us / UTC)"}, "Korean (ko_KR.UTF-8 / kr / Asia/Seoul)")
		if err != nil || !accepted {
			if err != nil {
				return "", false, err
			}
			return cancelled()
		}
		if strings.HasPrefix(preset, "English") {
			t.Plan.Localization = LocalizationPlan{Locale: "en_US.UTF-8", Keymap: "us", Timezone: "UTC"}
		} else {
			t.Plan.Localization = LocalizationPlan{Locale: "ko_KR.UTF-8", Keymap: "kr", Timezone: "Asia/Seoul"}
		}
		return "Localization updated.", false, nil
	case 1:
		disk, accepted, err := prompt("Whole installation disk", t.Plan.Target.Disk)
		if err != nil || !accepted {
			if err != nil {
				return "", false, err
			}
			return cancelled()
		}
		if err := applyDisk(&t.Plan, strings.TrimSpace(disk)); err != nil {
			return "", false, err
		}
		return "Installation disk updated.", false, nil
	case 2:
		mode, accepted, err := choose("Network mode", []string{"dhcp", "static", "off"}, t.Plan.Network.Mode)
		if err != nil || !accepted {
			if err != nil {
				return "", false, err
			}
			return cancelled()
		}
		t.Plan.Network.Mode = mode
		t.Plan.Network.DHCP4 = mode == "dhcp"
		t.Plan.Network.IPv6AcceptRA = mode == "dhcp"
		if mode == "off" {
			t.Plan.Network.Address, t.Plan.Network.Gateway, t.Plan.Network.DNS = "", "", ""
			return "Network disabled.", false, nil
		}
		match, accepted, err := prompt("Interface match", t.Plan.Network.InterfaceMatch)
		if err != nil || !accepted {
			if err != nil {
				return "", false, err
			}
			return cancelled()
		}
		t.Plan.Network.InterfaceMatch = strings.TrimSpace(match)
		if mode == "static" {
			address, ok, inputErr := prompt("Address/CIDR", t.Plan.Network.Address)
			if inputErr != nil || !ok {
				if inputErr != nil {
					return "", false, inputErr
				}
				return cancelled()
			}
			if strings.TrimSpace(address) == "" {
				return "", false, fmt.Errorf("static network requires an address/CIDR")
			}
			gateway, ok, inputErr := prompt("Gateway (blank for none)", t.Plan.Network.Gateway)
			if inputErr != nil || !ok {
				if inputErr != nil {
					return "", false, inputErr
				}
				return cancelled()
			}
			dns, ok, inputErr := prompt("DNS servers", t.Plan.Network.DNS)
			if inputErr != nil || !ok {
				if inputErr != nil {
					return "", false, inputErr
				}
				return cancelled()
			}
			t.Plan.Network.Address = strings.TrimSpace(address)
			t.Plan.Network.Gateway = strings.TrimSpace(gateway)
			t.Plan.Network.DNS = strings.ReplaceAll(strings.TrimSpace(dns), ",", " ")
		} else {
			t.Plan.Network.Address, t.Plan.Network.Gateway, t.Plan.Network.DNS = "", "", ""
		}
		return "Network settings updated.", false, nil
	case 3:
		user, accepted, err := prompt("Administrator user", t.Plan.Users.Admin.Name)
		if err != nil || !accepted {
			if err != nil {
				return "", false, err
			}
			return cancelled()
		}
		if !validUserName(strings.TrimSpace(user)) {
			return "", false, fmt.Errorf("invalid user name: %s", user)
		}
		hostname, accepted, err := prompt("Hostname", t.Plan.Identity.Hostname)
		if err != nil || !accepted {
			if err != nil {
				return "", false, err
			}
			return cancelled()
		}
		t.Plan.Users.Admin.Name = strings.TrimSpace(user)
		t.Plan.Users.Admin.PrimaryGroup = strings.TrimSpace(user)
		t.Plan.Identity.Hostname = strings.TrimSpace(hostname)
		return "Administrator account updated.", false, nil
	case 4:
		sourceType, accepted, err := choose("Package source", []string{"local", "remote", "mirror"}, t.Plan.Source.Type)
		if err != nil || !accepted {
			if err != nil {
				return "", false, err
			}
			return cancelled()
		}
		current := t.Plan.Source.MediaRoot
		if sourceType == "remote" {
			current = t.Plan.Source.RepoURL
		}
		location, accepted, err := prompt("Source location", current)
		if err != nil || !accepted {
			if err != nil {
				return "", false, err
			}
			return cancelled()
		}
		switch sourceType {
		case "local":
			setLocalSource(&t.Plan, strings.TrimSpace(location))
		case "remote":
			if err := setRemoteSource(&t.Plan, strings.TrimSpace(location)); err != nil {
				return "", false, err
			}
			key, ok, inputErr := prompt("Repository verification key", t.Plan.Source.VerifyKey)
			if inputErr != nil || !ok {
				if inputErr != nil {
					return "", false, inputErr
				}
				return cancelled()
			}
			if strings.TrimSpace(key) == "" {
				return "", false, fmt.Errorf("remote source requires a verification key")
			}
			t.Plan.Source.VerifyKey = strings.TrimSpace(key)
		case "mirror":
			if err := setMirrorSource(&t.Plan, strings.TrimSpace(location)); err != nil {
				return "", false, err
			}
		}
		return "Package source updated.", false, nil
	case 5:
		profile, accepted, err := choose("Installation profile", fullscreenProfiles, t.Plan.Packages.Profile)
		if err != nil || !accepted {
			if err != nil {
				return "", false, err
			}
			return cancelled()
		}
		ApplyProfile(&t.Plan, profile)
		return "Profile applied: " + profile, false, nil
	case 6:
		current := strings.ReplaceAll(t.Plan.Runtime.ContainerRuntime, "cri-o", "crio")
		runtime, accepted, err := choose("Container runtime", []string{"none", "crio", "containerd"}, current)
		if err != nil || !accepted {
			if err != nil {
				return "", false, err
			}
			return cancelled()
		}
		if err := applyRuntime(&t.Plan, runtime); err != nil {
			return "", false, err
		}
		return "Container runtime updated: " + runtime, false, nil
	case 7:
		mode, accepted, err := choose("AI management console", []string{"local", "remote", "off"}, t.Plan.AI.Mode)
		if err != nil || !accepted {
			if err != nil {
				return "", false, err
			}
			return cancelled()
		}
		endpoint := ""
		if mode == "remote" {
			endpoint, accepted, err = prompt("OpenAI-compatible endpoint", t.Plan.AI.Endpoint)
			if err != nil || !accepted {
				if err != nil {
					return "", false, err
				}
				return cancelled()
			}
		}
		if err := applyAI(&t.Plan, mode, strings.TrimSpace(endpoint)); err != nil {
			return "", false, err
		}
		return "AI mode updated: " + mode, false, nil
	case 8:
		t.Reviewed = true
		if ReviewReady(t.Plan) {
			return "Review complete. The install plan is ready to save.", false, nil
		}
		return "Review blocked. Resolve the items marked BLOCK.", false, nil
	case 9:
		t.Reviewed = true
		if !ReviewReady(t.Plan) {
			return "Install plan is blocked and was not saved.", false, nil
		}
		return t.startFullscreenInstall()
	default:
		return "", false, fmt.Errorf("unknown full-screen menu item %d", selected)
	}
}

func (t *TUI) fullscreenRows() []Check {
	dashboard := t.dashboardRows()
	rows := append([]Check{}, dashboard[:8]...)
	rows = append(rows, dashboard[9])
	start := Check{Name: "Save", State: "BLOCK", Summary: "차단 항목을 먼저 해결하십시오"}
	if t.ASCII {
		start.Summary = "resolve blocking items first"
	}
	if ReviewReady(t.Plan) {
		start.State = "OK"
		start.Summary = t.PlanPath
	}
	return append(rows, start)
}

func (t *TUI) RenderFullscreen(selected int, message string) {
	if t.Out == nil {
		t.Out = io.Discard
	}
	fmt.Fprint(t.Out, "\x1b[2J\x1b[H")
	labels := fullscreenMenuLabels
	if t.ASCII {
		labels = fullscreenMenuLabelsASCII
		fmt.Fprint(t.Out, "KIKI OS Scratch Pad - TUI fallback\r\n")
		fmt.Fprint(t.Out, "--------------------------------------------------------------------\r\n")
		fmt.Fprintf(t.Out, "Install plan: %s\r\n\r\n", t.PlanPath)
	} else {
		fmt.Fprint(t.Out, "KIKI OS 설치기 — 전체 화면 TUI\r\n")
		fmt.Fprint(t.Out, "────────────────────────────────────────────────────────────────────\r\n")
		fmt.Fprintf(t.Out, "설치 계획: %s\r\n\r\n", t.PlanPath)
	}
	for index, row := range t.fullscreenRows() {
		prefix := "  "
		suffix := ""
		if index == selected {
			prefix = "\x1b[7m> "
			suffix = "\x1b[0m"
		}
		fmt.Fprintf(t.Out, "%s%2d. %-30s [%s] %s%s\r\n", prefix, index+1, labels[index], dashboardToken(row.State), row.Summary, suffix)
	}
	if t.ASCII {
		fmt.Fprint(t.Out, "\r\nUp/Down or j/k: move   Enter: select   : command   c/q: CLI fallback\r\n")
		fmt.Fprint(t.Out, "Example: disk /dev/sda | profile server-core | group add development | ai local\r\n")
	} else {
		fmt.Fprint(t.Out, "\r\n↑/↓ 또는 j/k: 이동   Enter: 선택   : 명령 입력   c/q: CLI로 전환\r\n")
		fmt.Fprint(t.Out, "명령 예: disk /dev/sda · profile server-core · group add development · ai local\r\n")
	}
	if message != "" {
		if t.ASCII {
			fmt.Fprintf(t.Out, "\r\nStatus: %s\r\n", message)
		} else {
			fmt.Fprintf(t.Out, "\r\n상태: %s\r\n", message)
		}
	}
}

func (t *TUI) RunFullscreen() error {
	if t.In == nil {
		t.In = os.Stdin
	}
	if t.Out == nil {
		t.Out = os.Stdout
	}
	input, ok := t.In.(*os.File)
	if !ok {
		return fmt.Errorf("full-screen TUI input is not a terminal file")
	}
	original, err := enableRawTerminal(input.Fd())
	if err != nil {
		return fmt.Errorf("full-screen TUI requires a terminal: %w", err)
	}
	fmt.Fprint(t.Out, "\x1b[?1049h\x1b[?25l")
	defer func() {
		_ = setTerminalAttributes(input.Fd(), original)
		fmt.Fprint(t.Out, "\x1b[?25h\x1b[?1049l")
	}()

	selected := 0
	message := "GUI 다음 단계입니다. 설정 후 계획을 저장하거나 CLI로 전환할 수 있습니다."
	if t.ASCII {
		message = "GUI fallback active. Save the plan or switch to the CLI."
	}
	for {
		t.RenderFullscreen(selected, message)
		key, err := readFullscreenKey(t.In)
		if err != nil {
			return err
		}
		switch key {
		case "up", "k", "K":
			selected = (selected + len(fullscreenMenuLabels) - 1) % len(fullscreenMenuLabels)
		case "down", "j", "J":
			selected = (selected + 1) % len(fullscreenMenuLabels)
		case "1", "2", "3", "4", "5", "6", "7", "8", "9":
			selected = int(key[0] - '1')
		case "0":
			selected = 9
		case "c", "C", "q", "Q", "\x03":
			return nil
		case ":":
			command, accepted, err := readFullscreenCommand(t.In, t.Out, t.ASCII)
			if err != nil {
				return err
			}
			if !accepted {
				if t.ASCII {
					message = "Command input cancelled."
				} else {
					message = "명령 입력을 취소했습니다."
				}
				continue
			}
			var output bytes.Buffer
			if strings.TrimSpace(command) == "install" || strings.TrimSpace(command) == "start" || strings.TrimSpace(command) == "10" {
				itemMessage, done, installErr := t.startFullscreenInstall()
				if done {
					return installErr
				}
				if installErr != nil {
					message = "Error: " + installErr.Error()
				} else {
					message = itemMessage
				}
				continue
			}
			oldOut := t.Out
			t.Out = &output
			done, applyErr := t.ApplyCommand(command)
			t.Out = oldOut
			if applyErr != nil {
				message = "Error: " + applyErr.Error()
			} else if done {
				return nil
			} else {
				message = lastFullscreenMessage(output.String(), t.ASCII)
			}
		case "\r", "\n", "right", " ":
			itemMessage, done, applyErr := t.editFullscreenItem(selected)
			if applyErr != nil {
				message = "Error: " + applyErr.Error()
			} else if done {
				return nil
			} else {
				message = itemMessage
			}
		case "?":
			if t.ASCII {
				message = "Press Enter to inspect an item, or type a CLI command after colon (:)."
			} else {
				message = "Enter로 항목을 확인하고, 콜론(:) 뒤에 기존 CLI 설정 명령을 입력합니다."
			}
		}
	}
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
		fmt.Fprintln(t.Out, "Language:", dashboardLocalizationSummary(t.Plan))
		fmt.Fprintln(t.Out, "Use: locale ko_KR.UTF-8, keymap kr, timezone Asia/Seoul")
	case "2":
		fmt.Fprintln(t.Out, "Disk:", dashboardDiskSummary(t.Plan))
		fmt.Fprintln(t.Out, "Use: disk /dev/sda")
	case "3":
		fmt.Fprintln(t.Out, "Network:", dashboardNetworkSummary(t.Plan))
		fmt.Fprintln(t.Out, "Use: network dhcp [en* eth*], network static 192.168.122.50/24 192.168.122.1 1.1.1.1 [en* eth*], or network off")
	case "4":
		fmt.Fprintln(t.Out, "Account:", dashboardAccountSummary(t.Plan))
		fmt.Fprintln(t.Out, "Use: user kiki and hostname localhost.localdomain")
	case "5":
		fmt.Fprintln(t.Out, "Source:", dashboardSourceSummary(t.Plan))
		fmt.Fprintln(t.Out, "Use: source local|remote|mirror ... and verify-key /path/to/key")
	case "6":
		fmt.Fprintln(t.Out, "Profile:", t.Plan.Packages.Profile)
		fmt.Fprintln(t.Out, "Groups:", strings.Join(t.Plan.Packages.Groups, ", "))
		fmt.Fprintln(t.Out, "Use: profile minimal-systemd|server-core|desktop-gnome|kiki-kube-bootstrap|kiki-kube-control|kiki-kube-compute")
		fmt.Fprintln(t.Out, "     add -containerd to a Kubernetes profile to use containerd by default")
		fmt.Fprintln(t.Out, "     group add|remove server|development|container-containerd|container-crio")
	case "7":
		fmt.Fprintln(t.Out, "Runtime:", t.Plan.Runtime.ContainerRuntime)
		fmt.Fprintln(t.Out, "Use: runtime none, runtime crio, or runtime containerd")
	case "8":
		fmt.Fprintln(t.Out, "AI:", dashboardAISummary(t.Plan))
		fmt.Fprintln(t.Out, "Use: ai local, ai remote https://endpoint/v1/chat/completions, or ai off")
	case "9":
		t.Reviewed = true
		t.Render()
		fmt.Fprintln(t.Out)
		if ReviewReady(t.Plan) {
			fmt.Fprintln(t.Out, "Review: ready to write install plan.")
		} else {
			fmt.Fprintln(t.Out, "Review: blocked. Fix BLOCK items before install.")
		}
	case "10", "start", "install":
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
		fmt.Fprintln(t.Out, "Stage-1 installer and Stage-3 executor can consume this install plan.")
	case "profile":
		if len(fields) != 2 {
			return false, fmt.Errorf("usage: profile minimal-systemd|server-core|desktop-gnome|kiki-kube-bootstrap|kiki-kube-control|kiki-kube-compute[-containerd]")
		}
		ApplyProfile(&t.Plan, fields[1])
		t.Render()
	case "group":
		if len(fields) != 3 || (fields[1] != "add" && fields[1] != "remove") {
			return false, fmt.Errorf("usage: group add|remove <group-id>")
		}
		if err := applyPackageGroup(&t.Plan, fields[2], fields[1] == "add"); err != nil {
			return false, err
		}
		t.Render()
	case "disk":
		if len(fields) != 2 {
			return false, fmt.Errorf("usage: disk /dev/sda")
		}
		if isPartitionPath(fields[1]) {
			return false, fmt.Errorf("target disk must be a whole disk, not %s", fields[1])
		}
		if err := applyDisk(&t.Plan, fields[1]); err != nil {
			return false, err
		}
		t.Render()
	case "locale", "keymap", "timezone":
		if len(fields) != 2 {
			return false, fmt.Errorf("usage: %s <value>", fields[0])
		}
		switch fields[0] {
		case "locale":
			t.Plan.Localization.Locale = fields[1]
		case "keymap":
			t.Plan.Localization.Keymap = fields[1]
		case "timezone":
			t.Plan.Localization.Timezone = fields[1]
		}
		t.Render()
	case "swap":
		if len(fields) != 2 || (fields[1] != "on" && fields[1] != "off") {
			return false, fmt.Errorf("usage: swap on|off")
		}
		if err := applySwap(&t.Plan, fields[1]); err != nil {
			return false, err
		}
		if err := applyDisk(&t.Plan, t.Plan.Target.Disk); err != nil {
			return false, err
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
	case "ai":
		if len(fields) < 2 || len(fields) > 3 {
			return false, fmt.Errorf("usage: ai local|off | ai remote <endpoint>")
		}
		endpoint := ""
		if len(fields) == 3 {
			endpoint = fields[2]
		}
		if err := applyAI(&t.Plan, fields[1], endpoint); err != nil {
			return false, err
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
		if err := applyRuntime(&t.Plan, fields[1]); err != nil {
			return false, err
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
		fmt.Fprintln(t.Out, "Shell handoff is provided by the stage-1 C installer. This compatibility CLI keeps the install plan in process.")
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
	fmt.Fprintln(t.Out, "KIKI OS Install Plan CLI")
	fmt.Fprintln(t.Out, "Line-command compatibility mode; use --fullscreen for the keyboard-driven TUI")
	fmt.Fprintln(t.Out)
	fmt.Fprintln(t.Out, "Install Plan:", t.PlanPath)
	fmt.Fprintln(t.Out)
	for _, check := range t.dashboardRows() {
		fmt.Fprintf(t.Out, "[%s] %-10s %s\n", dashboardToken(check.State), check.Name, check.Summary)
	}
	fmt.Fprintln(t.Out)
	fmt.Fprintln(t.Out, "1) Language, keyboard, and timezone")
	fmt.Fprintln(t.Out, "2) Disk")
	fmt.Fprintln(t.Out, "3) Network")
	fmt.Fprintln(t.Out, "4) Account")
	fmt.Fprintln(t.Out, "5) Package source and trust")
	fmt.Fprintln(t.Out, "6) Profile")
	fmt.Fprintln(t.Out, "7) Runtime")
	fmt.Fprintln(t.Out, "8) AI agent")
	fmt.Fprintln(t.Out, "9) Review install plan")
	fmt.Fprintln(t.Out, "10) Start install")
	fmt.Fprintln(t.Out, "s) Shell")
	fmt.Fprintln(t.Out, "q) Power off")
}

func (t *TUI) dashboardRows() []Check {
	localization := checkLocalization(t.Plan)
	localization.Summary = dashboardLocalizationSummary(t.Plan)
	disk := checkDisk(t.Plan)
	disk.Summary = dashboardDiskSummary(t.Plan)
	if disk.State == "OK" && t.Plan.Target.Partitioning == "auto-whole-disk" {
		disk.State = "WARN"
	}
	network := checkNetwork(t.Plan)
	network.Summary = dashboardNetworkSummary(t.Plan)
	account := checkAccount(t.Plan)
	account.Summary = dashboardAccountSummary(t.Plan)
	source := checkSource(t.Plan)
	source.Summary = dashboardSourceSummary(t.Plan)
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
	ai := checkAI(t.Plan)
	ai.Summary = dashboardAISummary(t.Plan)
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
	init := Check{Name: "Init", State: "OK", Summary: "initramfs /init mounts root and execs /usr/lib/systemd/systemd"}
	return []Check{localization, disk, network, account, source, profile, runtime, ai, init, review}
}

func dashboardLocalizationSummary(plan InstallPlan) string {
	return fmt.Sprintf("%s, keymap %s, %s", plan.Localization.Locale, plan.Localization.Keymap, plan.Localization.Timezone)
}

func dashboardSourceSummary(plan InstallPlan) string {
	trust := "unsigned"
	if plan.Source.VerifyKey != "" {
		trust = "signature required"
	}
	return fmt.Sprintf("%s, %s", plan.Source.Type, trust)
}

func dashboardAISummary(plan InstallPlan) string {
	if plan.AI.Mode == "off" {
		return "disabled"
	}
	return fmt.Sprintf("%s, %s on %s, approval required", plan.AI.Mode, plan.AI.Model, plan.AI.ConsoleTTY)
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
	fmt.Fprintln(w, "  profile minimal-systemd|server-core|desktop-gnome|kiki-kube-bootstrap|kiki-kube-control|kiki-kube-compute")
	fmt.Fprintln(w, "  profile kiki-kube-bootstrap-containerd|kiki-kube-control-containerd|kiki-kube-compute-containerd")
	fmt.Fprintln(w, "  group add|remove minimal|server|ai-console|container-containerd|container-crio|kubernetes-node|development")
	fmt.Fprintln(w, "    legacy aliases: kiki-kube-controller -> kiki-kube-control, kiki-kube-node -> kiki-kube-compute")
	fmt.Fprintln(w, "  disk /dev/sda")
	fmt.Fprintln(w, "  locale ko_KR.UTF-8")
	fmt.Fprintln(w, "  keymap kr")
	fmt.Fprintln(w, "  timezone Asia/Seoul")
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
	fmt.Fprintln(w, "  ai local|off")
	fmt.Fprintln(w, "  ai remote https://endpoint.example/v1/chat/completions")
	fmt.Fprintln(w, "  firewalld on|off")
	fmt.Fprintln(w, "  review")
	fmt.Fprintln(w, "  write [path]")
	fmt.Fprintln(w, "  quit")
}

func PlanChecks(plan InstallPlan) []Check {
	checks := []Check{
		checkLocalization(plan),
		checkDisk(plan),
		checkNetwork(plan),
		checkAccount(plan),
		checkSource(plan),
		checkProfile(plan),
		checkRuntime(plan),
		checkAI(plan),
		checkInit(plan),
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

func checkLocalization(plan InstallPlan) Check {
	if plan.Localization.Locale == "" || plan.Localization.Keymap == "" || plan.Localization.Timezone == "" {
		return Check{Name: "Language", State: "BLOCK", Summary: "locale, keymap, and timezone are required"}
	}
	if strings.ContainsAny(plan.Localization.Locale+plan.Localization.Keymap+plan.Localization.Timezone, "\r\n\x00") {
		return Check{Name: "Language", State: "BLOCK", Summary: "localization values contain invalid characters"}
	}
	if strings.HasPrefix(plan.Localization.Timezone, "/") || strings.Contains(plan.Localization.Timezone, "..") {
		return Check{Name: "Language", State: "BLOCK", Summary: "timezone must be a relative IANA name"}
	}
	return Check{Name: "Language", State: "OK", Summary: dashboardLocalizationSummary(plan)}
}

func checkSource(plan InstallPlan) Check {
	if plan.Source.RepoIndex == "" {
		return Check{Name: "Source", State: "BLOCK", Summary: "repository index is required"}
	}
	if (plan.Source.Type == "remote-repository" || (plan.Source.Type == "mirror" && strings.HasPrefix(plan.Source.RepoURL, "http"))) && plan.Source.VerifyKey == "" {
		return Check{Name: "Source", State: "BLOCK", Summary: "remote repository requires a verification key"}
	}
	return Check{Name: "Source", State: "OK", Summary: dashboardSourceSummary(plan)}
}

func checkAI(plan InstallPlan) Check {
	if plan.AI.Mode != "local" && plan.AI.Mode != "remote" && plan.AI.Mode != "off" {
		return Check{Name: "AI", State: "BLOCK", Summary: "AI mode must be local, remote, or off"}
	}
	if plan.AI.Mode != "off" && (!plan.AI.RequireApproval || plan.AI.Endpoint == "" || plan.AI.ConsoleTTY == "") {
		return Check{Name: "AI", State: "BLOCK", Summary: "AI endpoint, console TTY, and command approval are required"}
	}
	return Check{Name: "AI", State: "OK", Summary: dashboardAISummary(plan)}
}

func checkInit(plan InstallPlan) Check {
	if plan.Boot.Kernel == "" || plan.Boot.Initramfs == "" {
		return Check{Name: "Init", State: "BLOCK", Summary: "kernel and initramfs paths are required"}
	}
	if plan.Boot.Root == "" {
		return Check{Name: "Init", State: "BLOCK", Summary: "installed root device is required for systemd handoff"}
	}
	return Check{Name: "Init", State: "OK", Summary: "installed boot uses initramfs handoff to systemd PID 1"}
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
	if plan.Network.Mode != "off" {
		if strings.TrimSpace(plan.Network.InterfaceMatch) == "" || strings.ContainsAny(plan.Network.InterfaceMatch, "\r\n\x00=/") {
			return Check{Name: "Network", State: "BLOCK", Summary: "select a valid network device or name pattern"}
		}
		for _, server := range strings.Fields(plan.Network.DNS) {
			ip := net.ParseIP(server)
			if ip == nil || ip.IsUnspecified() || ip.IsMulticast() {
				return Check{Name: "Network", State: "BLOCK", Summary: "DNS servers must be valid unicast IP addresses"}
			}
		}
	}
	if plan.Network.Mode == "static" {
		ip, subnet, err := net.ParseCIDR(plan.Network.Address)
		if err != nil || ip.IsUnspecified() || ip.IsMulticast() {
			return Check{Name: "Network", State: "BLOCK", Summary: "static network mode requires a valid unicast address/prefix"}
		}
		if plan.Network.Gateway != "" {
			gateway := net.ParseIP(plan.Network.Gateway)
			if gateway == nil || gateway.IsUnspecified() || gateway.IsMulticast() ||
				(ip.To4() == nil) != (gateway.To4() == nil) {
				return Check{Name: "Network", State: "BLOCK", Summary: "gateway must be a unicast IP of the same address family"}
			}
			if !subnet.Contains(gateway) && !gateway.IsLinkLocalUnicast() {
				return Check{Name: "Network", State: "BLOCK", Summary: "gateway must be reachable in the configured subnet"}
			}
		}
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
	line("  localization:")
	line("    locale: %s", quoteYAML(plan.Localization.Locale))
	line("    keymap: %s", quoteYAML(plan.Localization.Keymap))
	line("    timezone: %s", quoteYAML(plan.Localization.Timezone))
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
	line("    groups:")
	writeStringList(bw, "      ", plan.Packages.Groups)
	line("    dependency_resolution: %t", plan.Packages.DependencyResolution)
	line("    selected:")
	writeStringList(bw, "      ", plan.Packages.Selected)
	line("  services:")
	line("    default_target: %s", quoteYAML(plan.Services.DefaultTarget))
	line("    enable:")
	writeStringList(bw, "      ", plan.Services.Enable)
	line("    disable:")
	writeStringList(bw, "      ", plan.Services.Disable)
	line("  boot:")
	line("    loader: %s", quoteYAML(plan.Boot.Loader))
	line("    kernel: %s", quoteYAML(plan.Boot.Kernel))
	line("    initramfs: %s", quoteYAML(plan.Boot.Initramfs))
	line("    root: %s", quoteYAML(plan.Boot.Root))
	line("  runtime:")
	line("    container_runtime: %s", quoteYAML(plan.Runtime.ContainerRuntime))
	line("    cgroup_driver: %s", quoteYAML(plan.Runtime.CgroupDriver))
	line("    swap_policy: %s", quoteYAML(plan.Runtime.SwapPolicy))
	line("  ai:")
	line("    mode: %s", quoteYAML(plan.AI.Mode))
	line("    endpoint: %s", quoteYAML(plan.AI.Endpoint))
	line("    model: %s", quoteYAML(plan.AI.Model))
	line("    console_tty: %s", quoteYAML(plan.AI.ConsoleTTY))
	line("    require_approval: %t", plan.AI.RequireApproval)
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
