package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoopbackHostDetection(t *testing.T) {
	for _, host := range []string{"127.0.0.1", "localhost", "::1"} {
		if !isLoopbackHost(host) {
			t.Fatalf("loopback host rejected: %s", host)
		}
	}
	for _, host := range []string{"0.0.0.0", "10.0.0.5", ""} {
		if isLoopbackHost(host) {
			t.Fatalf("non-loopback host accepted: %q", host)
		}
	}
}

func TestReadOptionalToken(t *testing.T) {
	path := filepath.Join(t.TempDir(), "admin-token")
	expected := "0123456789abcdef0123456789abcdef"
	if err := os.WriteFile(path, []byte(" "+expected+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	token, err := readOptionalToken(path)
	if err != nil || token != expected {
		t.Fatalf("unexpected token result: %q %v", token, err)
	}
}
