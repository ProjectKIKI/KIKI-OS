package store

import (
	"path/filepath"
	"testing"
)

type testPackage struct {
	Name string `json:"name"`
}

func (p testPackage) GetName() string {
	return p.Name
}

type depPackage struct {
	Name string   `json:"name"`
	Deps []string `json:"deps,omitempty"`
}

func (p depPackage) GetName() string {
	return p.Name
}

func (p depPackage) GetRuntimeDependencies() []string {
	return p.Deps
}

func TestStoreAddFindRemoveAndLoad(t *testing.T) {
	dbPath := filepath.Join(t.TempDir(), "nested", "db.json")
	st := NewStore[testPackage](dbPath)

	if err := st.Init(); err != nil {
		t.Fatalf("Init() error = %v", err)
	}
	if err := st.Add(testPackage{Name: "kernel"}); err != nil {
		t.Fatalf("Add() error = %v", err)
	}
	if err := st.Add(testPackage{Name: "kernel"}); err == nil {
		t.Fatal("Add() duplicate error = nil")
	}

	found, ok := st.Find("kernel")
	if !ok {
		t.Fatal("Find() did not locate package")
	}
	if found.Name != "kernel" {
		t.Fatalf("Find() name = %q, want kernel", found.Name)
	}

	loaded := NewStore[testPackage](dbPath)
	if err := loaded.Load(); err != nil {
		t.Fatalf("Load() error = %v", err)
	}
	if _, ok := loaded.Find("kernel"); !ok {
		t.Fatal("Load() did not restore package")
	}

	if err := loaded.Remove("kernel"); err != nil {
		t.Fatalf("Remove() error = %v", err)
	}
	if _, ok := loaded.Find("kernel"); ok {
		t.Fatal("Remove() left package behind")
	}
	if err := loaded.Remove("kernel"); err == nil {
		t.Fatal("Remove() missing package error = nil")
	}
}

func TestStoreListReturnsCopy(t *testing.T) {
	st := NewStore[testPackage](filepath.Join(t.TempDir(), "db.json"))
	if err := st.Add(testPackage{Name: "baseos"}); err != nil {
		t.Fatalf("Add() error = %v", err)
	}

	list := st.List()
	list[0] = testPackage{Name: "mutated"}

	found, ok := st.Find("baseos")
	if !ok {
		t.Fatal("Find() did not locate original package")
	}
	if found.Name != "baseos" {
		t.Fatalf("store was mutated through List(): got %q", found.Name)
	}
}

func TestStoreRejectsEmptyName(t *testing.T) {
	st := NewStore[testPackage](filepath.Join(t.TempDir(), "db.json"))
	if err := st.Add(testPackage{}); err == nil {
		t.Fatal("Add() empty name error = nil")
	}
	if err := st.Remove(""); err == nil {
		t.Fatal("Remove() empty name error = nil")
	}
}

func TestStoreRemoveBlocksRuntimeDependents(t *testing.T) {
	st := NewStore[depPackage](filepath.Join(t.TempDir(), "db.json"))
	if err := st.Add(depPackage{Name: "glibc"}); err != nil {
		t.Fatalf("Add(glibc) error = %v", err)
	}
	if err := st.Add(depPackage{Name: "zlib", Deps: []string{"glibc"}}); err != nil {
		t.Fatalf("Add(zlib) error = %v", err)
	}

	if err := st.Remove("glibc"); err == nil {
		t.Fatal("Remove(glibc) dependency error = nil")
	}
	if err := st.Remove("zlib"); err != nil {
		t.Fatalf("Remove(zlib) error = %v", err)
	}
	if err := st.Remove("glibc"); err != nil {
		t.Fatalf("Remove(glibc after dependent) error = %v", err)
	}
}
