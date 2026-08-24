package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"example.com/aos-pkg/internal/agent"
	"example.com/aos-pkg/internal/stage3"
)

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	if os.Args[1] == "serve" {
		serve(os.Args[2:])
		return
	}
	if os.Args[1] == "kube" {
		kube(os.Args[2:])
		return
	}
	if os.Args[1] == "plan" {
		plan(os.Args[2:])
		return
	}
	if len(os.Args) != 2 || os.Args[1] != "inventory" {
		usage()
		os.Exit(2)
	}
	inventory, err := agent.NewCollector().Collect()
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(inventory); err != nil {
		fmt.Fprintln(os.Stderr, "error: encode inventory:", err)
		os.Exit(1)
	}
}

func usage() {
	fmt.Fprintln(os.Stderr, "usage: kiki-agent <inventory|serve|kube reconcile|plan fetch>")
}

func plan(arguments []string) {
	if len(arguments) == 0 || arguments[0] != "fetch" {
		usage()
		os.Exit(2)
	}
	flags := flag.NewFlagSet("plan fetch", flag.ExitOnError)
	root := flags.String("root", "/", "target root filesystem")
	planURL := flags.String("url", "", "remote install plan URL")
	digest := flags.String("sha256", "", "expected remote plan SHA-256")
	signature := flags.String("signature", "", "Ed25519 signature as base64, @file, file URL, or HTTP(S) URL")
	publicKey := flags.String("public-key", "/etc/kiki/trust/install-plan.ed25519.pub", "trusted Ed25519 public key")
	commandLine := flags.String("cmdline", "/proc/cmdline", "kernel command line used when URL flags are absent")
	downloaded := flags.String("downloaded", "/run/kiki/remote-install-plan.yaml", "downloaded plan path")
	verified := flags.String("verified", "/run/kiki/install-plan.yaml", "verified plan path")
	allowUnverified := flags.Bool("allow-unverified", false, "explicitly allow an unverified remote plan")
	maxBytes := flags.Int64("max-bytes", stage3.DefaultRemotePlanLimit, "maximum remote plan size")
	_ = flags.Parse(arguments[1:])

	if strings.TrimSpace(*planURL) == "" {
		data, err := os.ReadFile(rootedPath(*root, *commandLine))
		if err != nil {
			fatalPlan(fmt.Errorf("read kernel command line: %w", err))
		}
		values := stage3.ParsePlanKernelParameters(string(data))
		*planURL = values["kiki.plan.url"]
		if strings.TrimSpace(*digest) == "" {
			*digest = values["kiki.plan.sha256"]
		}
		if strings.TrimSpace(*signature) == "" {
			*signature = values["kiki.plan.signature"]
		}
	}
	result, err := stage3.FetchRemotePlan(context.Background(), stage3.RemotePlanOptions{
		URL:             *planURL,
		SHA256:          *digest,
		Signature:       rootedSignatureReference(*root, *signature),
		PublicKeyPath:   rootedPath(*root, *publicKey),
		DownloadedPath:  rootedPath(*root, *downloaded),
		VerifiedPath:    rootedPath(*root, *verified),
		AllowUnverified: *allowUnverified,
		MaxBytes:        *maxBytes,
	})
	if err != nil {
		fatalPlan(err)
	}
	fmt.Printf("kiki-agent: remote plan fetched sha256=%s size=%d verified=%t method=%s path=%s\n", result.SHA256, result.Size, result.Verified, result.VerificationMethod, result.VerifiedPath)
}

func kube(arguments []string) {
	if len(arguments) == 0 || arguments[0] != "reconcile" {
		usage()
		os.Exit(2)
	}
	flags := flag.NewFlagSet("kube reconcile", flag.ExitOnError)
	root := flags.String("root", "/", "target root filesystem")
	defaultsDir := flags.String("defaults-dir", "/usr/share/kiki/defaults", "distribution defaults directory")
	profile := flags.String("profile", "", "role profile name or YAML path")
	installPlan := flags.String("install-plan", "/var/lib/ki2/install-plan.yaml", "installed plan path")
	overridesDir := flags.String("overrides-dir", "/etc/kiki/overrides", "operator override directory")
	renderedPlan := flags.String("rendered-plan", "/var/lib/kiki/rendered/stage3-plan.yaml", "merged redacted plan path")
	kikiKubeadm := flags.String("kiki-kubeadm", "/usr/bin/kiki-kubeadm", "guarded kubeadm helper")
	kubectl := flags.String("kubectl", "/usr/bin/kubectl", "kubectl executable used for explicit CNI manifests")
	ki2ctl := flags.String("ki2ctl", "/usr/bin/ki2ctl", "ki2ctl executable used for packaged CNI")
	systemctl := flags.String("systemctl", "/usr/bin/systemctl", "systemctl executable used for kubelet health checks")
	tokenFile := flags.String("token-file", "", "one-shot kubeadm join token file")
	endpoint := flags.String("endpoint", "", "one-shot control-plane endpoint")
	caCertHash := flags.String("ca-cert-hash", "", "one-shot discovery CA hash")
	nodeName := flags.String("node-name", "", "one-shot Kubernetes node name")
	dryRun := flags.Bool("dry-run", false, "render and record the kubeadm command without executing it")
	skipPreflight := flags.Bool("skip-preflight", false, "skip CRI socket checks for image/rootfs validation")
	_ = flags.Parse(arguments[1:])

	planPath := rootedPath(*root, *installPlan)
	paths, err := stage3.YAMLFiles(rootedPath(*root, *defaultsDir))
	if err != nil {
		fatalStage3(err)
	}
	profilePath, err := resolveProfilePath(*root, *profile, planPath)
	if err != nil {
		fatalStage3(err)
	}
	if profilePath != "" {
		paths = append(paths, profilePath)
	}
	paths = append(paths, planPath)
	overrides, err := stage3.YAMLFiles(rootedPath(*root, *overridesDir))
	if err != nil {
		fatalStage3(err)
	}
	paths = append(paths, overrides...)

	document, err := stage3.LoadFiles(paths)
	if err != nil {
		fatalStage3(err)
	}
	for path, value := range map[string]string{
		"kubernetes.cluster.control_plane_endpoint": *endpoint,
		"kubernetes.join.ca_cert_hash":              *caCertHash,
		"kubernetes.join.token_ref":                 *tokenFile,
		"system.hostname":                           *nodeName,
	} {
		if strings.TrimSpace(value) != "" {
			if err := stage3.SetPath(document, path, value); err != nil {
				fatalStage3(err)
			}
		}
	}
	renderedPath := rootedPath(*root, *renderedPlan)
	if err := stage3.WriteRendered(renderedPath, document); err != nil {
		fatalStage3(err)
	}
	config, err := stage3.Decode(document)
	if err != nil {
		fatalStage3(err)
	}
	result, err := stage3.Reconcile(context.Background(), config, stage3.ReconcileOptions{
		Root:          *root,
		PlanPath:      renderedPath,
		KikiKubeadm:   *kikiKubeadm,
		Kubectl:       *kubectl,
		Ki2ctl:        *ki2ctl,
		Systemctl:     *systemctl,
		TokenFile:     *tokenFile,
		NodeName:      *nodeName,
		Endpoint:      *endpoint,
		CACertHash:    *caCertHash,
		DryRun:        *dryRun,
		SkipPreflight: *skipPreflight,
	})
	if err != nil {
		fatalStage3(err)
	}
	fmt.Printf(
		"kiki-agent: kube reconcile role=%s action=%s kubeadm_skipped=%t kubelet_ready=%t rendered=%s\n",
		result.Role,
		result.Action,
		result.KubeadmSkipped,
		result.KubeletReady,
		renderedPath,
	)
}

