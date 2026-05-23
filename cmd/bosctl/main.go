package main

import (
	"archive/tar"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"path"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"example.com/aos-pkg/internal/model"
	"example.com/aos-pkg/internal/store"
	"gopkg.in/yaml.v3"
)

const (
	bosSubdir  = ".bosctl"
	bosDBFile  = "bosdb.json"
	appVersion = "0.0.3"
)

func usage() {
	fmt.Println("bosctl - BaseOS package manager (v" + appVersion + ")")
	fmt.Println()
	fmt.Println("Usage:")
	fmt.Println("  bosctl init")
	fmt.Println("  bosctl add <name> <version> <arch> <summary> [release] [--deps a,b] [--build-deps a,b]")
	fmt.Println("  bosctl list")
	fmt.Println("  bosctl info <name>")
	fmt.Println("  bosctl remove <name>")
	fmt.Println("  bosctl repo-index <repo-path>")
	fmt.Println("  bosctl plan <repo-path|index.yaml> <name>")
}

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(1)
	}

	cmd := os.Args[1]

	dbPath, err := store.DefaultPath(bosSubdir, bosDBFile)
	if err != nil {
		fmt.Println("error: cannot determine db path:", err)
		os.Exit(1)
	}
	st := store.NewStore[model.BosPackage](dbPath)

	switch cmd {
	case "init":
		if err := st.Init(); err != nil {
			fmt.Println("error: init db:", err)
			os.Exit(1)
		}
		fmt.Println("bosctl: initialized db at", dbPath)

	case "add":
		if len(os.Args) < 6 {
			fmt.Println("error: missing arguments for add")
			fmt.Println("usage: bosctl add <name> <version> <arch> <summary> [release] [--deps a,b] [--build-deps a,b]")
			os.Exit(1)
		}
		name := os.Args[2]
		version := os.Args[3]
		arch := os.Args[4]
		summary := os.Args[5]
		release, deps, err := parseAddOptions(os.Args[6:])
		if err != nil {
			fmt.Println("error:", err)
			os.Exit(1)
		}
		if dependencyListContains(deps.Runtime, name) || dependencyListContains(deps.Build, name) {
			fmt.Println("error: package cannot depend on itself:", name)
			os.Exit(1)
		}

		if err := st.Load(); err != nil {
			fmt.Println("error: load db:", err)
			os.Exit(1)
		}

		pkg := model.BosPackage{
			Name:         name,
			Version:      version,
			Arch:         arch,
			Summary:      summary,
			Release:      release,
			Dependencies: deps,
		}
		if err := st.Add(pkg); err != nil {
			fmt.Println("error:", err)
			os.Exit(1)
		}
		fmt.Println("bosctl: added package", name)

	case "list":
		if err := st.Load(); err != nil {
			fmt.Println("error: load db:", err)
			os.Exit(1)
		}
		pkgs := st.List()
		if len(pkgs) == 0 {
			fmt.Println("no BOS packages in local DB")
			return
		}
		fmt.Println("Installed BOS packages:")
		for _, p := range pkgs {
			fmt.Printf("  %s %s-%s (%s) - %s\n", p.Name, p.Version, p.Release, p.Arch, p.Summary)
			if len(p.Dependencies.Runtime) > 0 {
				fmt.Printf("    runtime deps: %s\n", strings.Join(p.Dependencies.Runtime, ", "))
			}
		}

	case "info":
		if len(os.Args) < 3 {
			fmt.Println("error: missing package name")
			fmt.Println("usage: bosctl info <name>")
			os.Exit(1)
		}
		name := os.Args[2]

		if err := st.Load(); err != nil {
			fmt.Println("error: load db:", err)
			os.Exit(1)
		}

		p, ok := st.Find(name)
		if !ok {
			fmt.Println("package not found:", name)
			os.Exit(1)
		}
		fmt.Println("Name   :", p.Name)
		fmt.Println("Version:", p.Version)
		fmt.Println("Release:", p.Release)
		fmt.Println("Arch   :", p.Arch)
		fmt.Println("Summary:", p.Summary)
		printDependencyInfo("Runtime deps", p.Dependencies.Runtime)
		printDependencyInfo("Build deps  ", p.Dependencies.Build)
		fmt.Println("DB Path:", dbPath)

	case "remove":
		if len(os.Args) < 3 {
			fmt.Println("error: missing package name")
			fmt.Println("usage: bosctl remove <name>")
			os.Exit(1)
		}
		name := os.Args[2]

		if err := st.Load(); err != nil {
			fmt.Println("error: load db:", err)
			os.Exit(1)
		}
		if err := st.Remove(name); err != nil {
			fmt.Println("error:", err)
			os.Exit(1)
		}
		fmt.Println("bosctl: removed package", name)

	case "repo-index":
		if len(os.Args) < 3 {
			fmt.Println("usage: bosctl repo-index <repo-path>")
			os.Exit(1)
		}
		repoPath := os.Args[2]
		if err := repoIndexCommand(repoPath); err != nil {
			fmt.Println("error:", err)
			os.Exit(1)
		}
		fmt.Println("bosctl: generated index.yaml in", repoPath)

	case "plan":
		if len(os.Args) < 4 {
			fmt.Println("usage: bosctl plan <repo-path|index.yaml> <name>")
			os.Exit(1)
		}
		index, err := loadRepoIndex(os.Args[2])
		if err != nil {
			fmt.Println("error:", err)
			os.Exit(1)
		}
		plan, err := resolveInstallPlan(index, os.Args[3])
		if err != nil {
			fmt.Println("error:", err)
			os.Exit(1)
		}
		printInstallPlan(os.Args[3], plan)

	default:
		fmt.Println("error: unknown command:", cmd)
		usage()
		os.Exit(1)
	}
}

