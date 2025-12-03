    package main

    import (
        "archive/tar"
        "compress/gzip"
        "crypto/sha256"
        "encoding/hex"
        "fmt"
        "io"
        "os"
        "path/filepath"
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
        fmt.Println("  bosctl add <name> <version> <arch> <summary> [release]")
        fmt.Println("  bosctl list")
        fmt.Println("  bosctl info <name>")
        fmt.Println("  bosctl repo-index <repo-path>")
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
                fmt.Println("usage: bosctl add <name> <version> <arch> <summary> [release]")
                os.Exit(1)
            }
            name := os.Args[2]
            version := os.Args[3]
            arch := os.Args[4]
            summary := os.Args[5]
            release := "1"
            if len(os.Args) >= 7 {
                release = os.Args[6]
            }

            if err := st.Load(); err != nil {
                fmt.Println("error: load db:", err)
                os.Exit(1)
            }

            pkg := model.BosPackage{
                Name:    name,
                Version: version,
                Arch:    arch,
                Summary: summary,
                Release: release,
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
                fmt.Printf("  %s %s-%s (%s) - %s
", p.Name, p.Version, p.Release, p.Arch, p.Summary)
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
            fmt.Println("DB Path:", dbPath)

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

        default:
            fmt.Println("error: unknown command:", cmd)
            usage()
            os.Exit(1)
        }
    }

    // Manifest describes the minimal fields we need from manifest.yaml
    type Manifest struct {
        Name    string `yaml:"name"`
        Version string `yaml:"version"`
        Release string `yaml:"release"`
        Arch    string `yaml:"arch"`
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
        Name    string `yaml:"name"`
        Version string `yaml:"version"`
        Release string `yaml:"release"`
        Arch    string `yaml:"arch"`
        File    string `yaml:"file"`
        Digest  struct {
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
            if e.IsDir() {
                continue
            }
            if filepath.Ext(e.Name()) != ".bos" {
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

            if man.Release == "" {
                man.Release = "1"
            }

            var pkg RepoPkg
            pkg.Name = man.Name
            pkg.Version = man.Version
            pkg.Release = man.Release
            pkg.Arch = man.Arch
            pkg.File = e.Name()
            pkg.Digest.Algo = "sha256"
            pkg.Digest.Value = digest

            index.Packages = append(index.Packages, pkg)
        }

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

    // extractManifest pulls manifest.yaml out of a .bos tar.gz.
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

            // support both "manifest.yaml" and "./manifest.yaml"
            if filepath.Base(hdr.Name) == "manifest.yaml" {
                data, err := io.ReadAll(tr)
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
