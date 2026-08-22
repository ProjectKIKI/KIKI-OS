package buildsystem

import (
	"errors"
	"fmt"
	"net"
	"net/url"
	"path/filepath"
	"regexp"
	"strings"
)

type OCIBuild struct {
	ID             string   `json:"id"`
	Source         Source   `json:"source"`
	ContextPath    string   `json:"context_path"`
	DefinitionPath string   `json:"definition_path"`
	Destination    string   `json:"destination"`
	ArtifactPVC    string   `json:"artifact_pvc"`
	Platforms      []string `json:"platforms"`
	PackageType    string   `json:"package_type"`
}

type OCIConfig struct {
	GitImage           string
	BuildctlImage      string
	SupplyChainImage   string
	AllowedGitHosts    []string
	AllowedRegistries  []string
	BuildKitAddress    string
	BuildKitCIDR       string
	BuildKitPort       int
	EgressProxyURL     string
	EgressProxyCIDR    string
	RegistryAuthSecret string
	SigningSecret      string
	BuildTokenSecret   string
	InfraOpsURL        string
}

var registryPathPattern = regexp.MustCompile(`^[a-z0-9.-]+(?::[0-9]+)?/[a-z0-9]+(?:[._/-][a-z0-9]+)*$`)

func RenderOCIJob(build OCIBuild, config OCIConfig) (map[string]any, error) {
	if !namePattern.MatchString(build.ID) || !namePattern.MatchString(build.ArtifactPVC) {
		return nil, errors.New("build ID and artifact PVC must be DNS-compatible names")
	}
	if build.PackageType != "oci" && build.PackageType != "cpm" {
		return nil, errors.New("package type must be oci or cpm")
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
	definitionPath, err := safeRelativePath(build.DefinitionPath, false)
	if err != nil {
		return nil, fmt.Errorf("definition path: %w", err)
	}
	if filepath.Base(definitionPath) != definitionPath {
		return nil, errors.New("definition path must be a filename within the context")
	}
	if !registryPathPattern.MatchString(build.Destination) || strings.Contains(build.Destination, "@") || strings.Contains(build.Destination, ":latest") {
		return nil, errors.New("destination must be an untagged OCI registry repository")
	}
	registryHost := strings.Split(build.Destination, "/")[0]
	registryHost = strings.Split(registryHost, ":")[0]
	if !allowedHost(registryHost, config.AllowedRegistries) {
		return nil, fmt.Errorf("registry %q is not allowed", registryHost)
	}
	if !digestPinned(config.GitImage) || !digestPinned(config.BuildctlImage) || !digestPinned(config.SupplyChainImage) {
		return nil, errors.New("all OCI build images must be digest pinned")
	}
	if config.BuildKitPort < 1 || config.BuildKitPort > 65535 || config.BuildKitAddress == "" {
		return nil, errors.New("BuildKit address and port are required")
	}
	if _, _, err := net.ParseCIDR(config.BuildKitCIDR); err != nil {
		return nil, errors.New("valid BuildKit CIDR is required")
	}
	if _, _, err := net.ParseCIDR(config.EgressProxyCIDR); err != nil {
		return nil, errors.New("valid egress proxy CIDR is required")
	}
	if config.RegistryAuthSecret == "" || config.SigningSecret == "" || config.BuildTokenSecret == "" || config.InfraOpsURL == "" {
		return nil, errors.New("registry auth, signing, build token, and InfraOps references are required")
	}
	if len(build.Platforms) == 0 {
		return nil, errors.New("at least one platform is required")
	}
	for _, platform := range build.Platforms {
		if platform != "linux/amd64" && platform != "linux/arm64" {
			return nil, fmt.Errorf("unsupported platform %q", platform)
		}
	}

	security := restrictedSecurityContext()
	proxyEnv := []any{map[string]any{"name": "HTTPS_PROXY", "value": config.EgressProxyURL}, map[string]any{"name": "HTTP_PROXY", "value": config.EgressProxyURL}}
	commonMounts := []any{map[string]any{"name": "workspace", "mountPath": "/workspace"}, map[string]any{"name": "tmp", "mountPath": "/tmp"}}
	clone := map[string]any{"name": "source-clone", "image": config.GitImage, "command": []any{"git"}, "args": []any{"clone", "--no-checkout", "--filter=blob:none", build.Source.URL, "/workspace/source"}, "env": proxyEnv, "securityContext": security, "volumeMounts": commonMounts}
	checkout := map[string]any{"name": "source-checkout", "image": config.GitImage, "command": []any{"git"}, "args": []any{"-C", "/workspace/source", "checkout", "--detach", build.Source.Revision}, "env": proxyEnv, "securityContext": security, "volumeMounts": commonMounts}
	contextDir := "/workspace/source"
	if contextPath != "" {
		contextDir += "/" + contextPath
	}
	imageRef := build.Destination + ":build-" + build.ID
	metadataPath := "/artifacts/" + build.ID + ".buildkit-metadata.json"
	buildctl := map[string]any{
		"name": "buildkit", "image": config.BuildctlImage, "imagePullPolicy": "IfNotPresent",
		"args": []any{"--addr", config.BuildKitAddress, "build", "--frontend", "dockerfile.v0", "--local", "context=" + contextDir, "--local", "dockerfile=" + contextDir, "--opt", "filename=" + definitionPath, "--opt", "platform=" + strings.Join(build.Platforms, ","), "--opt", "build-arg:HTTPS_PROXY=" + config.EgressProxyURL, "--output", "type=image,name=" + imageRef + ",push=true", "--metadata-file", metadataPath},
		"env":  proxyEnv, "securityContext": security,
		"resources":    map[string]any{"requests": map[string]any{"cpu": "500m", "memory": "512Mi"}, "limits": map[string]any{"cpu": "2", "memory": "2Gi"}},
		"volumeMounts": []any{map[string]any{"name": "workspace", "mountPath": "/workspace", "readOnly": true}, map[string]any{"name": "artifacts", "mountPath": "/artifacts"}, map[string]any{"name": "registry-auth", "mountPath": "/home/nonroot/.docker", "readOnly": true}, map[string]any{"name": "tmp", "mountPath": "/tmp"}},
	}
	supplyChain := map[string]any{
		"name": "supply-chain", "image": config.SupplyChainImage, "imagePullPolicy": "IfNotPresent",
		"args": []any{"finalize", "--build-id", build.ID, "--image", imageRef, "--metadata", metadataPath, "--source", build.Source.URL, "--revision", build.Source.Revision, "--artifacts", "/artifacts", "--package-type", build.PackageType, "--infraops-url", config.InfraOpsURL, "--token-file", "/run/secrets/infraops/build-token", "--actor", "build-worker"},
		"env":  proxyEnv, "securityContext": security,
		"resources":    map[string]any{"requests": map[string]any{"cpu": "250m", "memory": "256Mi"}, "limits": map[string]any{"cpu": "2", "memory": "2Gi"}},
		"volumeMounts": []any{map[string]any{"name": "artifacts", "mountPath": "/artifacts"}, map[string]any{"name": "registry-auth", "mountPath": "/home/nonroot/.docker", "readOnly": true}, map[string]any{"name": "signing", "mountPath": "/run/secrets/signing", "readOnly": true}, map[string]any{"name": "build-token", "mountPath": "/run/secrets/infraops", "readOnly": true}, map[string]any{"name": "tmp", "mountPath": "/tmp"}},
	}
	podSpec := map[string]any{
		"restartPolicy": "Never", "automountServiceAccountToken": false,
		"securityContext": map[string]any{"runAsNonRoot": true, "seccompProfile": map[string]any{"type": "RuntimeDefault"}, "fsGroup": int64(65532)},
		"initContainers":  []any{clone, checkout, buildctl}, "containers": []any{supplyChain},
		"nodeSelector": map[string]any{"kiki.io/build-worker": "true"}, "tolerations": []any{map[string]any{"key": "kiki.io/build", "operator": "Equal", "value": "true", "effect": "NoSchedule"}},
		"volumes": []any{
			map[string]any{"name": "workspace", "emptyDir": map[string]any{"sizeLimit": "16Gi"}}, map[string]any{"name": "tmp", "emptyDir": map[string]any{"sizeLimit": "2Gi"}},
			map[string]any{"name": "artifacts", "persistentVolumeClaim": map[string]any{"claimName": build.ArtifactPVC}},
			map[string]any{"name": "registry-auth", "secret": map[string]any{"secretName": config.RegistryAuthSecret, "defaultMode": 256}},
			map[string]any{"name": "signing", "secret": map[string]any{"secretName": config.SigningSecret, "defaultMode": 256}},
			map[string]any{"name": "build-token", "secret": map[string]any{"secretName": config.BuildTokenSecret, "items": []any{map[string]any{"key": "build-token", "path": "build-token"}}, "defaultMode": 256}},
		},
	}
	return map[string]any{"apiVersion": "batch/v1", "kind": "Job", "metadata": map[string]any{"name": build.ID, "namespace": "kiki-build", "labels": map[string]any{"kiki.io/build-id": build.ID, "kiki.io/build-type": build.PackageType}}, "spec": map[string]any{"backoffLimit": 0, "activeDeadlineSeconds": 3600, "ttlSecondsAfterFinished": 86400, "template": map[string]any{"metadata": map[string]any{"labels": map[string]any{"kiki.io/build-id": build.ID}}, "spec": podSpec}}}, nil
}

func RenderOCINetworkPolicy(buildID string, config OCIConfig) (map[string]any, error) {
	base, err := RenderBuildNetworkPolicy(buildID, config.EgressProxyCIDR)
	if err != nil {
		return nil, err
	}
	if _, _, err := net.ParseCIDR(config.BuildKitCIDR); err != nil {
		return nil, errors.New("invalid BuildKit CIDR")
	}
	spec := base["spec"].(map[string]any)
	egress := spec["egress"].([]any)
	egress = append(egress, map[string]any{"to": []any{map[string]any{"ipBlock": map[string]any{"cidr": config.BuildKitCIDR}}}, "ports": []any{map[string]any{"protocol": "TCP", "port": config.BuildKitPort}}})
	spec["egress"] = egress
	return base, nil
}

func validateSource(source Source, hosts []string) error {
	parsed, err := url.Parse(source.URL)
	if err != nil || parsed.Scheme != "https" || parsed.Hostname() == "" || parsed.User != nil {
		return errors.New("source URL must be HTTPS without embedded credentials")
	}
	if !allowedHost(parsed.Hostname(), hosts) {
		return fmt.Errorf("source host %q is not allowed", parsed.Hostname())
	}
	return nil
}

func safeRelativePath(value string, allowEmpty bool) (string, error) {
	clean := filepath.ToSlash(filepath.Clean(value))
	if clean == "." && allowEmpty {
		return "", nil
	}
	if clean == "." || strings.HasPrefix(clean, "../") || strings.HasPrefix(clean, "/") || strings.Contains(clean, "\\") {
		return "", errors.New("path escapes source root")
	}
	return clean, nil
}

func restrictedSecurityContext() map[string]any {
	return map[string]any{"allowPrivilegeEscalation": false, "readOnlyRootFilesystem": true, "runAsNonRoot": true, "runAsUser": int64(65532), "runAsGroup": int64(65532), "capabilities": map[string]any{"drop": []any{"ALL"}}}
}
