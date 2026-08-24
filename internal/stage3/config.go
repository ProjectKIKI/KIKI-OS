package stage3

import (
	"bytes"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"gopkg.in/yaml.v3"
)

type Document map[string]any

type Config struct {
	System struct {
		Hostname string `yaml:"hostname"`
	} `yaml:"system"`
	Runtime struct {
		ContainerRuntime string            `yaml:"container_runtime"`
		SwapPolicy       string            `yaml:"swap_policy"`
		CRISockets       map[string]string `yaml:"cri_sockets"`
	} `yaml:"runtime"`
	Kubernetes struct {
		Role    string `yaml:"role"`
		Cluster struct {
			ControlPlaneEndpoint string `yaml:"control_plane_endpoint"`
			PodCIDR              string `yaml:"pod_cidr"`
			ServiceCIDR          string `yaml:"service_cidr"`
		} `yaml:"cluster"`
		Kubeadm struct {
			Action                   string `yaml:"action"`
			ConfigOutput             string `yaml:"config_output"`
			ConfigTemplate           string `yaml:"config_template"`
			InitTemplate             string `yaml:"init_template"`
			JoinControlPlaneTemplate string `yaml:"join_control_plane_template"`
			JoinComputeTemplate      string `yaml:"join_compute_template"`
			CRISocket                string `yaml:"cri_socket"`
		} `yaml:"kubeadm"`
		Join struct {
			TokenRef                      string `yaml:"token_ref"`
			CACertHash                    string `yaml:"ca_cert_hash"`
			ControlPlaneCertificatePolicy string `yaml:"control_plane_certificate_policy"`
		} `yaml:"join"`
		CNI struct {
			Enabled          bool     `yaml:"enabled"`
			Provider         string   `yaml:"provider"`
			ManifestURL      string   `yaml:"manifest_url"`
			ManifestPath     string   `yaml:"manifest_path"`
			Package          string   `yaml:"package"`
			AllowedProviders []string `yaml:"allowed_providers"`
		} `yaml:"cni"`
	} `yaml:"kubernetes"`
	Safety struct {
		AllowClusterReset           bool `yaml:"allow_cluster_reset"`
		AllowControlPlaneCertUpload bool `yaml:"allow_control_plane_cert_upload"`
		AllowUnverifiedRemotePlan   bool `yaml:"allow_unverified_remote_plan"`
		RequireJoinToken            bool `yaml:"require_join_token"`
		RequireCACertHash           bool `yaml:"require_ca_cert_hash"`
		RequireRepositorySignature  bool `yaml:"require_repository_signature"`
	} `yaml:"safety"`
}

func LoadFiles(paths []string) (Document, error) {
	merged := Document{}
	for _, path := range paths {
		if strings.TrimSpace(path) == "" {
			continue
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return nil, fmt.Errorf("read stage3 config %s: %w", path, err)
		}
		var layer Document
		decoder := yaml.NewDecoder(bytes.NewReader(data))
		decoder.KnownFields(false)
		if err := decoder.Decode(&layer); err != nil {
			return nil, fmt.Errorf("decode stage3 config %s: %w", path, err)
		}
		if installPlan, ok := asMap(layer["install_plan"]); ok {
			layer = Document(installPlan)
		}
		merged = Merge(merged, layer)
	}
	return merged, nil
}

func Merge(base, overlay Document) Document {
	result := cloneMap(base)
	for key, value := range overlay {
		if appended, ok := appendDirective(result[key], value); ok {
			result[key] = appended
			continue
		}
		baseMap, baseOK := asMap(result[key])
		overlayMap, overlayOK := asMap(value)
		if baseOK && overlayOK {
			result[key] = Merge(Document(baseMap), Document(overlayMap))
			continue
		}
		result[key] = cloneValue(value)
	}
	return result
}

func SetPath(document Document, path string, value any) error {
	parts := strings.Split(path, ".")
	if len(parts) == 0 || strings.TrimSpace(path) == "" {
		return errors.New("stage3 config path is empty")
	}
	current := map[string]any(document)
	for _, part := range parts[:len(parts)-1] {
		if part == "" {
			return fmt.Errorf("invalid stage3 config path %q", path)
		}
		next, ok := asMap(current[part])
		if !ok {
			next = map[string]any{}
			current[part] = next
		}
		current = next
	}
	current[parts[len(parts)-1]] = value
	return nil
}

