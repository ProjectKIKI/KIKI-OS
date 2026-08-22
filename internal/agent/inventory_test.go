package agent

import (
	"errors"
	"io"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

type memoryFiles map[string]string

func (files memoryFiles) Open(path string) (io.ReadCloser, error) {
	value, ok := files[path]
	if !ok {
		return nil, errors.New("not found")
	}
	return io.NopCloser(strings.NewReader(value)), nil
}

func (files memoryFiles) ReadFile(path string) ([]byte, error) {
	value, ok := files[path]
	if !ok {
		return nil, errors.New("not found")
	}
	return []byte(value), nil
}

func (files memoryFiles) Glob(pattern string) ([]string, error) {
	var matches []string
	for path := range files {
		matched, err := filepath.Match(pattern, path)
		if err != nil {
			return nil, err
		}
		if matched {
			matches = append(matches, path)
		}
	}
	return matches, nil
}

func (files memoryFiles) Readlink(path string) (string, error) {
	value, ok := files[path]
	if !ok {
		return "", errors.New("not found")
	}
	return value, nil
}

func TestCollectInventory(t *testing.T) {
	now := time.Date(2026, 7, 31, 1, 2, 3, 0, time.FixedZone("KST", 9*60*60))
	collector := Collector{
		Files: memoryFiles{
			"/etc/os-release": "NAME=\"KIKI OS\"\nID=kiki\nVERSION_ID=1\n",
			"/etc/machine-id": "machine-123\n",
			"/proc/cpuinfo":   "processor: 0\nmodel name: KIKI Test CPU\nflags: avx2 sse4_2 avx\n",
			"/proc/meminfo":   "MemTotal: 32768 kB\nMemAvailable: 16384 kB\n",
		},
		Hostname:     func() (string, error) { return "node-01", nil },
		Architecture: "amd64",
		LogicalCores: 8,
		Now:          func() time.Time { return now },
	}
	inventory, err := collector.Collect()
	if err != nil {
		t.Fatal(err)
	}
	if inventory.SchemaVersion != "kiki.io/inventory/v1alpha1" || inventory.Hostname != "node-01" || inventory.MachineID != "machine-123" {
		t.Fatalf("unexpected identity: %#v", inventory)
	}
	if inventory.OS.ID != "kiki" || inventory.OS.Architecture != "amd64" {
		t.Fatalf("unexpected OS: %#v", inventory.OS)
	}
	if inventory.CPU.Model != "KIKI Test CPU" || inventory.CPU.LogicalCores != 8 {
		t.Fatalf("unexpected CPU: %#v", inventory.CPU)
	}
	if got := strings.Join(inventory.CPU.Features, ","); got != "avx,avx2,sse4_2" {
		t.Fatalf("features not normalized: %s", got)
	}
	if inventory.Memory.TotalBytes != 32768*1024 || inventory.Memory.AvailableBytes != 16384*1024 {
		t.Fatalf("unexpected memory: %#v", inventory.Memory)
	}
	if inventory.CollectedAt.Location() != time.UTC {
		t.Fatalf("timestamp is not UTC: %s", inventory.CollectedAt)
	}
}

func TestCollectRequiresMemoryFields(t *testing.T) {
	collector := Collector{
		Files: memoryFiles{
			"/etc/os-release": "ID=kiki\n",
			"/proc/cpuinfo":   "model name: CPU\n",
			"/proc/meminfo":   "MemTotal: 1024 kB\n",
		},
		Hostname:     func() (string, error) { return "node", nil },
		Architecture: "amd64",
		LogicalCores: 1,
		Now:          time.Now,
	}
	_, err := collector.Collect()
	if err == nil || !strings.Contains(err.Error(), "MemAvailable") {
		t.Fatalf("unexpected error: %v", err)
	}
}
