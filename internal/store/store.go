package store

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
)

// Package is the minimal interface a package type must implement
// to be managed by Store.
type Package interface {
	GetName() string
}

// RuntimeDependencyProvider can be implemented by package types that expose
// runtime dependencies. Store uses it to block unsafe removals.
type RuntimeDependencyProvider interface {
	GetRuntimeDependencies() []string
}

// Store is a simple JSON-backed package store.
type Store[T Package] struct {
	Path     string
	Packages []T
}

// DefaultPath builds a default DB path under the user's home directory.
func DefaultPath(subdir, filename string) (string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	dir := filepath.Join(home, subdir)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	return filepath.Join(dir, filename), nil
}

// NewStore creates a store bound to a given path.
func NewStore[T Package](path string) *Store[T] {
	return &Store[T]{Path: path, Packages: []T{}}
}

// Init resets the store to an empty state and writes it to disk.
func (s *Store[T]) Init() error {
	s.Packages = []T{}
	return s.save()
}

// Load reads the store from disk, if it exists.
func (s *Store[T]) Load() error {
	data, err := os.ReadFile(s.Path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			s.Packages = []T{}
			return nil
		}
		return err
	}
	if len(data) == 0 {
		s.Packages = []T{}
		return nil
	}
	return json.Unmarshal(data, &s.Packages)
}

// save writes the current state to disk.
func (s *Store[T]) save() error {
	if err := os.MkdirAll(filepath.Dir(s.Path), 0o755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(s.Packages, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(s.Path, data, 0o644)
}

// Add inserts a new package, ensuring no name duplicates.
func (s *Store[T]) Add(pkg T) error {
	if pkg.GetName() == "" {
		return fmt.Errorf("package name is required")
	}
	for _, p := range s.Packages {
		if p.GetName() == pkg.GetName() {
			return fmt.Errorf("package %q already exists", pkg.GetName())
		}
	}
	s.Packages = append(s.Packages, pkg)
	return s.save()
}

// Remove deletes a package by name.
func (s *Store[T]) Remove(name string) error {
	if name == "" {
		return fmt.Errorf("package name is required")
	}
	targetIndex := -1
	for i, p := range s.Packages {
		if p.GetName() == name {
			targetIndex = i
			break
		}
	}
	if targetIndex == -1 {
		return fmt.Errorf("package %q not found", name)
	}

	for _, p := range s.Packages {
		if p.GetName() == name {
			continue
		}
		provider, ok := any(p).(RuntimeDependencyProvider)
		if !ok {
			continue
		}
		for _, dep := range provider.GetRuntimeDependencies() {
			if dep == name {
				return fmt.Errorf("cannot remove package %q: required by %q", name, p.GetName())
			}
		}
	}

	s.Packages = append(s.Packages[:targetIndex], s.Packages[targetIndex+1:]...)
	return s.save()
}

// Find returns a package by name.
func (s *Store[T]) Find(name string) (T, bool) {
	var zero T
	for _, p := range s.Packages {
		if p.GetName() == name {
			return p, true
		}
	}
	return zero, false
}

// List returns all packages.
func (s *Store[T]) List() []T {
	pkgs := make([]T, len(s.Packages))
	copy(pkgs, s.Packages)
	return pkgs
}