func Decode(document Document) (Config, error) {
	data, err := yaml.Marshal(document)
	if err != nil {
		return Config{}, fmt.Errorf("encode merged stage3 config: %w", err)
	}
	var config Config
	if err := yaml.Unmarshal(data, &config); err != nil {
		return Config{}, fmt.Errorf("decode merged stage3 config: %w", err)
	}
	return config, nil
}

func WriteRendered(path string, document Document) error {
	if strings.TrimSpace(path) == "" {
		return errors.New("rendered stage3 plan path is empty")
	}
	redacted := redactMap(document)
	data, err := yaml.Marshal(redacted)
	if err != nil {
		return fmt.Errorf("encode rendered stage3 plan: %w", err)
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return fmt.Errorf("create rendered stage3 plan directory: %w", err)
	}
	temporary, err := os.CreateTemp(filepath.Dir(path), ".stage3-plan-*.tmp")
	if err != nil {
		return fmt.Errorf("create rendered stage3 plan: %w", err)
	}
	temporaryPath := temporary.Name()
	defer os.Remove(temporaryPath)
	if err := temporary.Chmod(0o600); err != nil {
		temporary.Close()
		return fmt.Errorf("protect rendered stage3 plan: %w", err)
	}
	if _, err := temporary.Write(data); err != nil {
		temporary.Close()
		return fmt.Errorf("write rendered stage3 plan: %w", err)
	}
	if err := temporary.Close(); err != nil {
		return fmt.Errorf("close rendered stage3 plan: %w", err)
	}
	if err := os.Rename(temporaryPath, path); err != nil {
		return fmt.Errorf("publish rendered stage3 plan: %w", err)
	}
	return nil
}

func YAMLFiles(directory string) ([]string, error) {
	entries, err := os.ReadDir(directory)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	paths := make([]string, 0, len(entries))
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		extension := strings.ToLower(filepath.Ext(entry.Name()))
		if extension == ".yaml" || extension == ".yml" {
			paths = append(paths, filepath.Join(directory, entry.Name()))
		}
	}
	sort.Strings(paths)
	return paths, nil
}

func appendDirective(base, overlay any) ([]any, bool) {
	directive, ok := asMap(overlay)
	if !ok || directive["merge_strategy"] != "append" {
		return nil, false
	}
	items, ok := directive["items"].([]any)
	if !ok {
		return nil, false
	}
	result, _ := cloneValue(base).([]any)
	result = append(result, cloneValue(items).([]any)...)
	return result, true
}

func cloneMap(input map[string]any) Document {
	result := Document{}
	for key, value := range input {
		result[key] = cloneValue(value)
	}
	return result
}

func cloneValue(value any) any {
	switch typed := value.(type) {
	case Document:
		return map[string]any(cloneMap(map[string]any(typed)))
	case map[string]any:
		return map[string]any(cloneMap(typed))
	case []any:
		result := make([]any, len(typed))
		for index, item := range typed {
			result[index] = cloneValue(item)
		}
		return result
	default:
		return value
	}
}

func redactMap(input map[string]any) Document {
	result := Document{}
	for key, value := range input {
		if isSecretKey(key) && !isEmpty(value) {
			result[key] = "<redacted>"
			continue
		}
		result[key] = redactValue(value)
	}
	return result
}

func redactValue(value any) any {
	if child, ok := asMap(value); ok {
		return map[string]any(redactMap(child))
	}
	if items, ok := value.([]any); ok {
		result := make([]any, len(items))
		for index, item := range items {
			result[index] = redactValue(item)
		}
		return result
	}
	return value
}

func asMap(value any) (map[string]any, bool) {
	switch typed := value.(type) {
	case Document:
		return map[string]any(typed), true
	case map[string]any:
		return typed, true
	default:
		return nil, false
	}
}

func isSecretKey(key string) bool {
	normalized := strings.ToLower(strings.ReplaceAll(key, "-", "_"))
	if strings.HasSuffix(normalized, "_ref") || normalized == "ca_cert_hash" || normalized == "verify_key" || normalized == "public_key" {
		return false
	}
	switch normalized {
	case "password", "token", "registration_token", "node_token", "api_key", "private_key", "certificate_key", "secret":
		return true
	default:
		return false
	}
}

func isEmpty(value any) bool {
	return value == nil || strings.TrimSpace(fmt.Sprint(value)) == ""
}