func parseAddOptions(args []string) (string, model.PackageDependencies, error) {
	release := "1"
	if len(args) > 0 && !strings.HasPrefix(args[0], "--") {
		release = strings.TrimSpace(args[0])
		args = args[1:]
	}
	if release == "" {
		release = "1"
	}

	var deps model.PackageDependencies
	for i := 0; i < len(args); i++ {
		arg := args[i]
		switch {
		case arg == "--deps" || arg == "--runtime-deps":
			i++
			if i >= len(args) {
				return "", deps, fmt.Errorf("%s requires a comma-separated value", arg)
			}
			deps.Runtime = append(deps.Runtime, parseDependencyCSV(args[i])...)
		case strings.HasPrefix(arg, "--deps="):
			deps.Runtime = append(deps.Runtime, parseDependencyCSV(strings.TrimPrefix(arg, "--deps="))...)
		case strings.HasPrefix(arg, "--runtime-deps="):
			deps.Runtime = append(deps.Runtime, parseDependencyCSV(strings.TrimPrefix(arg, "--runtime-deps="))...)
		case arg == "--build-deps":
			i++
			if i >= len(args) {
				return "", deps, fmt.Errorf("%s requires a comma-separated value", arg)
			}
			deps.Build = append(deps.Build, parseDependencyCSV(args[i])...)
		case strings.HasPrefix(arg, "--build-deps="):
			deps.Build = append(deps.Build, parseDependencyCSV(strings.TrimPrefix(arg, "--build-deps="))...)
		default:
			return "", deps, fmt.Errorf("unknown add option %q", arg)
		}
	}
	deps.Normalize()
	return release, deps, nil
}

func parseDependencyCSV(value string) []string {
	if value == "" {
		return nil
	}
	return strings.Split(value, ",")
}

func dependencyListContains(deps []string, name string) bool {
	name = strings.TrimSpace(name)
	for _, dep := range deps {
		if strings.TrimSpace(dep) == name {
			return true
		}
	}
	return false
}

func printDependencyInfo(label string, deps []string) {
	if len(deps) == 0 {
		fmt.Println(label+":", "(none)")
		return
	}
	fmt.Println(label+":", strings.Join(deps, ", "))
}

// Manifest describes the minimal fields needed from manifest.yaml.
type Manifest struct {
	Name         string                    `yaml:"name"`
	Version      string                    `yaml:"version"`
	Release      string                    `yaml:"release"`
	Arch         string                    `yaml:"arch"`
	Summary      string                    `yaml:"summary,omitempty"`
	Dependencies model.PackageDependencies `yaml:"dependencies,omitempty"`
}

