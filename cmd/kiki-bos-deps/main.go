package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"sort"
)

func main() {
	root := flag.String("root", "", "ephemeral buildroot used for the resolution record")
	catalog := flag.String("catalog", "/etc/kiki/bos-build-capabilities.json", "immutable builder capability catalog")
	flag.Parse()
	requested := flag.Args()
	if len(requested) > 0 && requested[0] == "--" {
		requested = requested[1:]
	}
	if err := resolve(*root, *catalog, requested); err != nil {
		_, _ = fmt.Fprintln(os.Stderr, "dependency resolution:", err)
		os.Exit(1)
	}
}

func resolve(root, catalogPath string, requested []string) error {
	if root == "" {
		return errors.New("buildroot is required")
	}
	data, err := os.ReadFile(catalogPath)
	if err != nil {
		return fmt.Errorf("read capability catalog: %w", err)
	}
	var available []string
	if err := json.Unmarshal(data, &available); err != nil {
		return fmt.Errorf("parse capability catalog: %w", err)
	}
	set := make(map[string]bool, len(available))
	for _, name := range available {
		set[name] = true
	}
	for _, name := range requested {
		if !set[name] {
			return fmt.Errorf("build dependency %q is not in the pinned builder profile", name)
		}
	}
	sort.Strings(requested)
	if err := os.MkdirAll(root, 0o750); err != nil {
		return err
	}
	lock, err := json.MarshalIndent(map[string]any{"version": 1, "resolved": requested}, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(root, "build-requires.lock.json"), append(lock, '\n'), 0o640)
}
