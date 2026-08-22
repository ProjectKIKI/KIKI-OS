package modelruntime

import (
	"errors"
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

type PodSpec struct {
	Name          string
	Namespace     string
	NodeName      string
	ModelAlias    string
	ModelPath     string
	ModelSource   string
	ModelDigest   string
	CachePVC      string
	Port          int
	ContextLength int
	CPU           string
	Memory        string
	LlamaImage    string
	VLLMImage     string
	FetcherImage  string
}

// RenderPodTemplate returns the Pod template a controller can place in a
// Deployment or StatefulSet. Images must be digest pinned by the trusted
// platform configuration; users cannot supply an arbitrary mutable image.
func RenderPodTemplate(spec PodSpec, plan Plan) (map[string]any, error) {
	if plan.Phase != "Ready" {
		return nil, errors.New("cannot render a Pod for a non-ready runtime plan")
	}
	if spec.Name == "" || spec.Namespace == "" || spec.ModelAlias == "" || spec.CachePVC == "" {
		return nil, errors.New("name, namespace, model alias, and cache PVC are required")
	}
	if !strings.HasPrefix(spec.ModelPath, "/models/") || strings.Contains(spec.ModelPath, "..") {
		return nil, errors.New("model path must be a safe path below /models")
	}
	if !strings.HasPrefix(spec.ModelSource, "oci://") || !shaDigestPattern.MatchString(spec.ModelDigest) || !digestPinnedImage(spec.FetcherImage) {
		return nil, errors.New("model source, digest, and digest-pinned fetcher image are required")
	}
	if spec.Port < 1024 || spec.Port > 65535 || spec.ContextLength < 512 {
		return nil, errors.New("port or context length is outside the allowed range")
	}
	image := spec.LlamaImage
	args := []string{"--model", spec.ModelPath, "--alias", spec.ModelAlias, "--host", "0.0.0.0", "--port", strconv.Itoa(spec.Port), "--ctx-size", strconv.Itoa(spec.ContextLength)}
	if plan.Engine == "vllm" {
		image = spec.VLLMImage
		args = []string{"--model", spec.ModelPath, "--served-model-name", spec.ModelAlias, "--host", "0.0.0.0", "--port", strconv.Itoa(spec.Port), "--max-model-len", strconv.Itoa(spec.ContextLength)}
	} else if plan.Engine != "llama.cpp" {
		return nil, fmt.Errorf("unsupported engine %q", plan.Engine)
	}
	if !digestPinnedImage(image) {
		return nil, errors.New("runtime image must be pinned by sha256 digest")
	}
	if plan.Engine == "llama.cpp" && plan.GPUOffload {
		args = append(args, "--gpu-layers", "999")
	}

	requests := map[string]any{"cpu": defaultString(spec.CPU, "4"), "memory": defaultString(spec.Memory, "8Gi")}
	limits := map[string]any{"memory": defaultString(spec.Memory, "8Gi")}
	if resource := gpuResource(plan.Backend); resource != "" {
		limits[resource] = 1
	}
	container := map[string]any{
		"name": "inference", "image": image, "imagePullPolicy": "IfNotPresent", "args": args,
		"ports":     []any{map[string]any{"name": "http", "containerPort": spec.Port}},
		"resources": map[string]any{"requests": requests, "limits": limits},
		"securityContext": map[string]any{
			"allowPrivilegeEscalation": false, "readOnlyRootFilesystem": true,
			"runAsNonRoot": true, "runAsUser": int64(65532), "runAsGroup": int64(65532),
			"capabilities": map[string]any{"drop": []any{"ALL"}},
		},
		"volumeMounts": []any{
			map[string]any{"name": "models", "mountPath": "/models", "readOnly": true},
			map[string]any{"name": "tmp", "mountPath": "/tmp"},
		},
		"readinessProbe": map[string]any{"httpGet": map[string]any{"path": "/health", "port": "http"}, "periodSeconds": 5, "failureThreshold": 12},
		"livenessProbe":  map[string]any{"httpGet": map[string]any{"path": "/health", "port": "http"}, "periodSeconds": 15, "failureThreshold": 4},
	}
	source := strings.TrimPrefix(spec.ModelSource, "oci://")
	if index := strings.LastIndex(source, "@"); index >= 0 {
		source = source[:index]
	}
	fetcher := map[string]any{
		"name": "model-fetch", "image": spec.FetcherImage, "imagePullPolicy": "IfNotPresent",
		"args":            []string{"pull", source + "@" + spec.ModelDigest, "--output", "/models/" + spec.ModelAlias},
		"securityContext": map[string]any{"allowPrivilegeEscalation": false, "readOnlyRootFilesystem": true, "runAsNonRoot": true, "runAsUser": int64(65532), "runAsGroup": int64(65532), "capabilities": map[string]any{"drop": []any{"ALL"}}},
		"volumeMounts":    []any{map[string]any{"name": "models", "mountPath": "/models"}, map[string]any{"name": "tmp", "mountPath": "/tmp"}},
	}
	podSpec := map[string]any{
		"automountServiceAccountToken": false,
		"securityContext":              map[string]any{"runAsNonRoot": true, "seccompProfile": map[string]any{"type": "RuntimeDefault"}, "fsGroup": int64(65532)},
		"containers":                   []any{container},
		"initContainers":               []any{fetcher},
		"volumes": []any{
			map[string]any{"name": "models", "persistentVolumeClaim": map[string]any{"claimName": spec.CachePVC}},
			map[string]any{"name": "tmp", "emptyDir": map[string]any{"sizeLimit": "1Gi"}},
		},
	}
	if spec.NodeName != "" {
		podSpec["nodeName"] = spec.NodeName
	}
	return map[string]any{
		"apiVersion": "v1",
		"kind":       "Pod",
		"metadata": map[string]any{
			"name":      spec.Name,
			"namespace": spec.Namespace,
			"labels":    map[string]any{"app.kubernetes.io/name": "kiki-model-runtime", "kiki.io/model-deployment": spec.Name},
		},
		"spec": podSpec,
	}, nil
}

func digestPinnedImage(value string) bool {
	return pinnedImagePattern.MatchString(value)
}

var pinnedImagePattern = regexp.MustCompile(`^[^[:space:]@]+@sha256:[a-f0-9]{64}$`)
var shaDigestPattern = regexp.MustCompile(`^sha256:[a-f0-9]{64}$`)

func gpuResource(backend string) string {
	switch backend {
	case "cuda":
		return "nvidia.com/gpu"
	case "rocm":
		return "amd.com/gpu"
	case "xpu":
		return "gpu.intel.com/i915"
	default:
		return ""
	}
}

func defaultString(value, fallback string) string {
	if value == "" {
		return fallback
	}
	return value
}