func resolveProfilePath(root, profile, planPath string) (string, error) {
	if strings.TrimSpace(profile) != "" {
		if strings.ContainsRune(profile, filepath.Separator) || filepath.Ext(profile) != "" {
			return rootedPath(root, profile), nil
		}
		return rootedPath(root, filepath.Join("/usr/share/kiki/profiles", profile+".yaml")), nil
	}
	document, err := stage3.LoadFiles([]string{planPath})
	if err != nil {
		return "", err
	}
	config, err := stage3.Decode(document)
	if err != nil {
		return "", err
	}
	name := ""
	switch config.Kubernetes.Role {
	case "bootstrap", "bootstrap-control-plane":
		name = "bootstrap"
	case "control", "control-plane":
		name = "control"
	case "compute":
		name = "compute"
	case "none", "server-core", "":
		name = "server-core"
	}
	if name == "" {
		return "", fmt.Errorf("cannot derive Stage 3 profile from Kubernetes role %q", config.Kubernetes.Role)
	}
	path := rootedPath(root, filepath.Join("/usr/share/kiki/profiles", name+".yaml"))
	if _, err := os.Stat(path); err != nil {
		if os.IsNotExist(err) {
			return "", nil
		}
		return "", err
	}
	return path, nil
}

func rootedPath(root, path string) string {
	if filepath.IsAbs(path) && filepath.Clean(root) != "/" {
		return filepath.Join(root, strings.TrimPrefix(filepath.Clean(path), string(filepath.Separator)))
	}
	if filepath.IsAbs(path) {
		return filepath.Clean(path)
	}
	return filepath.Join(root, path)
}

func rootedSignatureReference(root, reference string) string {
	reference = strings.TrimSpace(reference)
	if strings.HasPrefix(reference, "@") {
		return "@" + rootedPath(root, strings.TrimPrefix(reference, "@"))
	}
	if strings.HasPrefix(reference, "file://") {
		return "file://" + rootedPath(root, strings.TrimPrefix(reference, "file://"))
	}
	return reference
}

func fatalStage3(err error) {
	fmt.Fprintln(os.Stderr, "kiki-agent: kube reconcile:", err)
	os.Exit(1)
}

func fatalPlan(err error) {
	fmt.Fprintln(os.Stderr, "kiki-agent: plan fetch:", err)
	os.Exit(1)
}

func serve(arguments []string) {
	flags := flag.NewFlagSet("serve", flag.ExitOnError)
	infraOpsURL := flags.String("infraops-url", "", "InfraOps base URL")
	tokenFile := flags.String("token-file", "", "bearer-token file")
	nodeName := flags.String("node-name", "", "Kubernetes node name")
	interval := flags.Duration("interval", 60*time.Second, "inventory reporting interval")
	_ = flags.Parse(arguments)
	if *infraOpsURL == "" || *tokenFile == "" || *nodeName == "" {
		log.Fatal("-infraops-url, -token-file, and -node-name are required")
	}
	data, err := os.ReadFile(*tokenFile)
	if err != nil {
		log.Fatal(err)
	}
	token := strings.TrimSpace(string(data))
	collector := agent.NewCollector()
	reporter := agent.Reporter{BaseURL: *infraOpsURL, Token: token, Actor: "kiki-agent", NodeName: *nodeName, HTTP: &http.Client{Timeout: 30 * time.Second}, Collect: collector.Collect, Interval: *interval, OnError: func(err error) { log.Printf("inventory report failed: %v", err) }}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := reporter.Run(ctx); err != nil {
		log.Fatal(err)
	}
}
