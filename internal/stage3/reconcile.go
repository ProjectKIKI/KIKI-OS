package stage3

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
)

var caHashPattern = regexp.MustCompile(`^(?:sha256:)?[a-fA-F0-9]{64}$`)
var cniPackagePattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._+-]*$`)

type Runner interface {
	Run(context.Context, string, []string) error
}

type ExecRunner struct{}

func (ExecRunner) Run(ctx context.Context, name string, arguments []string) error {
	command := exec.CommandContext(ctx, name, arguments...)
	command.Stdout = os.Stdout
	command.Stderr = os.Stderr
	command.Stdin = os.Stdin
	return command.Run()
}

type ReconcileOptions struct {
	Root          string
	PlanPath      string
	KikiKubeadm   string
	Kubectl       string
	Ki2ctl        string
	Systemctl     string
	TokenFile     string
	NodeName      string
	Endpoint      string
	CACertHash    string
	DryRun        bool
	SkipPreflight bool
	CheckKubelet  bool
	Runner        Runner
}

type ReconcileResult struct {
	Role           string
	Action         string
	Command        []string
	CNICommand     []string
	CRI            string
	CNIReady       bool
	KubeadmSkipped bool
	KubeletReady   bool
}

func Reconcile(ctx context.Context, config Config, options ReconcileOptions) (ReconcileResult, error) {
	if options.Root == "" {
		options.Root = "/"
	}
	if options.PlanPath == "" {
		return ReconcileResult{}, errors.New("rendered stage3 plan path is required")
	}
	if options.KikiKubeadm == "" {
		options.KikiKubeadm = "/usr/bin/kiki-kubeadm"
	}
	if options.Kubectl == "" {
		options.Kubectl = "/usr/bin/kubectl"
	}
	if options.Ki2ctl == "" {
		options.Ki2ctl = "/usr/bin/ki2ctl"
	}
	if options.Systemctl == "" {
		options.Systemctl = "/usr/bin/systemctl"
	}
	if options.Runner == nil {
		options.Runner = ExecRunner{}
	}

	role, action, err := normalizeRoleAction(config.Kubernetes.Role, config.Kubernetes.Kubeadm.Action)
	if err != nil {
		return ReconcileResult{}, err
	}
	if action == "none" {
		return ReconcileResult{Role: role, Action: action}, nil
	}

	endpoint := firstNonEmpty(options.Endpoint, config.Kubernetes.Cluster.ControlPlaneEndpoint)
	caHash := firstNonEmpty(options.CACertHash, config.Kubernetes.Join.CACertHash)
	tokenFile := firstNonEmpty(options.TokenFile, config.Kubernetes.Join.TokenRef)
	if err := validateCNI(config); err != nil {
		return ReconcileResult{}, err
	}
	if action == "join" {
		if endpoint == "" {
			return ReconcileResult{}, errors.New("Kubernetes join requires control_plane_endpoint")
		}
		if config.Safety.RequireCACertHash && caHash == "" {
			return ReconcileResult{}, errors.New("Kubernetes join requires ca_cert_hash")
		}
		if caHash != "" && !caHashPattern.MatchString(caHash) {
			return ReconcileResult{}, errors.New("Kubernetes ca_cert_hash must be a SHA-256 digest")
		}
		if config.Safety.RequireJoinToken && tokenFile == "" {
			return ReconcileResult{}, errors.New("Kubernetes join requires token_ref or --token-file")
		}
		if tokenFile != "" {
			data, readErr := os.ReadFile(rooted(options.Root, tokenFile))
			if readErr != nil {
				return ReconcileResult{}, fmt.Errorf("read Kubernetes join token: %w", readErr)
			}
			if strings.TrimSpace(string(data)) == "" {
				return ReconcileResult{}, errors.New("Kubernetes join token file is empty")
			}
		}
		if role == "control-plane" && strings.TrimSpace(config.Kubernetes.Join.ControlPlaneCertificatePolicy) == "" {
			return ReconcileResult{}, errors.New("control-plane join requires an explicit certificate policy")
		}
		if role == "control-plane" {
			policy := strings.TrimSpace(config.Kubernetes.Join.ControlPlaneCertificatePolicy)
			switch policy {
			case "manual", "external":
			case "upload", "automatic":
				if !config.Safety.AllowControlPlaneCertUpload {
					return ReconcileResult{}, errors.New("control-plane certificate upload requires allow_control_plane_cert_upload")
				}
			default:
				return ReconcileResult{}, fmt.Errorf("unsupported control-plane certificate policy %q", policy)
			}
		}
	}

	template, err := kubeadmTemplate(config, role, action)
	if err != nil {
		return ReconcileResult{}, err
	}
	cri := resolveCRI(config)
	if !options.SkipPreflight {
		if cri == "" {
			return ReconcileResult{}, errors.New("container runtime CRI socket is not configured")
		}
		if _, err := os.Stat(rooted(options.Root, strings.TrimPrefix(cri, "unix://"))); err != nil {
			return ReconcileResult{}, fmt.Errorf("CRI socket preflight failed: %w", err)
		}
	}

	arguments := []string{"--root", options.Root, "--plan", options.PlanPath, action, "--role", role, "--action", action, "--template", template}
	if output := strings.TrimSpace(config.Kubernetes.Kubeadm.ConfigOutput); output != "" {
		arguments = append(arguments, "--output", output)
	}
	if options.NodeName != "" {
		arguments = append(arguments, "--node-name", options.NodeName)
	}
	if endpoint != "" {
		arguments = append(arguments, "--endpoint", endpoint)
	}
	if tokenFile != "" {
		arguments = append(arguments, "--token-file", tokenFile)
	}
	if caHash != "" {
		arguments = append(arguments, "--ca-cert-hash", caHash)
	}
	if cri != "" {
		arguments = append(arguments, "--cri-socket", cri)
	}
	if cidr := strings.TrimSpace(config.Kubernetes.Cluster.PodCIDR); cidr != "" {
		arguments = append(arguments, "--pod-cidr", cidr)
	}
	if cidr := strings.TrimSpace(config.Kubernetes.Cluster.ServiceCIDR); cidr != "" {
		arguments = append(arguments, "--service-cidr", cidr)
	}
	if options.DryRun {
		arguments = append(arguments, "--dry-run")
	}

	skipped, err := kubeadmAlreadySucceeded(options.Root, role, action)
	if err != nil {
		return ReconcileResult{}, err
	}
	if !skipped {
		if err := options.Runner.Run(ctx, options.KikiKubeadm, arguments); err != nil {
			return ReconcileResult{}, fmt.Errorf("run kiki-kubeadm %s: %w", action, err)
		}
	}
	result := ReconcileResult{Role: role, Action: action, Command: append([]string{options.KikiKubeadm}, arguments...), CRI: cri, KubeadmSkipped: skipped}
	if config.Kubernetes.CNI.Enabled {
		name, cniArguments := cniCommand(config, options)
		result.CNICommand = append([]string{name}, cniArguments...)
		if !options.DryRun {
			if err := options.Runner.Run(ctx, name, cniArguments); err != nil {
				return ReconcileResult{}, fmt.Errorf("apply CNI provider %s: %w", config.Kubernetes.CNI.Provider, err)
			}
			result.CNIReady = true
		}
	}
	if !options.DryRun && (filepath.Clean(options.Root) == "/" || options.CheckKubelet) {
		if err := options.Runner.Run(ctx, options.Systemctl, []string{"is-active", "--quiet", "kubelet.service"}); err != nil {
			return ReconcileResult{}, fmt.Errorf("kubelet health check failed: %w", err)
		}
		result.KubeletReady = true
	}
	return result, nil
}

func normalizeRoleAction(role, action string) (string, string, error) {
	switch strings.TrimSpace(role) {
	case "", "none", "server-core":
		role = "none"
	case "bootstrap", "bootstrap-control-plane":
		role = "bootstrap-control-plane"
	case "control", "control-plane":
		role = "control-plane"
	case "compute":
		role = "compute"
	default:
		return "", "", fmt.Errorf("unsupported Kubernetes role %q", role)
	}
	if strings.TrimSpace(action) == "" {
		switch role {
		case "bootstrap-control-plane":
			action = "init"
		case "control-plane", "compute":
			action = "join"
		default:
			action = "none"
		}
	}
	if action != "none" && action != "init" && action != "join" {
		return "", "", fmt.Errorf("unsupported kubeadm action %q", action)
	}
	if action == "init" && role != "bootstrap-control-plane" {
		return "", "", errors.New("kubeadm init is only valid for bootstrap-control-plane")
	}
	if action == "join" && role != "control-plane" && role != "compute" {
		return "", "", errors.New("kubeadm join is only valid for control-plane or compute")
	}
	return role, action, nil
}

func kubeadmTemplate(config Config, role, action string) (string, error) {
	if explicit := strings.TrimSpace(config.Kubernetes.Kubeadm.ConfigTemplate); explicit != "" {
		return explicit, nil
	}
	var template string
	if action == "init" {
		template = config.Kubernetes.Kubeadm.InitTemplate
	} else if role == "control-plane" {
		template = config.Kubernetes.Kubeadm.JoinControlPlaneTemplate
	} else {
		template = config.Kubernetes.Kubeadm.JoinComputeTemplate
	}
	if strings.TrimSpace(template) == "" {
		return "", fmt.Errorf("kubeadm template is not configured for role %s", role)
	}
	return template, nil
}

func resolveCRI(config Config) string {
	if value := strings.TrimSpace(config.Kubernetes.Kubeadm.CRISocket); value != "" {
		return value
	}
	runtime := strings.TrimSpace(config.Runtime.ContainerRuntime)
	if config.Runtime.CRISockets != nil {
		return strings.TrimSpace(config.Runtime.CRISockets[runtime])
	}
	return ""
}

func validateCNI(config Config) error {
	if !config.Kubernetes.CNI.Enabled {
		return nil
	}
	provider := strings.TrimSpace(config.Kubernetes.CNI.Provider)
	allowed := false
	for _, candidate := range config.Kubernetes.CNI.AllowedProviders {
		if provider == candidate {
			allowed = true
			break
		}
	}
	if !allowed {
		return fmt.Errorf("CNI provider %q is not allowed", provider)
	}
	if strings.TrimSpace(config.Kubernetes.CNI.ManifestURL) == "" && strings.TrimSpace(config.Kubernetes.CNI.ManifestPath) == "" && strings.TrimSpace(config.Kubernetes.CNI.Package) == "" {
		return errors.New("enabled CNI requires manifest_url, manifest_path, or package")
	}
	if value := strings.TrimSpace(config.Kubernetes.CNI.ManifestURL); value != "" {
		parsed, err := url.Parse(value)
		if err != nil || parsed.Host == "" || (parsed.Scheme != "http" && parsed.Scheme != "https") {
			return errors.New("CNI manifest_url must use http or https")
		}
	}
	if value := strings.TrimSpace(config.Kubernetes.CNI.ManifestPath); value != "" && !filepath.IsAbs(value) {
		return errors.New("CNI manifest_path must be absolute")
	}
	if value := strings.TrimSpace(config.Kubernetes.CNI.Package); value != "" && !cniPackagePattern.MatchString(value) {
		return errors.New("CNI package name is invalid")
	}
	return nil
}

func kubeadmAlreadySucceeded(root, role, action string) (bool, error) {
	path := rooted(root, "/var/lib/kiki/kubernetes/state.json")
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return false, nil
		}
		return false, fmt.Errorf("read kubeadm state: %w", err)
	}
	var state struct {
		Status string `json:"status"`
		Role   string `json:"role"`
		Action string `json:"action"`
	}
	if err := json.Unmarshal(data, &state); err != nil {
		return false, fmt.Errorf("decode kubeadm state: %w", err)
	}
	if state.Status != "succeeded" {
		return false, nil
	}
	if state.Role != role || state.Action != action {
		return false, fmt.Errorf("existing successful kubeadm state is %s/%s; refusing %s/%s without an explicit reset workflow", state.Role, state.Action, role, action)
	}
	return true, nil
}

func cniCommand(config Config, options ReconcileOptions) (string, []string) {
	if value := strings.TrimSpace(config.Kubernetes.CNI.ManifestURL); value != "" {
		return options.Kubectl, []string{"apply", "-f", value}
	}
	if value := strings.TrimSpace(config.Kubernetes.CNI.ManifestPath); value != "" {
		return options.Kubectl, []string{"apply", "-f", rooted(options.Root, value)}
	}
	return options.Ki2ctl, []string{"install", strings.TrimSpace(config.Kubernetes.CNI.Package)}
}

func rooted(root, value string) string {
	if filepath.IsAbs(value) && filepath.Clean(root) != "/" {
		return filepath.Join(root, strings.TrimPrefix(filepath.Clean(value), string(filepath.Separator)))
	}
	if filepath.IsAbs(value) {
		return filepath.Clean(value)
	}
	return filepath.Join(root, value)
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return strings.TrimSpace(value)
		}
	}
	return ""
}
