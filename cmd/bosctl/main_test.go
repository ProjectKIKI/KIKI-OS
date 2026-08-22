package main

import (
	"archive/tar"
	"compress/gzip"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"example.com/aos-pkg/internal/model"
	"gopkg.in/yaml.v3"
)

func TestRepoIndexCommandGeneratesSortedIndex(t *testing.T) {
	repo := t.TempDir()
	writeBosPackage(t, filepath.Join(repo, "zeta.bos"), "manifest.yaml", "name: zeta\nversion: 2.0.0\nrelease: 3\narch: x86_64\nsummary: zeta package\ndependencies:\n  runtime:\n    - alpha\n  build:\n    - toolchain\n")
	alphaPath := filepath.Join(repo, "alpha.bos")
	writeBosPackage(t, alphaPath, "manifest.yaml", "name: alpha\nversion: 1.0.0\narch: aarch64\n")

	if err := repoIndexCommand(repo); err != nil {
		t.Fatalf("repoIndexCommand() error = %v", err)
	}

	data, err := os.ReadFile(filepath.Join(repo, "index.yaml"))
	if err != nil {
		t.Fatalf("ReadFile(index.yaml) error = %v", err)
	}

	var index RepoIndex
	if err := yaml.Unmarshal(data, &index); err != nil {
		t.Fatalf("Unmarshal(index.yaml) error = %v", err)
	}

	if len(index.Packages) != 2 {
		t.Fatalf("package count = %d, want 2", len(index.Packages))
	}
	if index.Packages[0].File != "alpha.bos" || index.Packages[1].File != "zeta.bos" {
		t.Fatalf("packages not sorted by file: %#v", index.Packages)
	}
	if index.Packages[0].Release != "1" {
		t.Fatalf("default release = %q, want 1", index.Packages[0].Release)
	}
	if index.Packages[1].Summary != "zeta package" {
		t.Fatalf("summary = %q, want zeta package", index.Packages[1].Summary)
	}
	if got := strings.Join(index.Packages[1].Dependencies.Runtime, ","); got != "alpha" {
		t.Fatalf("runtime dependencies = %q, want alpha", got)
	}
	if got := strings.Join(index.Packages[1].Dependencies.Build, ","); got != "toolchain" {
		t.Fatalf("build dependencies = %q, want toolchain", got)
	}

	wantDigest, err := calcSHA256(alphaPath)
	if err != nil {
		t.Fatalf("calcSHA256() error = %v", err)
	}
	if index.Packages[0].Digest.Algo != "sha256" || index.Packages[0].Digest.Value != wantDigest {
		t.Fatalf("digest = %s:%s, want sha256:%s", index.Packages[0].Digest.Algo, index.Packages[0].Digest.Value, wantDigest)
	}
}

func TestRepoIndexCommandRejectsInvalidManifest(t *testing.T) {
	repo := t.TempDir()
	writeBosPackage(t, filepath.Join(repo, "broken.bos"), "manifest.yaml", "name: broken\nversion: 1.0.0\n")

	err := repoIndexCommand(repo)
	if err == nil {
		t.Fatal("repoIndexCommand() invalid manifest error = nil")
	}
	if !strings.Contains(err.Error(), "arch") {
		t.Fatalf("error = %q, want missing arch", err)
	}
}

func TestResolveInstallPlanIncludesRuntimeDependencies(t *testing.T) {
	index := RepoIndex{Packages: []RepoPkg{
		{Name: "curl", Version: "8.0.0", Release: "1", Arch: "x86_64", File: "curl.bos", Dependencies: runtimeDeps("zlib")},
		{Name: "glibc", Version: "2.39", Release: "1", Arch: "x86_64", File: "glibc.bos"},
		{Name: "zlib", Version: "1.3.1", Release: "1", Arch: "x86_64", File: "zlib.bos", Dependencies: runtimeDeps("glibc")},
	}}

	plan, err := resolveInstallPlan(&index, "curl")
	if err != nil {
		t.Fatalf("resolveInstallPlan() error = %v", err)
	}
	if got := strings.Join(repoPkgNames(plan), ","); got != "glibc,zlib,curl" {
		t.Fatalf("plan = %q, want glibc,zlib,curl", got)
	}
}

func TestResolveInstallPlanRejectsMissingDependency(t *testing.T) {
	index := RepoIndex{Packages: []RepoPkg{
		{Name: "curl", Version: "8.0.0", Release: "1", Arch: "x86_64", File: "curl.bos", Dependencies: runtimeDeps("zlib")},
	}}

	err := mustPlanError(t, &index, "curl")
	if !strings.Contains(err.Error(), `package "zlib" not found`) {
		t.Fatalf("error = %q, want missing zlib", err)
	}
}

func TestResolveInstallPlanRejectsDependencyCycle(t *testing.T) {
	index := RepoIndex{Packages: []RepoPkg{
		{Name: "alpha", Version: "1.0.0", Release: "1", Arch: "x86_64", File: "alpha.bos", Dependencies: runtimeDeps("beta")},
		{Name: "beta", Version: "1.0.0", Release: "1", Arch: "x86_64", File: "beta.bos", Dependencies: runtimeDeps("alpha")},
	}}

	err := mustPlanError(t, &index, "alpha")
	if !strings.Contains(err.Error(), "dependency cycle") {
		t.Fatalf("error = %q, want dependency cycle", err)
	}
}

func TestExtractManifestRequiresTopLevelManifest(t *testing.T) {
	pkgPath := filepath.Join(t.TempDir(), "nested.bos")
	writeBosPackage(t, pkgPath, "rootfs/manifest.yaml", "name: nested\nversion: 1.0.0\narch: x86_64\n")

	if _, err := extractManifest(pkgPath); err == nil {
		t.Fatal("extractManifest() nested manifest error = nil")
	}
}

func writeBosPackage(t *testing.T, path, manifestName, manifest string) {
	t.Helper()

	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatalf("MkdirAll() error = %v", err)
	}
	f, err := os.Create(path)
	if err != nil {
		t.Fatalf("Create() error = %v", err)
	}
	defer f.Close()

	gz := gzip.NewWriter(f)
	defer gz.Close()

	tw := tar.NewWriter(gz)
	defer tw.Close()

	body := []byte(manifest)
	if err := tw.WriteHeader(&tar.Header{
		Name: manifestName,
		Mode: 0o644,
		Size: int64(len(body)),
	}); err != nil {
		t.Fatalf("WriteHeader() error = %v", err)
	}
	if _, err := tw.Write(body); err != nil {
		t.Fatalf("Write() error = %v", err)
	}
}

func runtimeDeps(names ...string) model.PackageDependencies {
	return model.PackageDependencies{Runtime: names}
}

func repoPkgNames(plan []RepoPkg) []string {
	names := make([]string, 0, len(plan))
	for _, pkg := range plan {
		names = append(names, pkg.Name)
	}
	return names
}

func mustPlanError(t *testing.T, index *RepoIndex, name string) error {
	t.Helper()

	_, err := resolveInstallPlan(index, name)
	if err == nil {
		t.Fatal("resolveInstallPlan() error = nil")
	}
	return err
}
