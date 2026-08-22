package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestResolveAllowsOnlyPinnedBuilderCapabilities(t *testing.T) {
	directory := t.TempDir()
	catalog := filepath.Join(directory, "catalog.json")
	if err := os.WriteFile(catalog, []byte(`["gcc","make"]`), 0o600); err != nil {
		t.Fatal(err)
	}
	root := filepath.Join(directory, "root")
	if err := resolve(root, catalog, []string{"make", "gcc"}); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(filepath.Join(root, "build-requires.lock.json"))
	if err != nil || !strings.Contains(string(data), `"gcc"`) {
		t.Fatalf("lock file missing: %s %v", data, err)
	}
	if err := resolve(root, catalog, []string{"curl"}); err == nil || !strings.Contains(err.Error(), "not in") {
		t.Fatalf("unpinned capability accepted: %v", err)
	}
}
