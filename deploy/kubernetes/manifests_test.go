package kubernetes_test

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"

	"gopkg.in/yaml.v3"
)

var pinnedImage = regexp.MustCompile(`^[^[:space:]@]+@sha256:[a-f0-9]{64}$`)

func TestBaseManifestsPreserveRuntimeAndFactoryBoundaries(t *testing.T) {
	files, err := filepath.Glob(filepath.Join("base", "*.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	var documents []map[string]any
	for _, path := range files {
		if filepath.Base(path) == "kustomization.yaml" {
			continue
		}
		data, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		decoder := yaml.NewDecoder(strings.NewReader(string(data)))
		for {
			var document map[string]any
			if err := decoder.Decode(&document); err != nil {
				if errors.Is(err, io.EOF) {
					break
				}
				t.Fatalf("parse %s: %v", path, err)
			}
			if len(document) > 0 {
				documents = append(documents, document)
			}
		}
	}
	if len(documents) < 8 {
		t.Fatalf("too few deployment resources: %d", len(documents))
	}
	for _, document := range documents {
		kind, _ := document["kind"].(string)
		encoded, _ := yaml.Marshal(document)
		text := string(encoded)
		if strings.Contains(text, "kiki-image-factory") {
			t.Fatalf("Image Factory leaked into normal-node manifests: %s", kind)
		}
		if kind == "ClusterRole" && (strings.Contains(text, "- '*'\n") || strings.Contains(text, "resources: ['*']")) {
			t.Fatal("wildcard RBAC is forbidden")
		}
		if kind == "Deployment" || kind == "DaemonSet" {
			for _, line := range strings.Split(text, "\n") {
				line = strings.TrimSpace(line)
				if strings.HasPrefix(line, "image: ") && !pinnedImage.MatchString(strings.Trim(strings.TrimPrefix(line, "image: "), `"'`)) {
					t.Fatalf("mutable image in %s: %s", kind, line)
				}
			}
		}
	}
}
