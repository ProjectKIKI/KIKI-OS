package main

import (
	"archive/tar"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestBuildBosProducesDeterministicArchive(t *testing.T) {
	workdir := t.TempDir()
	writeTestFile(t, filepath.Join(workdir, "manifest.yaml"), "name: kiki-agent\nversion: 1.0.0\nrelease: '1'\narch: amd64\n", 0o644)
	writeTestFile(t, filepath.Join(workdir, "rootfs/usr/bin/kiki-agent"), "binary", 0o755)

	first := filepath.Join(t.TempDir(), "first.bos")
	second := filepath.Join(t.TempDir(), "second.bos")
	result1, err := buildBos(workdir, first)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chtimes(filepath.Join(workdir, "rootfs/usr/bin/kiki-agent"), time.Now(), time.Now()); err != nil {
		t.Fatal(err)
	}
	result2, err := buildBos(workdir, second)
	if err != nil {
		t.Fatal(err)
	}
	if result1.SHA256 != result2.SHA256 {
		t.Fatalf("build is not deterministic: %s != %s", result1.SHA256, result2.SHA256)
	}
	data, err := os.ReadFile(first)
	if err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(data)
	if got := hex.EncodeToString(digest[:]); got != result1.SHA256 {
		t.Fatalf("reported digest %s does not match %s", result1.SHA256, got)
	}

	entries := readArchiveEntries(t, first)
	if entries["manifest.yaml"] != "name: kiki-agent\nversion: 1.0.0\nrelease: '1'\narch: amd64\n" {
		t.Fatalf("manifest missing from archive: %#v", entries)
	}
	if entries["rootfs/usr/bin/kiki-agent"] != "binary" {
		t.Fatalf("payload missing from archive: %#v", entries)
	}
}

func TestBuildBosRejectsInvalidInput(t *testing.T) {
	tests := []struct {
		name     string
		manifest string
		prepare  func(*testing.T, string)
		want     string
	}{
		{name: "missing required field", manifest: "name: pkg\narch: amd64\n", want: "requires name, version, and arch"},
		{name: "unsafe name", manifest: "name: ../pkg\nversion: 1\narch: amd64\n", want: "unsupported characters"},
		{name: "unsafe version", manifest: "name: pkg\nversion: ../1\narch: amd64\n", want: "manifest version contains unsupported characters"},
		{name: "symlink", manifest: "name: pkg\nversion: 1\narch: amd64\n", prepare: addSymlink, want: "symbolic links are not allowed"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			workdir := t.TempDir()
			writeTestFile(t, filepath.Join(workdir, "manifest.yaml"), test.manifest, 0o644)
			if test.prepare != nil {
				test.prepare(t, workdir)
			}
			_, err := buildBos(workdir, filepath.Join(t.TempDir(), "output.bos"))
			if err == nil || !strings.Contains(err.Error(), test.want) {
				t.Fatalf("expected error containing %q, got %v", test.want, err)
			}
		})
	}
}

func TestBuildBosRejectsOutputInsideWorkdir(t *testing.T) {
	workdir := t.TempDir()
	writeTestFile(t, filepath.Join(workdir, "manifest.yaml"), "name: pkg\nversion: 1\narch: amd64\n", 0o644)
	_, err := buildBos(workdir, filepath.Join(workdir, "output.bos"))
	if err == nil || !strings.Contains(err.Error(), "outside the build workdir") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func writeTestFile(t *testing.T, path, content string, mode os.FileMode) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), mode); err != nil {
		t.Fatal(err)
	}
}

func addSymlink(t *testing.T, workdir string) {
	t.Helper()
	if err := os.Symlink("manifest.yaml", filepath.Join(workdir, "manifest-link.yaml")); err != nil {
		t.Skipf("symlinks unavailable: %v", err)
	}
}

func readArchiveEntries(t *testing.T, path string) map[string]string {
	t.Helper()
	file, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	gzipReader, err := gzip.NewReader(file)
	if err != nil {
		t.Fatal(err)
	}
	defer gzipReader.Close()
	tarReader := tar.NewReader(gzipReader)
	entries := map[string]string{}
	for {
		header, err := tarReader.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			t.Fatal(err)
		}
		if header.Typeflag != tar.TypeReg {
			continue
		}
		data, err := io.ReadAll(tarReader)
		if err != nil {
			t.Fatal(err)
		}
		entries[header.Name] = string(data)
	}
	return entries
}
