package crds

import (
	"io"
	"os"
	"path/filepath"
	"testing"

	"gopkg.in/yaml.v3"
)

func TestCRDManifestsParse(t *testing.T) {
	paths, err := filepath.Glob("*.yaml")
	if err != nil {
		t.Fatal(err)
	}
	if len(paths) == 0 {
		t.Fatal("no CRD manifests found")
	}
	for _, path := range paths {
		t.Run(path, func(t *testing.T) {
			file, err := os.Open(path)
			if err != nil {
				t.Fatal(err)
			}
			defer file.Close()
			decoder := yaml.NewDecoder(file)
			for document := 0; ; document++ {
				var manifest map[string]any
				err := decoder.Decode(&manifest)
				if err == io.EOF {
					break
				}
				if err != nil {
					t.Fatalf("document %d: %v", document, err)
				}
				if manifest["apiVersion"] == "" || manifest["kind"] != "CustomResourceDefinition" {
					t.Fatalf("document %d is not a CRD", document)
				}
				metadata, ok := manifest["metadata"].(map[string]any)
				if !ok || metadata["name"] == "" {
					t.Fatalf("document %d has no metadata.name", document)
				}
				spec, ok := manifest["spec"].(map[string]any)
				if !ok || spec["group"] == "" || spec["versions"] == nil {
					t.Fatalf("document %d has incomplete spec", document)
				}
			}
		})
	}
}
