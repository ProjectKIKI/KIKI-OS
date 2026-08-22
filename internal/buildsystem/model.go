package buildsystem

import (
	"errors"
	"fmt"
	"net"
	"net/url"
	"path/filepath"
	"strings"
)

type ModelBuild struct {
	ID           string
	Source       Source
	ContextPath  string
	InputPath    string
	InputFormat  string
	OutputFormat string
	Quantization string
	Destination  string
	ArtifactPVC  string
	LicenseID    string
}

type ModelConfig struct {
	GitImage           string
	BuilderImage       string
	SupplyChainImage   string
	AllowedGitHosts    []string
	AllowedRegistries  []string
	EgressProxyURL     string
	EgressProxyCIDR    string
	RegistryAuthSecret string
	SigningSecret      string
	BuildTokenSecret   string
	InfraOpsURL        string
}

func RenderModelJob(build ModelBuild, config ModelConfig) (map[string]any, error) {
	if !namePattern.MatchString(build.ID) || !namePattern.MatchString(build.ArtifactPVC) {
		return nil, errors.New("build ID and artifact PVC must be DNS-compatible names")
	}
	if !commitPattern.MatchString(build.Source.Revision) {
		return nil, errors.New("source revision must be a full commit SHA")
	}
	if err := validateSource(build.Source, config.AllowedGitHosts); err != nil {
		return nil, err
	}
	contextPath, err := safeRelativePath(build.ContextPath, true)
	if err != nil {
		return nil, fmt.Errorf("context path: %w", err)
	}
	inputPath, err := safeRelativePath(build.InputPath, false)
	if err != nil {
		return nil, fmt.Errorf("input path: %w", err)
	}
	if build.InputFormat != "gguf" && build.InputFormat != "safetensors" {
		return nil, errors.New("input format must be gguf or safetensors")
	}
	if build.OutputFormat != "gguf" && build.OutputFormat != "safetensors" {
		return nil, errors.New("output format must be gguf or safetensors")
	}
	if build.OutputFormat == "safetensors" && build.Quantization != "none" {
		return nil, errors.New("safetensors output supports only none quantization")
	}
	allowedQuantization := map[string]bool{"none": true, "q4_k_m": true, "q5_k_m": true, "q8_0": true}
	if !allowedQuantization[build.Quantization] {
		return nil, errors.New("unsupported model quantization")
	}
	if strings.TrimSpace(build.LicenseID) == "" {
		return nil, errors.New("model license ID is required")
	}
	if !registryPathPattern.MatchString(build.Destination) || strings.Contains(build.Destination, "@") || strings.Contains(build.Destination, ":latest") {
		return nil, errors.New("destination must be an untagged OCI registry repository")
	}
	registryHost := strings.Split(strings.Split(build.Destination, "/")[0], ":")[0]
	if !allowedHost(registryHost, config.AllowedRegistries) {
		return nil, fmt.Errorf("registry %q is not allowed", registryHost)
	}
	if !digestPinned(config.GitImage) || !digestPinned(config.BuilderImage) || !digestPinned(config.SupplyChainImage) {
		return nil, errors.New("all model build images must be digest pinned")
	}
	proxy, err := url.Parse(config.EgressProxyURL)
	if err != nil || (proxy.Scheme != "http" && proxy.Scheme != "https") || proxy.Host == "" || proxy.User != nil {
		return nil, errors.New("credential-free HTTP(S) egress proxy is required")
	}
	if _, _, err := net.ParseCIDR(config.EgressProxyCIDR); err != nil {
		return nil, errors.New("valid egress proxy CIDR is required")
	}
	if config.RegistryAuthSecret == "" || config.SigningSecret == "" || config.BuildTokenSecret == "" || config.InfraOpsURL == "" {
		return nil, errors.New("registry auth, signing, build token, and InfraOps references are required")
	}
	security := restrictedSecurityContext()
	proxyEnv := []any{map[string]any{"name": "HTTPS_PROXY", "value": config.EgressProxyURL}, map[string]any{"name": "HTTP_PROXY", "value": config.EgressProxyURL}}
	commonMounts := []any{map[string]any{"name": "workspace", "mountPath": "/workspace"}, map[string]any{"name": "tmp", "mountPath": "/tmp"}}
	clone := map[string]any{"name": "source-clone", "image": config.GitImage, "command": []any{"git"}, "args": []any{"clone", "--no-checkout", "--filter=blob:none", build.Source.URL, "/workspace/source"}, "env": proxyEnv, "securityContext": security, "volumeMounts": commonMounts}
	checkout := map[string]any{"name": "source-checkout", "image": config.GitImage, "command": []any{"git"}, "args": []any{"-C", "/workspace/source", "checkout", "--detach", build.Source.Revision}, "env": proxyEnv, "securityContext": security, "volumeMounts": commonMounts}
	input := filepath.ToSlash(filepath.Join("/workspace/source", contextPath, inputPath))
	imageRef := build.Destination + ":build-" + build.ID
	metadata := "/artifacts/" + build.ID + ".model-metadata.json"
	builder := map[string]any{
		"name": "model-build", "image": config.BuilderImage, "imagePullPolicy": "IfNotPresent",
		"args": []any{"build-push", "--input", input, "--input-format", build.InputFormat, "--output-format", build.OutputFormat, "--quantization", build.Quantization, "--destination", imageRef, "--metadata", metadata, "--license", build.LicenseID},
		"env":  proxyEnv, "securityContext": security,
		"resources":    map[string]any{"requests": map[string]any{"cpu": "2", "memory": "4Gi", "ephemeral-storage": "20Gi"}, "limits": map[string]any{"cpu": "16", "memory": "64Gi", "ephemeral-storage": "100Gi"}},
		"volumeMounts": []any{map[string]any{"name": "workspace", "mountPath": "/workspace"}, map[string]any{"name": "artifacts", "mountPath": "/artifacts"}, map[string]any{"name": "registry-auth", "mountPath": "/home/nonroot/.docker", "readOnly": true}, map[string]any{"name": "tmp", "mountPath": "/tmp"}},
	}
	supplyChain := map[string]any{
		"name": "supply-chain", "image": config.SupplyChainImage, "imagePullPolicy": "IfNotPresent",
		"args": []any{"finalize", "--build-id", build.ID, "--image", imageRef, "--metadata", metadata, "--source", build.Source.URL, "--revision", build.Source.Revision, "--artifacts", "/artifacts", "--package-type", "model", "--infraops-url", config.InfraOpsURL, "--token-file", "/run/secrets/infraops/build-token", "--actor", "build-worker"},
		"env":  proxyEnv, "securityContext": security,
		"volumeMounts": []any{map[string]any{"name": "artifacts", "mountPath": "/artifacts"}, map[string]any{"name": "registry-auth", "mountPath": "/home/nonroot/.docker", "readOnly": true}, map[string]any{"name": "signing", "mountPath": "/run/secrets/signing", "readOnly": true}, map[string]any{"name": "build-token", "mountPath": "/run/secrets/infraops", "readOnly": true}, map[string]any{"name": "tmp", "mountPath": "/tmp"}},
	}
	podSpec := map[string]any{
		"restartPolicy": "Never", "automountServiceAccountToken": false,
		"securityContext": map[string]any{"runAsNonRoot": true, "seccompProfile": map[string]any{"type": "RuntimeDefault"}, "fsGroup": int64(65532)},
		"initContainers":  []any{clone, checkout, builder}, "containers": []any{supplyChain},
		"nodeSelector": map[string]any{"kiki.io/model-builder": "true"}, "tolerations": []any{map[string]any{"key": "kiki.io/model-build", "operator": "Equal", "value": "true", "effect": "NoSchedule"}},
		"volumes": []any{map[string]any{"name": "workspace", "emptyDir": map[string]any{"sizeLimit": "120Gi"}}, map[string]any{"name": "artifacts", "persistentVolumeClaim": map[string]any{"claimName": build.ArtifactPVC}}, map[string]any{"name": "registry-auth", "secret": map[string]any{"secretName": config.RegistryAuthSecret, "defaultMode": 256}}, map[string]any{"name": "signing", "secret": map[string]any{"secretName": config.SigningSecret, "defaultMode": 256}}, map[string]any{"name": "build-token", "secret": map[string]any{"secretName": config.BuildTokenSecret, "items": []any{map[string]any{"key": "build-token", "path": "build-token"}}, "defaultMode": 256}}, map[string]any{"name": "tmp", "emptyDir": map[string]any{"sizeLimit": "4Gi"}}},
	}
	return map[string]any{"apiVersion": "batch/v1", "kind": "Job", "metadata": map[string]any{"name": build.ID, "namespace": "kiki-build", "labels": map[string]any{"kiki.io/build-id": build.ID, "kiki.io/build-type": "model"}}, "spec": map[string]any{"backoffLimit": 0, "activeDeadlineSeconds": 21600, "ttlSecondsAfterFinished": 86400, "template": map[string]any{"metadata": map[string]any{"labels": map[string]any{"kiki.io/build-id": build.ID}}, "spec": podSpec}}}, nil
}
