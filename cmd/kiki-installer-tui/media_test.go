package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestMediaPreviewBlocksMissingTransitivePackage(t *testing.T) {
	plan := NewDefaultPlan("desktop-gnome")
	plan.Source.RepoIndex = filepath.Join(t.TempDir(), "index.json")
	plan.Packages.Selected = []string{"desktop"}
	write := func(text string) {
		t.Helper()
		if err := os.WriteFile(plan.Source.RepoIndex, []byte(text), 0600); err != nil {
			t.Fatal(err)
		}
	}
	write(`{"arch":"x86_64","packages":[{"name":"desktop","size":20,"dependencies":{"runtime":["renderer"]}}]}`)
	if check := checkProfile(plan); check.State != "BLOCK" || !strings.Contains(check.Summary, "renderer") {
		t.Fatal(check)
	}
	write(`{"arch":"x86_64","packages":[{"name":"desktop","size":20,"dependencies":{"runtime":["renderer"]}},{"name":"renderer","size":10,"dependencies":{"runtime":[]}}]}`)
	count, size, err := previewLocalPackages(plan)
	if err != nil || count != 2 || size != 30 {
		t.Fatalf("%d %d %v", count, size, err)
	}
	if check := checkProfile(plan); check.State != "OK" {
		t.Fatal(check)
	}
	write(`{"arch":"x86_64","packages":[{"name":"desktop","size":20,"dependencies":{"runtime":["desktop"]}}]}`)
	if check := checkProfile(plan); check.State != "BLOCK" {
		t.Fatal(check)
	}
}

func TestOverlappingGroupsRetainDependencies(t *testing.T) {
	plan := NewDefaultPlan("server-core")
	if err := applyPackageGroup(&plan, "kubernetes-node", true); err != nil {
		t.Fatal(err)
	}
	if err := applyPackageGroup(&plan, "server", false); err != nil {
		t.Fatal(err)
	}
	if !contains(plan.Packages.Selected, "chrony") || !contains(plan.Services.Enable, "chronyd.service") {
		t.Fatal("shared group dependency removed")
	}
}
