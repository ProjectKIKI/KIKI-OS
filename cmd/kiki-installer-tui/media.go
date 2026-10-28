package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strings"
)

func profileAIDefault(profile string) string {
	if profile == "" {
		profile = "minimal-systemd"
	}
	profile = canonicalProfile(profile)
	mode := catalogProfiles[profile].AIDefault
	if mode == "" {
		mode = "local"
	}
	if mediaValue("profile "+profile, "ai_default") == "off" {
		return "off"
	}
	return mode
}

func initialMediaProfile() string {
	profile := mediaValue("media", "default_profile")
	if _, known := catalogProfiles[profile]; known {
		return profile
	}
	return "minimal-systemd"
}

func mediaValue(section, key string) string {
	path := os.Getenv("KIKI_INSTALLER_MEDIA_CATALOG")
	if path == "" {
		path = "/etc/kiki/installer-media.ini"
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	selected := false
	for _, line := range strings.Split(string(data), "\n") {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "[") {
			selected = line == "["+section+"]"
			continue
		}
		if selected && strings.HasPrefix(line, key+"=") {
			return strings.TrimPrefix(line, key+"=")
		}
	}
	return ""
}

// This is an availability preview. The installer backend verifies the media's
// Ed25519 signature and package hashes before touching the target disk.
func previewLocalPackages(plan InstallPlan) (int, int64, error) {
	file, err := os.Open(plan.Source.RepoIndex)
	if os.IsNotExist(err) {
		return 0, 0, nil
	}
	if err != nil {
		return 0, 0, err
	}
	defer file.Close()
	type entry struct {
		Name         string
		Size         int64
		Dependencies struct{ Runtime []string }
	}
	var index struct {
		Arch     string
		Packages []entry
	}
	decoder := json.NewDecoder(io.LimitReader(file, 4*1024*1024+1))
	if err := decoder.Decode(&index); err != nil {
		return 0, 0, fmt.Errorf("invalid local media index: %w", err)
	}
	if index.Arch != "x86_64" || len(index.Packages) == 0 {
		return 0, 0, fmt.Errorf("invalid local media architecture or empty index")
	}
	entries := map[string]entry{}
	for _, item := range index.Packages {
		if _, exists := entries[item.Name]; exists || item.Name == "" || item.Size <= 0 {
			return 0, 0, fmt.Errorf("invalid package entry: %s", item.Name)
		}
		entries[item.Name] = item
	}
	state := map[string]int{}
	var size int64
	var visit func(string) error
	visit = func(name string) error {
		if state[name] == 2 {
			return nil
		}
		if state[name] == 1 {
			return fmt.Errorf("runtime dependency cycle: %s", name)
		}
		item, exists := entries[name]
		if !exists {
			return fmt.Errorf("package missing from local media: %s", name)
		}
		if len(state) >= 512 {
			return fmt.Errorf("too many runtime packages")
		}
		state[name] = 1
		for _, dep := range item.Dependencies.Runtime {
			if err := visit(dep); err != nil {
				return err
			}
		}
		state[name] = 2
		size += item.Size
		return nil
	}
	for _, name := range plan.Packages.Selected {
		if err := visit(name); err != nil {
			return 0, 0, err
		}
	}
	return len(state), size, nil
}
