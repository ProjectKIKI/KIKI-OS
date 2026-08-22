package buildsystem

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/url"
	"path/filepath"
	"regexp"
	"strings"
)

type Source struct {
	URL      string `json:"url"`
	Revision string `json:"revision"`
}

type BOSBuild struct {
	ID          string     `json:"id"`
	Source      Source     `json:"source"`
	ContextPath string     `json:"context_path"`
	OutputName  string     `json:"output_name"`
	ArtifactPVC string     `json:"artifact_pvc"`
	Platforms   []string   `json:"platforms"`
	Recipe      *BOSRecipe `json:"recipe,omitempty"`
}

type BOSRecipe struct {
	Name          string   `json:"name"`
	Version       string   `json:"version"`
	Release       string   `json:"release"`
	Summary       string   `json:"summary"`
	Description   string   `json:"description,omitempty"`
	License       string   `json:"license"`
	Arch          string   `json:"arch"`
	SourceURL     string   `json:"source_url"`
	SourceSHA256  string   `json:"source_sha256"`
	BuildRequires []string `json:"build_requires,omitempty"`
	Requires      []string `json:"requires,omitempty"`
	Prepare       []string `json:"prepare,omitempty"`
	Build         []string `json:"build,omitempty"`
	Install       []string `json:"install"`
	Check         []string `json:"check,omitempty"`
	Files         []string `json:"files"`
}

type Config struct {
	GitImage           string
	BOSBuilderImage    string
	SupplyChainImage   string
	AllowedGitHosts    []string
	AllowedSourceHosts []string
	EgressProxyURL     string
	EgressProxyCIDR    string
	OCI                OCIConfig
	Model              ModelConfig
	SigningSecret      string
	BuildTokenSecret   string
	InfraOpsURL        string
}

var commitPattern = regexp.MustCompile(`^[a-f0-9]{40}([a-f0-9]{24})?$`)
var namePattern = regexp.MustCompile(`^[a-z0-9]([-a-z0-9.]{0,61}[a-z0-9])?$`)
var pinnedImagePattern = regexp.MustCompile(`^[^[:space:]@]+@sha256:[a-f0-9]{64}$`)