func (m *Manifest) normalize() {
	m.Name = strings.TrimSpace(m.Name)
	m.Version = strings.TrimSpace(m.Version)
	m.Release = strings.TrimSpace(m.Release)
	m.Arch = strings.TrimSpace(m.Arch)
	m.Summary = strings.TrimSpace(m.Summary)
	m.Dependencies.Normalize()
	if m.Release == "" {
		m.Release = "1"
	}
}

func (m Manifest) validate() error {
	var missing []string
	if m.Name == "" {
		missing = append(missing, "name")
	}
	if m.Version == "" {
		missing = append(missing, "version")
	}
	if m.Arch == "" {
		missing = append(missing, "arch")
	}
	if len(missing) > 0 {
		return fmt.Errorf("manifest.yaml missing required field(s): %s", strings.Join(missing, ", "))
	}
	if dependencyListContains(m.Dependencies.Runtime, m.Name) || dependencyListContains(m.Dependencies.Build, m.Name) {
		return fmt.Errorf("manifest.yaml dependency references package itself: %s", m.Name)
	}
	return nil
}

// RepoIndex is the structure of index.yaml for BOS repos.
type RepoIndex struct {
	Repo struct {
		Name    string `yaml:"name"`
		Version int    `yaml:"version"`
		Created string `yaml:"created"`
	} `yaml:"repo"`
	Packages []RepoPkg `yaml:"packages"`
}

type RepoPkg struct {
	Name         string                    `yaml:"name"`
	Version      string                    `yaml:"version"`
	Release      string                    `yaml:"release"`
	Arch         string                    `yaml:"arch"`
	Summary      string                    `yaml:"summary,omitempty"`
	Dependencies model.PackageDependencies `yaml:"dependencies,omitempty"`
	File         string                    `yaml:"file"`
	Digest       struct {
		Algo  string `yaml:"algo"`
		Value string `yaml:"value"`
	} `yaml:"digest"`
}

// repoIndexCommand scans repoPath for .bos files and generates index.yaml.
func repoIndexCommand(repoPath string) error {
	entries, err := os.ReadDir(repoPath)
	if err != nil {
		return fmt.Errorf("cannot read repo path: %w", err)
	}

	var index RepoIndex
	index.Repo.Name = "AOS BOS Repository"
	index.Repo.Version = 1
	index.Repo.Created = time.Now().UTC().Format(time.RFC3339)

	for _, e := range entries {
		if e.IsDir() || filepath.Ext(e.Name()) != ".bos" {
			continue
		}

		bosFile := filepath.Join(repoPath, e.Name())

		digest, err := calcSHA256(bosFile)
		if err != nil {
			return fmt.Errorf("calc sha256 for %s: %w", e.Name(), err)
		}

		man, err := extractManifest(bosFile)
		if err != nil {
			return fmt.Errorf("extract manifest from %s: %w", e.Name(), err)
		}
		man.normalize()
		if err := man.validate(); err != nil {
			return fmt.Errorf("invalid manifest in %s: %w", e.Name(), err)
		}

		var pkg RepoPkg
		pkg.Name = man.Name
		pkg.Version = man.Version
		pkg.Release = man.Release
		pkg.Arch = man.Arch
		pkg.Summary = man.Summary
		pkg.Dependencies = man.Dependencies
		pkg.File = e.Name()
		pkg.Digest.Algo = "sha256"
		pkg.Digest.Value = digest

		index.Packages = append(index.Packages, pkg)
	}

	sort.Slice(index.Packages, func(i, j int) bool {
		return index.Packages[i].File < index.Packages[j].File
	})

	outPath := filepath.Join(repoPath, "index.yaml")
	data, err := yaml.Marshal(&index)
	if err != nil {
		return fmt.Errorf("marshal index.yaml: %w", err)
	}
	if err := os.WriteFile(outPath, data, 0o644); err != nil {
		return fmt.Errorf("write index.yaml: %w", err)
	}
	return nil
}

