package bosrecipe

import (
	"archive/tar"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"example.com/aos-pkg/internal/buildsystem"
	"gopkg.in/yaml.v3"
)

const maxSourceBytes int64 = 2 << 30
const maxExtractedBytes int64 = 8 << 30

type Runner interface {
	Run(context.Context, string, []string, string, []string) error
}

type ExecRunner struct{}

func (ExecRunner) Run(ctx context.Context, name string, args []string, directory string, environment []string) error {
	command := exec.CommandContext(ctx, name, args...)
	command.Dir = directory
	command.Env = append(os.Environ(), environment...)
	command.Stdout = os.Stdout
	command.Stderr = os.Stderr
	return command.Run()
}

type Options struct {
	Recipe         buildsystem.BOSRecipe
	Output         string
	WorkspaceRoot  string
	PackagerPath   string
	DependencyPath string
	HTTPClient     *http.Client
	Runner         Runner
}

func Build(ctx context.Context, options Options) error {
	if options.Output == "" || filepath.Ext(options.Output) != ".bos" {
		return errors.New("output must be a .bos file")
	}
	if options.WorkspaceRoot == "" {
		options.WorkspaceRoot = "/workspace"
	}
	if options.PackagerPath == "" {
		options.PackagerPath = "/usr/local/bin/bosbuild"
	}
	if options.DependencyPath == "" {
		options.DependencyPath = "/usr/local/bin/kiki-bos-deps"
	}
	if options.Runner == nil {
		options.Runner = ExecRunner{}
	}
	workspace, err := os.MkdirTemp(options.WorkspaceRoot, "bos-recipe-")
	if err != nil {
		return fmt.Errorf("create recipe workspace: %w", err)
	}
	defer os.RemoveAll(workspace)

	archivePath := filepath.Join(workspace, "source.tar.gz")
	if err := downloadSource(ctx, options.HTTPClient, options.Recipe.SourceURL, options.Recipe.SourceSHA256, archivePath); err != nil {
		return err
	}
	sourceRoot := filepath.Join(workspace, "source")
	if err := extractTarGz(archivePath, sourceRoot); err != nil {
		return err
	}
	commandRoot, err := effectiveSourceRoot(sourceRoot)
	if err != nil {
		return err
	}
	packageRoot := filepath.Join(workspace, "package")
	destdir := filepath.Join(packageRoot, "rootfs")
	builddir := filepath.Join(workspace, "build")
	for _, directory := range []string{destdir, builddir} {
		if err := os.MkdirAll(directory, 0o750); err != nil {
			return err
		}
	}
	environment := []string{"SOURCE_DIR=" + commandRoot, "BUILD_DIR=" + builddir, "DESTDIR=" + destdir, "HOME=" + filepath.Join(workspace, "home")}
	if len(options.Recipe.BuildRequires) > 0 {
		args := append([]string{"--root", filepath.Join(workspace, "buildroot"), "--"}, options.Recipe.BuildRequires...)
		if err := options.Runner.Run(ctx, options.DependencyPath, args, workspace, environment); err != nil {
			return fmt.Errorf("resolve build dependencies: %w", err)
		}
	}
	for _, phase := range []struct {
		name     string
		commands []string
	}{{"prepare", options.Recipe.Prepare}, {"build", options.Recipe.Build}, {"install", options.Recipe.Install}, {"check", options.Recipe.Check}} {
		for index, script := range phase.commands {
			if err := options.Runner.Run(ctx, "/bin/sh", []string{"-eu", "-c", script}, commandRoot, environment); err != nil {
				return fmt.Errorf("%s command %d failed: %w", phase.name, index+1, err)
			}
		}
	}
	if err := verifyInstalledFiles(destdir, options.Recipe.Files); err != nil {
		return err
	}
	if err := writeManifest(filepath.Join(packageRoot, "manifest.yaml"), options.Recipe); err != nil {
		return err
	}
	if err := options.Runner.Run(ctx, options.PackagerPath, []string{"-C", packageRoot, "-o", options.Output}, workspace, environment); err != nil {
		return fmt.Errorf("package BOS artifact: %w", err)
	}
	return nil
}