func RenderBOSJob(build BOSBuild, config Config) (map[string]any, error) {
	if !namePattern.MatchString(build.ID) || !namePattern.MatchString(build.ArtifactPVC) {
		return nil, errors.New("build ID and artifact PVC must be DNS-compatible names")
	}
	if !commitPattern.MatchString(build.Source.Revision) {
		return nil, errors.New("source revision must be a full 40 or 64 character commit SHA")
	}
	parsed, err := url.Parse(build.Source.URL)
	if err != nil || parsed.Scheme != "https" || parsed.Hostname() == "" || parsed.User != nil {
		return nil, errors.New("source URL must be an HTTPS URL without embedded credentials")
	}
	allowedHosts := config.AllowedGitHosts
	if build.Recipe != nil && len(config.AllowedSourceHosts) > 0 {
		allowedHosts = config.AllowedSourceHosts
	}
	if !allowedHost(parsed.Hostname(), allowedHosts) {
		return nil, fmt.Errorf("source host %q is not allowed", parsed.Hostname())
	}
	contextPath := filepath.ToSlash(filepath.Clean(build.ContextPath))
	if contextPath == "." {
		contextPath = ""
	}
	if strings.HasPrefix(contextPath, "../") || strings.HasPrefix(contextPath, "/") || strings.Contains(contextPath, "\\") {
		return nil, errors.New("context path must remain below the source root")
	}
	if filepath.Base(build.OutputName) != build.OutputName || filepath.Ext(build.OutputName) != ".bos" {
		return nil, errors.New("output name must be a .bos filename")
	}
	if !digestPinned(config.BOSBuilderImage) || !digestPinned(config.SupplyChainImage) || (build.Recipe == nil && !digestPinned(config.GitImage)) {
		return nil, errors.New("git, BOS builder, and supply-chain images must be digest pinned")
	}
	proxy, err := url.Parse(config.EgressProxyURL)
	if err != nil || (proxy.Scheme != "http" && proxy.Scheme != "https") || proxy.Host == "" || proxy.User != nil {
		return nil, errors.New("a credential-free HTTP(S) egress proxy is required")
	}
	if _, _, err := net.ParseCIDR(config.EgressProxyCIDR); err != nil {
		return nil, errors.New("a valid egress proxy CIDR is required")
	}
	if len(build.Platforms) != 1 || (build.Platforms[0] != "linux/amd64" && build.Platforms[0] != "linux/arm64") {
		return nil, errors.New("BOS MVP requires exactly one supported platform")
	}
	if build.Recipe != nil {
		if err := validateBOSRecipe(*build.Recipe, build.Source, build.Platforms[0]); err != nil {
			return nil, err
		}
	}

	security := map[string]any{
		"allowPrivilegeEscalation": false, "readOnlyRootFilesystem": true,
		"runAsNonRoot": true, "runAsUser": int64(65532), "runAsGroup": int64(65532),
		"capabilities": map[string]any{"drop": []any{"ALL"}},
	}
	clone := map[string]any{
		"name": "source-clone", "image": config.GitImage, "imagePullPolicy": "IfNotPresent",
		"command": []any{"git"}, "args": []any{"clone", "--no-checkout", "--filter=blob:none", build.Source.URL, "/workspace/source"},
		"env":             []any{map[string]any{"name": "HTTPS_PROXY", "value": config.EgressProxyURL}},
		"securityContext": security, "volumeMounts": []any{map[string]any{"name": "workspace", "mountPath": "/workspace"}, map[string]any{"name": "tmp", "mountPath": "/tmp"}},
	}
	checkout := map[string]any{
		"name": "source-checkout", "image": config.GitImage, "imagePullPolicy": "IfNotPresent",
		"command": []any{"git"}, "args": []any{"-C", "/workspace/source", "checkout", "--detach", build.Source.Revision},
		"env":             []any{map[string]any{"name": "HTTPS_PROXY", "value": config.EgressProxyURL}},
		"securityContext": security, "volumeMounts": []any{map[string]any{"name": "workspace", "mountPath": "/workspace"}, map[string]any{"name": "tmp", "mountPath": "/tmp"}},
	}
	workdir := "/workspace/source"
	if contextPath != "" {
		workdir += "/" + contextPath
	}
	builder := map[string]any{
		"name": "bos-build", "image": config.BOSBuilderImage, "imagePullPolicy": "IfNotPresent",
		"args":            []any{"-C", workdir, "-o", "/artifacts/" + build.OutputName},
		"securityContext": security,
		"resources":       map[string]any{"requests": map[string]any{"cpu": "500m", "memory": "512Mi", "ephemeral-storage": "1Gi"}, "limits": map[string]any{"cpu": "4", "memory": "4Gi", "ephemeral-storage": "8Gi"}},
		"volumeMounts":    []any{map[string]any{"name": "workspace", "mountPath": "/workspace", "readOnly": true}, map[string]any{"name": "artifacts", "mountPath": "/artifacts"}, map[string]any{"name": "tmp", "mountPath": "/tmp"}},
	}
	initContainers := []any{clone, checkout, builder}
	if build.Recipe != nil {
		recipeJSON, err := json.Marshal(build.Recipe)
		if err != nil {
			return nil, err
		}
		if len(recipeJSON) > 96*1024 {
			return nil, errors.New("BOS recipe exceeds the 96 KiB Job argument limit")
		}
		builder = map[string]any{
			"name": "bos-recipe-build", "image": config.BOSBuilderImage, "imagePullPolicy": "IfNotPresent",
			"command":         []any{"/usr/local/bin/kiki-bos-recipe"},
			"args":            []any{"--recipe-base64", base64.RawURLEncoding.EncodeToString(recipeJSON), "--output", "/artifacts/" + build.OutputName},
			"env":             []any{map[string]any{"name": "HTTPS_PROXY", "value": config.EgressProxyURL}},
			"securityContext": security,
			"resources":       map[string]any{"requests": map[string]any{"cpu": "500m", "memory": "512Mi", "ephemeral-storage": "1Gi"}, "limits": map[string]any{"cpu": "4", "memory": "4Gi", "ephemeral-storage": "8Gi"}},
			"volumeMounts":    []any{map[string]any{"name": "workspace", "mountPath": "/workspace"}, map[string]any{"name": "artifacts", "mountPath": "/artifacts"}, map[string]any{"name": "tmp", "mountPath": "/tmp"}},
		}
		initContainers = []any{builder}
	}
	supplyChain := map[string]any{
		"name": "supply-chain", "image": config.SupplyChainImage, "imagePullPolicy": "IfNotPresent",
		"args":            []any{"finalize-file", "--build-id", build.ID, "--artifact", "/artifacts/" + build.OutputName, "--source", build.Source.URL, "--revision", build.Source.Revision, "--evidence-dir", "/artifacts", "--package-type", "bos", "--infraops-url", config.InfraOpsURL, "--token-file", "/run/secrets/infraops/build-token", "--actor", "build-worker"},
		"securityContext": security,
		"resources":       map[string]any{"requests": map[string]any{"cpu": "250m", "memory": "256Mi"}, "limits": map[string]any{"cpu": "2", "memory": "2Gi"}},
		"volumeMounts":    []any{map[string]any{"name": "artifacts", "mountPath": "/artifacts"}, map[string]any{"name": "signing", "mountPath": "/run/secrets/signing", "readOnly": true}, map[string]any{"name": "build-token", "mountPath": "/run/secrets/infraops", "readOnly": true}, map[string]any{"name": "tmp", "mountPath": "/tmp"}},
	}
	if config.SigningSecret == "" || config.BuildTokenSecret == "" || config.InfraOpsURL == "" {
		return nil, errors.New("signing, build token, and InfraOps references are required")
	}
	podSpec := map[string]any{
		"restartPolicy": "Never", "automountServiceAccountToken": false,
		"securityContext": map[string]any{"runAsNonRoot": true, "seccompProfile": map[string]any{"type": "RuntimeDefault"}, "fsGroup": int64(65532)},
		"initContainers":  initContainers, "containers": []any{supplyChain},
		"nodeSelector": map[string]any{"kiki.io/build-worker": "true"},
		"tolerations":  []any{map[string]any{"key": "kiki.io/build", "operator": "Equal", "value": "true", "effect": "NoSchedule"}},
		"volumes": []any{
			map[string]any{"name": "workspace", "emptyDir": map[string]any{"sizeLimit": "16Gi"}},
			map[string]any{"name": "artifacts", "persistentVolumeClaim": map[string]any{"claimName": build.ArtifactPVC}},
			map[string]any{"name": "tmp", "emptyDir": map[string]any{"sizeLimit": "1Gi"}},
			map[string]any{"name": "signing", "secret": map[string]any{"secretName": config.SigningSecret, "defaultMode": 256}},
			map[string]any{"name": "build-token", "secret": map[string]any{"secretName": config.BuildTokenSecret, "items": []any{map[string]any{"key": "build-token", "path": "build-token"}}, "defaultMode": 256}},
		},
	}
	return map[string]any{
		"apiVersion": "batch/v1", "kind": "Job",
		"metadata": map[string]any{"name": build.ID, "namespace": "kiki-build", "labels": map[string]any{"kiki.io/build-id": build.ID, "kiki.io/build-type": "bos"}},
		"spec":     map[string]any{"backoffLimit": 0, "activeDeadlineSeconds": 1800, "ttlSecondsAfterFinished": 86400, "template": map[string]any{"metadata": map[string]any{"labels": map[string]any{"kiki.io/build-id": build.ID}}, "spec": podSpec}},
	}, nil
}

var bosFieldPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._+:-]{0,127}$`)
var sha256HexPattern = regexp.MustCompile(`^[a-f0-9]{64}$`)

func validateBOSRecipe(recipe BOSRecipe, source Source, platform string) error {
	if !bosFieldPattern.MatchString(recipe.Name) || !bosFieldPattern.MatchString(recipe.Version) || !bosFieldPattern.MatchString(recipe.Release) || recipe.Summary == "" || recipe.License == "" {
		return errors.New("BOS recipe requires valid name, version, release, summary, and license")
	}
	if len(recipe.Summary) > 256 || len(recipe.Description) > 4096 || len(recipe.Install) == 0 || len(recipe.Files) == 0 {
		return errors.New("BOS recipe requires install commands and files within size limits")
	}
	if recipe.SourceURL != source.URL || recipe.SourceSHA256 != source.Revision || !sha256HexPattern.MatchString(recipe.SourceSHA256) {
		return errors.New("BOS recipe source URL and SHA-256 must match the immutable build source")
	}
	wantArch := "amd64"
	if platform == "linux/arm64" {
		wantArch = "arm64"
	}
	if recipe.Arch != wantArch {
		return errors.New("BOS recipe architecture does not match platform")
	}
	for _, group := range [][]string{recipe.BuildRequires, recipe.Requires} {
		if len(group) > 128 {
			return errors.New("too many BOS dependencies")
		}
		for _, item := range group {
			if !bosFieldPattern.MatchString(item) {
				return errors.New("invalid BOS dependency")
			}
		}
	}
	for _, group := range [][]string{recipe.Prepare, recipe.Build, recipe.Install, recipe.Check} {
		if len(group) > 64 {
			return errors.New("too many BOS recipe commands")
		}
		for _, command := range group {
			if strings.TrimSpace(command) == "" || len(command) > 4096 || strings.ContainsRune(command, '\x00') {
				return errors.New("invalid BOS recipe command")
			}
		}
	}
	for _, path := range recipe.Files {
		if !strings.HasPrefix(path, "/") || strings.Contains(path, "..") || strings.ContainsAny(path, "\x00\r\n") {
			return errors.New("BOS file paths must be safe absolute paths")
		}
	}
	return nil
}

func RenderBuildNetworkPolicy(buildID, proxyCIDR string) (map[string]any, error) {
	if !namePattern.MatchString(buildID) {
		return nil, errors.New("invalid build ID")
	}
	if _, _, err := net.ParseCIDR(proxyCIDR); err != nil {
		return nil, errors.New("invalid proxy CIDR")
	}
	return map[string]any{
		"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
		"metadata": map[string]any{"name": buildID + "-egress", "namespace": "kiki-build"},
		"spec": map[string]any{
			"podSelector": map[string]any{"matchLabels": map[string]any{"kiki.io/build-id": buildID}},
			"policyTypes": []any{"Ingress", "Egress"}, "ingress": []any{},
			"egress": []any{
				map[string]any{"to": []any{map[string]any{"namespaceSelector": map[string]any{"matchLabels": map[string]any{"kubernetes.io/metadata.name": "kube-system"}}, "podSelector": map[string]any{"matchLabels": map[string]any{"k8s-app": "kube-dns"}}}}, "ports": []any{map[string]any{"protocol": "UDP", "port": 53}, map[string]any{"protocol": "TCP", "port": 53}}},
				map[string]any{"to": []any{map[string]any{"ipBlock": map[string]any{"cidr": proxyCIDR}}}, "ports": []any{map[string]any{"protocol": "TCP", "port": 443}, map[string]any{"protocol": "TCP", "port": 80}}},
				map[string]any{"to": []any{map[string]any{"namespaceSelector": map[string]any{"matchLabels": map[string]any{"kubernetes.io/metadata.name": "kiki-system"}}, "podSelector": map[string]any{"matchLabels": map[string]any{"app.kubernetes.io/name": "kiki-infraops"}}}}, "ports": []any{map[string]any{"protocol": "TCP", "port": 8090}}},
			},
		},
	}, nil
}

func allowedHost(host string, allowed []string) bool {
	for _, candidate := range allowed {
		if strings.EqualFold(host, strings.TrimSpace(candidate)) {
			return true
		}
	}
	return false
}

func digestPinned(value string) bool {
	return pinnedImagePattern.MatchString(value)
}
