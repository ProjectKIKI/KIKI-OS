package main

import (
	"archive/tar"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"gopkg.in/yaml.v3"
)

const appVersion = "0.0.3"

var packageNamePattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._+-]*$`)

type manifest struct {
	Name    string `yaml:"name"`
	Version string `yaml:"version"`
	Release string `yaml:"release"`
	Arch    string `yaml:"arch"`
}

type buildResult struct {
	Path   string
	SHA256 string
	Size   int64
}

func usage() {
	fmt.Println("bosbuild - AOS BOS package builder (v" + appVersion + ")")
	fmt.Println()
	fmt.Println("Usage:")
	fmt.Println("  bosbuild -C <workdir> -o <output.bos>")
	fmt.Println()
	fmt.Println("Options:")
	fmt.Println("  -C   작업 디렉터리 (manifest.yaml, rootfs/, scripts/ 포함)")
	fmt.Println("  -o   출력 BOS 패키지 파일 이름 (*.bos)")
}

func main() {
	workdir := flag.String("C", "", "작업 디렉터리 (manifest.yaml, rootfs/, scripts/ 포함)")
	output := flag.String("o", "", "출력 BOS 패키지 파일 (*.bos)")
	flag.Usage = usage
	flag.Parse()

	if *workdir == "" || *output == "" {
		usage()
		os.Exit(1)
	}

	result, err := buildBos(*workdir, *output)
	if err != nil {
		fmt.Println("error:", err)
		os.Exit(1)
	}

	fmt.Printf("bosbuild: created %s\nsha256: %s\nsize: %d\n", result.Path, result.SHA256, result.Size)
}

func buildBos(workdir, output string) (buildResult, error) {
	root, err := filepath.Abs(workdir)
	if err != nil {
		return buildResult{}, fmt.Errorf("resolve workdir: %w", err)
	}
	rootInfo, err := os.Stat(root)
	if err != nil {
		return buildResult{}, fmt.Errorf("stat workdir: %w", err)
	}
	if !rootInfo.IsDir() {
		return buildResult{}, errors.New("workdir must be a directory")
	}

	outputPath, err := filepath.Abs(output)
	if err != nil {
		return buildResult{}, fmt.Errorf("resolve output: %w", err)
	}
	if filepath.Ext(outputPath) != ".bos" {
		return buildResult{}, errors.New("output must have a .bos extension")
	}
	if pathWithin(root, outputPath) {
		return buildResult{}, errors.New("output must be outside the build workdir")
	}

	if _, err := loadManifest(filepath.Join(root, "manifest.yaml")); err != nil {
		return buildResult{}, err
	}

	entries, err := collectEntries(root)
	if err != nil {
		return buildResult{}, err
	}
	if err := os.MkdirAll(filepath.Dir(outputPath), 0o755); err != nil {
		return buildResult{}, fmt.Errorf("create output directory: %w", err)
	}

	temporary, err := os.CreateTemp(filepath.Dir(outputPath), ".bosbuild-*.tmp")
	if err != nil {
		return buildResult{}, fmt.Errorf("create temporary output: %w", err)
	}
	temporaryPath := temporary.Name()
	committed := false
	defer func() {
		_ = temporary.Close()
		if !committed {
			_ = os.Remove(temporaryPath)
		}
	}()

	hash := sha256.New()
	if err := writeArchive(io.MultiWriter(temporary, hash), root, entries); err != nil {
		return buildResult{}, err
	}
	if err := temporary.Sync(); err != nil {
		return buildResult{}, fmt.Errorf("sync output: %w", err)
	}
	info, err := temporary.Stat()
	if err != nil {
		return buildResult{}, fmt.Errorf("stat output: %w", err)
	}
	if err := temporary.Close(); err != nil {
		return buildResult{}, fmt.Errorf("close output: %w", err)
	}
	if err := os.Rename(temporaryPath, outputPath); err != nil {
		return buildResult{}, fmt.Errorf("commit output: %w", err)
	}
	committed = true

	return buildResult{Path: outputPath, SHA256: hex.EncodeToString(hash.Sum(nil)), Size: info.Size()}, nil
}

func loadManifest(path string) (manifest, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return manifest{}, fmt.Errorf("read manifest.yaml: %w", err)
	}
	var value manifest
	if err := yaml.Unmarshal(data, &value); err != nil {
		return manifest{}, fmt.Errorf("parse manifest.yaml: %w", err)
	}
	value.Name = strings.TrimSpace(value.Name)
	value.Version = strings.TrimSpace(value.Version)
	value.Release = strings.TrimSpace(value.Release)
	value.Arch = strings.TrimSpace(value.Arch)
	if value.Name == "" || value.Version == "" || value.Arch == "" {
		return manifest{}, errors.New("manifest.yaml requires name, version, and arch")
	}
	if !packageNamePattern.MatchString(value.Name) {
		return manifest{}, errors.New("manifest name contains unsupported characters")
	}
	for field, value := range map[string]string{"version": value.Version, "release": value.Release, "arch": value.Arch} {
		if strings.ContainsAny(value, "/\\\x00\r\n\t ") {
			return manifest{}, fmt.Errorf("manifest %s contains unsupported characters", field)
		}
	}
	return value, nil
}

func collectEntries(root string) ([]string, error) {
	var entries []string
	err := filepath.WalkDir(root, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if path == root {
			return nil
		}
		info, err := entry.Info()
		if err != nil {
			return err
		}
		if info.Mode()&os.ModeSymlink != 0 {
			return fmt.Errorf("symbolic links are not allowed: %s", path)
		}
		if !info.Mode().IsRegular() && !info.IsDir() {
			return fmt.Errorf("unsupported file type: %s", path)
		}
		entries = append(entries, path)
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("scan workdir: %w", err)
	}
	return entries, nil
}

func writeArchive(output io.Writer, root string, entries []string) error {
	gzipWriter, err := gzip.NewWriterLevel(output, gzip.BestCompression)
	if err != nil {
		return fmt.Errorf("create gzip writer: %w", err)
	}
	gzipWriter.Header.ModTime = time.Unix(0, 0).UTC()
	gzipWriter.Header.OS = 255
	tarWriter := tar.NewWriter(gzipWriter)

	for _, path := range entries {
		info, err := os.Lstat(path)
		if err != nil {
			return fmt.Errorf("stat %s: %w", path, err)
		}
		relative, err := filepath.Rel(root, path)
		if err != nil {
			return fmt.Errorf("resolve archive path: %w", err)
		}
		header, err := tar.FileInfoHeader(info, "")
		if err != nil {
			return fmt.Errorf("create header for %s: %w", relative, err)
		}
		header.Name = filepath.ToSlash(relative)
		header.ModTime = time.Unix(0, 0).UTC()
		header.AccessTime = time.Time{}
		header.ChangeTime = time.Time{}
		header.Uid = 0
		header.Gid = 0
		header.Uname = "root"
		header.Gname = "root"
		if err := tarWriter.WriteHeader(header); err != nil {
			return fmt.Errorf("write header for %s: %w", relative, err)
		}
		if !info.Mode().IsRegular() {
			continue
		}
		file, err := os.Open(path)
		if err != nil {
			return fmt.Errorf("open %s: %w", relative, err)
		}
		_, copyErr := io.Copy(tarWriter, file)
		closeErr := file.Close()
		if copyErr != nil {
			return fmt.Errorf("archive %s: %w", relative, copyErr)
		}
		if closeErr != nil {
			return fmt.Errorf("close %s: %w", relative, closeErr)
		}
	}
	if err := tarWriter.Close(); err != nil {
		return fmt.Errorf("close tar archive: %w", err)
	}
	if err := gzipWriter.Close(); err != nil {
		return fmt.Errorf("close gzip archive: %w", err)
	}
	return nil
}

func pathWithin(root, candidate string) bool {
	relative, err := filepath.Rel(root, candidate)
	return err == nil && relative != ".." && !strings.HasPrefix(relative, ".."+string(filepath.Separator))
}
