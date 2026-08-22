package bosrecipe

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"example.com/aos-pkg/internal/buildsystem"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (function roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) {
	return function(request)
}

type fakeRunner struct{ calls []string }

func (runner *fakeRunner) Run(_ context.Context, name string, args []string, _ string, environment []string) error {
	runner.calls = append(runner.calls, name+" "+strings.Join(args, " "))
	var destdir string
	for _, item := range environment {
		if strings.HasPrefix(item, "DESTDIR=") {
			destdir = strings.TrimPrefix(item, "DESTDIR=")
		}
	}
	if name == "/bin/sh" && strings.Contains(args[len(args)-1], "install") {
		path := filepath.Join(destdir, "usr/bin/hello")
		if err := os.MkdirAll(filepath.Dir(path), 0o750); err != nil {
			return err
		}
		return os.WriteFile(path, []byte("hello"), 0o755)
	}
	if name == "/trusted/bosbuild" {
		return os.WriteFile(args[3], []byte("bos"), 0o640)
	}
	return nil
}

func TestBuildRecipeVerifiesSourceAndRunsPhases(t *testing.T) {
	archive := testArchive(t, "hello-1.0/README", "hello")
	digest := sha256.Sum256(archive)
	client := &http.Client{Transport: roundTripFunc(func(_ *http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: http.StatusOK, Status: "200 OK", Body: io.NopCloser(bytes.NewReader(archive))}, nil
	})}
	runner := &fakeRunner{}
	output := filepath.Join(t.TempDir(), "hello.bos")
	recipe := buildsystem.BOSRecipe{Name: "hello", Version: "1.0", Release: "1", Summary: "hello", License: "MIT", Arch: "amd64", SourceURL: "https://sources.example.com/hello.tar.gz", SourceSHA256: hex.EncodeToString(digest[:]), BuildRequires: []string{"make"}, Prepare: []string{"prepare"}, Build: []string{"build"}, Install: []string{"install"}, Check: []string{"check"}, Files: []string{"/usr/bin/hello"}}
	if err := Build(context.Background(), Options{Recipe: recipe, Output: output, WorkspaceRoot: t.TempDir(), PackagerPath: "/trusted/bosbuild", DependencyPath: "/trusted/deps", HTTPClient: client, Runner: runner}); err != nil {
		t.Fatal(err)
	}
	if len(runner.calls) != 6 || !strings.HasPrefix(runner.calls[0], "/trusted/deps") || !strings.HasPrefix(runner.calls[5], "/trusted/bosbuild") {
		t.Fatalf("unexpected execution order: %#v", runner.calls)
	}
}

func TestExtractTarGzRejectsTraversal(t *testing.T) {
	archive := testArchive(t, "../escape", "bad")
	path := filepath.Join(t.TempDir(), "source.tar.gz")
	if err := os.WriteFile(path, archive, 0o600); err != nil {
		t.Fatal(err)
	}
	err := extractTarGz(path, filepath.Join(t.TempDir(), "out"))
	if err == nil || !strings.Contains(err.Error(), "path traversal") {
		t.Fatalf("traversal accepted: %v", err)
	}
}

func testArchive(t *testing.T, name, content string) []byte {
	t.Helper()
	var buffer bytes.Buffer
	gz := gzip.NewWriter(&buffer)
	tw := tar.NewWriter(gz)
	if err := tw.WriteHeader(&tar.Header{Name: name, Mode: 0o644, Size: int64(len(content)), Typeflag: tar.TypeReg}); err != nil {
		t.Fatal(err)
	}
	if _, err := tw.Write([]byte(content)); err != nil {
		t.Fatal(err)
	}
	if err := tw.Close(); err != nil {
		t.Fatal(err)
	}
	if err := gz.Close(); err != nil {
		t.Fatal(err)
	}
	return buffer.Bytes()
}
