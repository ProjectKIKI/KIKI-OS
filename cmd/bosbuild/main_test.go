package main

import (
	"archive/tar"
	"compress/gzip"
	"io"
	"os"
	"path/filepath"
	"testing"
)

func TestBuildBosCreatesArchive(t *testing.T) {
	workdir := t.TempDir()
	writeFile(t, filepath.Join(workdir, "manifest.yaml"), "name: kernel\nversion: 5.15.130\narch: x86_64\n")
	writeFile(t, filepath.Join(workdir, "rootfs", "etc", "os-release"), "NAME=AOS\n")

	output := filepath.Join(t.TempDir(), "kernel.bos")
	if err := buildBos(workdir, output); err != nil {
		t.Fatalf("buildBos() error = %v", err)
	}

	entries := readBosEntries(t, output)
	if entries["manifest.yaml"] != "name: kernel\nversion: 5.15.130\narch: x86_64\n" {
		t.Fatalf("manifest entry = %q", entries["manifest.yaml"])
	}
	if entries["rootfs/etc/os-release"] != "NAME=AOS\n" {
		t.Fatalf("rootfs entry = %q", entries["rootfs/etc/os-release"])
	}
}

func TestBuildBosSkipsOutputInsideWorkdir(t *testing.T) {
	workdir := t.TempDir()
	writeFile(t, filepath.Join(workdir, "manifest.yaml"), "name: baseos\nversion: 0.0.1\narch: x86_64\n")

	output := filepath.Join(workdir, "baseos.bos")
	if err := buildBos(workdir, output); err != nil {
		t.Fatalf("buildBos() error = %v", err)
	}

	entries := readBosEntries(t, output)
	if _, ok := entries["baseos.bos"]; ok {
		t.Fatal("archive included its own output file")
	}
}

func TestBuildBosRequiresManifest(t *testing.T) {
	err := buildBos(t.TempDir(), filepath.Join(t.TempDir(), "missing.bos"))
	if err == nil {
		t.Fatal("buildBos() missing manifest error = nil")
	}
}

func writeFile(t *testing.T, path, data string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatalf("MkdirAll() error = %v", err)
	}
	if err := os.WriteFile(path, []byte(data), 0o644); err != nil {
		t.Fatalf("WriteFile() error = %v", err)
	}
}

func readBosEntries(t *testing.T, path string) map[string]string {
	t.Helper()

	f, err := os.Open(path)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	defer f.Close()

	gz, err := gzip.NewReader(f)
	if err != nil {
		t.Fatalf("NewReader() error = %v", err)
	}
	defer gz.Close()

	tr := tar.NewReader(gz)
	entries := map[string]string{}
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			t.Fatalf("Next() error = %v", err)
		}
		if !hdr.FileInfo().Mode().IsRegular() {
			continue
		}
		data, err := io.ReadAll(tr)
		if err != nil {
			t.Fatalf("ReadAll() error = %v", err)
		}
		entries[hdr.Name] = string(data)
	}
	return entries
}