func downloadSource(ctx context.Context, client *http.Client, rawURL, wantDigest, output string) error {
	parsed, err := url.Parse(rawURL)
	if err != nil || parsed.Scheme != "https" || parsed.Host == "" || parsed.User != nil {
		return errors.New("recipe source must be a credential-free HTTPS URL")
	}
	if len(wantDigest) != 64 {
		return errors.New("recipe source requires a SHA-256 digest")
	}
	if client == nil {
		originalHost := parsed.Hostname()
		client = &http.Client{Timeout: 30 * time.Minute, CheckRedirect: func(request *http.Request, via []*http.Request) error {
			if request.URL.Scheme != "https" || !strings.EqualFold(request.URL.Hostname(), originalHost) {
				return errors.New("recipe source redirect changed scheme or host")
			}
			if len(via) >= 5 {
				return errors.New("too many recipe source redirects")
			}
			return nil
		}}
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, rawURL, nil)
	if err != nil {
		return err
	}
	response, err := client.Do(request)
	if err != nil {
		return fmt.Errorf("download recipe source: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("download recipe source returned %s", response.Status)
	}
	file, err := os.OpenFile(output, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	hash := sha256.New()
	written, copyErr := io.Copy(io.MultiWriter(file, hash), io.LimitReader(response.Body, maxSourceBytes+1))
	closeErr := file.Close()
	if copyErr != nil {
		return copyErr
	}
	if closeErr != nil {
		return closeErr
	}
	if written > maxSourceBytes {
		return errors.New("recipe source exceeds 2 GiB")
	}
	if hex.EncodeToString(hash.Sum(nil)) != strings.ToLower(wantDigest) {
		return errors.New("recipe source SHA-256 mismatch")
	}
	return nil
}

func extractTarGz(archivePath, destination string) error {
	file, err := os.Open(archivePath)
	if err != nil {
		return err
	}
	defer file.Close()
	gzipReader, err := gzip.NewReader(file)
	if err != nil {
		return fmt.Errorf("source is not a tar.gz archive: %w", err)
	}
	defer gzipReader.Close()
	if err := os.MkdirAll(destination, 0o750); err != nil {
		return err
	}
	tarReader := tar.NewReader(gzipReader)
	var extracted int64
	for {
		header, err := tarReader.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return fmt.Errorf("read source archive: %w", err)
		}
		clean := filepath.Clean(filepath.FromSlash(header.Name))
		if clean == "." {
			continue
		}
		if filepath.IsAbs(clean) || clean == ".." || strings.HasPrefix(clean, ".."+string(filepath.Separator)) {
			return errors.New("source archive contains a path traversal")
		}
		target := filepath.Join(destination, clean)
		switch header.Typeflag {
		case tar.TypeDir:
			if err := os.MkdirAll(target, 0o750); err != nil {
				return err
			}
		case tar.TypeReg, tar.TypeRegA:
			if header.Size < 0 || header.Size > maxSourceBytes {
				return errors.New("source archive member is too large")
			}
			extracted += header.Size
			if extracted > maxExtractedBytes {
				return errors.New("expanded recipe source exceeds 8 GiB")
			}
			if err := os.MkdirAll(filepath.Dir(target), 0o750); err != nil {
				return err
			}
			mode := os.FileMode(header.Mode) & 0o777
			mode &^= 0o6000
			output, err := os.OpenFile(target, os.O_CREATE|os.O_EXCL|os.O_WRONLY, mode)
			if err != nil {
				return err
			}
			_, copyErr := io.CopyN(output, tarReader, header.Size)
			closeErr := output.Close()
			if copyErr != nil {
				return copyErr
			}
			if closeErr != nil {
				return closeErr
			}
		default:
			return fmt.Errorf("source archive contains unsupported entry %q", header.Name)
		}
	}
	return nil
}

func effectiveSourceRoot(root string) (string, error) {
	entries, err := os.ReadDir(root)
	if err != nil {
		return "", err
	}
	if len(entries) == 1 && entries[0].IsDir() {
		return filepath.Join(root, entries[0].Name()), nil
	}
	return root, nil
}

func verifyInstalledFiles(destdir string, files []string) error {
	declared := make(map[string]bool, len(files))
	for _, name := range files {
		clean := filepath.Clean(filepath.FromSlash(strings.TrimPrefix(name, "/")))
		if clean == "." || clean == ".." || strings.HasPrefix(clean, ".."+string(filepath.Separator)) {
			return fmt.Errorf("invalid installed file %q", name)
		}
		if _, err := os.Lstat(filepath.Join(destdir, clean)); err != nil {
			return fmt.Errorf("declared file %q was not installed: %w", name, err)
		}
		declared[filepath.ToSlash(clean)] = true
	}
	return filepath.WalkDir(destdir, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if entry.IsDir() {
			return nil
		}
		relative, err := filepath.Rel(destdir, path)
		if err != nil {
			return err
		}
		if !declared[filepath.ToSlash(relative)] {
			return fmt.Errorf("installed file %q is not declared in the BOS file list", "/"+filepath.ToSlash(relative))
		}
		return nil
	})
}

func writeManifest(path string, recipe buildsystem.BOSRecipe) error {
	manifest := struct {
		Name         string   `yaml:"name"`
		Version      string   `yaml:"version"`
		Release      string   `yaml:"release"`
		Arch         string   `yaml:"arch"`
		Summary      string   `yaml:"summary"`
		Description  string   `yaml:"description,omitempty"`
		License      string   `yaml:"license"`
		Source       string   `yaml:"source"`
		SourceSHA256 string   `yaml:"source_sha256"`
		Requires     []string `yaml:"requires,omitempty"`
		Files        []string `yaml:"files"`
	}{recipe.Name, recipe.Version, recipe.Release, recipe.Arch, recipe.Summary, recipe.Description, recipe.License, recipe.SourceURL, recipe.SourceSHA256, recipe.Requires, append([]string(nil), recipe.Files...)}
	sort.Strings(manifest.Requires)
	sort.Strings(manifest.Files)
	data, err := yaml.Marshal(manifest)
	if err != nil {
		return err
	}
	return os.WriteFile(path, data, 0o640)
}