func loadRepoIndex(repoRef string) (*RepoIndex, error) {
	indexPath := repoRef
	info, err := os.Stat(repoRef)
	if err != nil {
		return nil, fmt.Errorf("cannot stat repo index path: %w", err)
	}
	if info.IsDir() {
		indexPath = filepath.Join(repoRef, "index.yaml")
	}

	data, err := os.ReadFile(indexPath)
	if err != nil {
		return nil, fmt.Errorf("read index.yaml: %w", err)
	}
	var index RepoIndex
	if err := yaml.Unmarshal(data, &index); err != nil {
		return nil, fmt.Errorf("parse index.yaml: %w", err)
	}
	for i := range index.Packages {
		index.Packages[i].Name = strings.TrimSpace(index.Packages[i].Name)
		index.Packages[i].Version = strings.TrimSpace(index.Packages[i].Version)
		index.Packages[i].Release = strings.TrimSpace(index.Packages[i].Release)
		index.Packages[i].Arch = strings.TrimSpace(index.Packages[i].Arch)
		index.Packages[i].Dependencies.Normalize()
	}
	return &index, nil
}

func resolveInstallPlan(index *RepoIndex, name string) ([]RepoPkg, error) {
	name = strings.TrimSpace(name)
	if name == "" {
		return nil, fmt.Errorf("package name is required")
	}

	byName := make(map[string]RepoPkg, len(index.Packages))
	for _, pkg := range index.Packages {
		pkg.Name = strings.TrimSpace(pkg.Name)
		pkg.Dependencies.Normalize()
		if pkg.Name == "" {
			return nil, fmt.Errorf("repository index contains a package with empty name")
		}
		if _, exists := byName[pkg.Name]; exists {
			return nil, fmt.Errorf("repository index contains duplicate package %q", pkg.Name)
		}
		byName[pkg.Name] = pkg
	}

	visiting := map[string]bool{}
	visited := map[string]bool{}
	var plan []RepoPkg

	var visit func(string, []string) error
	visit = func(pkgName string, stack []string) error {
		pkgName = strings.TrimSpace(pkgName)
		if visited[pkgName] {
			return nil
		}
		if visiting[pkgName] {
			cycle := append(stack, pkgName)
			return fmt.Errorf("dependency cycle: %s", strings.Join(cycle, " -> "))
		}

		pkg, ok := byName[pkgName]
		if !ok {
			return fmt.Errorf("package %q not found in repository index", pkgName)
		}

		visiting[pkgName] = true
		for _, dep := range pkg.Dependencies.Runtime {
			if err := visit(dep, append(stack, pkgName)); err != nil {
				return err
			}
		}
		visiting[pkgName] = false
		visited[pkgName] = true
		plan = append(plan, pkg)
		return nil
	}

	if err := visit(name, nil); err != nil {
		return nil, err
	}
	return plan, nil
}

func printInstallPlan(name string, plan []RepoPkg) {
	fmt.Printf("Install plan for %s (%d package(s)):\n", name, len(plan))
	for i, pkg := range plan {
		fmt.Printf("  %02d. %s %s-%s (%s) %s\n", i+1, pkg.Name, pkg.Version, pkg.Release, pkg.Arch, pkg.File)
	}
}

func calcSHA256(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()

	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

// extractManifest pulls the top-level manifest.yaml out of a .bos tar.gz.
func extractManifest(bosPath string) (*Manifest, error) {
	f, err := os.Open(bosPath)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	gz, err := gzip.NewReader(f)
	if err != nil {
		return nil, err
	}
	defer gz.Close()

	tr := tar.NewReader(gz)

	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, err
		}
		if !hdr.FileInfo().Mode().IsRegular() {
			continue
		}

		if path.Clean(hdr.Name) == "manifest.yaml" {
			data, err := io.ReadAll(io.LimitReader(tr, 1<<20))
			if err != nil {
				return nil, err
			}
			var m Manifest
			if err := yaml.Unmarshal(data, &m); err != nil {
				return nil, err
			}
			return &m, nil
		}
	}

	return nil, fmt.Errorf("manifest.yaml not found in %s", bosPath)
}
