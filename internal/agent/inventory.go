package agent

import (
	"bufio"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"time"
)

type Inventory struct {
	SchemaVersion string        `json:"schema_version"`
	CollectedAt   time.Time     `json:"collected_at"`
	Hostname      string        `json:"hostname"`
	MachineID     string        `json:"machine_id,omitempty"`
	OS            OSInventory   `json:"os"`
	CPU           CPUInventory  `json:"cpu"`
	Memory        Memory        `json:"memory"`
	Accelerators  []Accelerator `json:"accelerators"`
}

type OSInventory struct {
	Name         string `json:"name,omitempty"`
	ID           string `json:"id,omitempty"`
	VersionID    string `json:"version_id,omitempty"`
	Architecture string `json:"architecture"`
}

type CPUInventory struct {
	Architecture string   `json:"architecture"`
	LogicalCores int      `json:"logical_cores"`
	Model        string   `json:"model,omitempty"`
	Features     []string `json:"features,omitempty"`
}

type Memory struct {
	TotalBytes     uint64 `json:"total_bytes"`
	AvailableBytes uint64 `json:"available_bytes"`
}

type Accelerator struct {
	ID          string `json:"id"`
	Vendor      string `json:"vendor"`
	Model       string `json:"model"`
	Backend     string `json:"backend"`
	MemoryBytes uint64 `json:"memory_bytes,omitempty"`
	Driver      string `json:"driver,omitempty"`
}

type Files interface {
	Open(string) (io.ReadCloser, error)
	ReadFile(string) ([]byte, error)
	Glob(string) ([]string, error)
	Readlink(string) (string, error)
}

type OSFiles struct{}

func (OSFiles) Open(path string) (io.ReadCloser, error) { return os.Open(path) }
func (OSFiles) ReadFile(path string) ([]byte, error)    { return os.ReadFile(path) }
func (OSFiles) Glob(pattern string) ([]string, error)   { return filepath.Glob(pattern) }
func (OSFiles) Readlink(path string) (string, error)    { return os.Readlink(path) }

type AcceleratorDetector interface {
	Detect() ([]Accelerator, error)
}

type Collector struct {
	Files                Files
	Hostname             func() (string, error)
	Architecture         string
	LogicalCores         int
	Now                  func() time.Time
	AcceleratorDetectors []AcceleratorDetector
}

func NewCollector() Collector {
	collector := Collector{
		Files:        OSFiles{},
		Hostname:     os.Hostname,
		Architecture: runtime.GOARCH,
		LogicalCores: runtime.NumCPU(),
		Now:          time.Now,
	}
	collector.AcceleratorDetectors = []AcceleratorDetector{DRMDetector{Files: collector.Files}}
	return collector
}

func (c Collector) Collect() (Inventory, error) {
	if c.Files == nil || c.Hostname == nil || c.Now == nil {
		return Inventory{}, errors.New("collector dependencies are not configured")
	}
	hostname, err := c.Hostname()
	if err != nil {
		return Inventory{}, fmt.Errorf("read hostname: %w", err)
	}
	osInventory, err := c.collectOS()
	if err != nil {
		return Inventory{}, err
	}
	cpu, err := c.collectCPU()
	if err != nil {
		return Inventory{}, err
	}
	memory, err := c.collectMemory()
	if err != nil {
		return Inventory{}, err
	}
	machineID := ""
	if data, readErr := c.Files.ReadFile("/etc/machine-id"); readErr == nil {
		machineID = strings.TrimSpace(string(data))
	}
	accelerators, err := collectAccelerators(c.AcceleratorDetectors)
	if err != nil {
		return Inventory{}, err
	}
	return Inventory{
		SchemaVersion: "kiki.io/inventory/v1alpha1",
		CollectedAt:   c.Now().UTC(),
		Hostname:      hostname,
		MachineID:     machineID,
		OS:            osInventory,
		CPU:           cpu,
		Memory:        memory,
		Accelerators:  accelerators,
	}, nil
}

func collectAccelerators(detectors []AcceleratorDetector) ([]Accelerator, error) {
	byID := map[string]Accelerator{}
	for _, detector := range detectors {
		if detector == nil {
			continue
		}
		items, err := detector.Detect()
		if err != nil {
			return nil, fmt.Errorf("detect accelerators: %w", err)
		}
		for _, item := range items {
			if item.ID == "" || item.Vendor == "" || item.Backend == "" {
				return nil, errors.New("accelerator detector returned incomplete identity")
			}
			byID[item.ID] = item
		}
	}
	items := make([]Accelerator, 0, len(byID))
	for _, item := range byID {
		items = append(items, item)
	}
	sort.Slice(items, func(i, j int) bool { return items[i].ID < items[j].ID })
	return items, nil
}

func (c Collector) collectOS() (OSInventory, error) {
	data, err := c.Files.ReadFile("/etc/os-release")
	if err != nil {
		return OSInventory{}, fmt.Errorf("read os-release: %w", err)
	}
	values := parseKeyValues(string(data))
	return OSInventory{
		Name:         values["NAME"],
		ID:           values["ID"],
		VersionID:    values["VERSION_ID"],
		Architecture: c.Architecture,
	}, nil
}

func (c Collector) collectCPU() (CPUInventory, error) {
	file, err := c.Files.Open("/proc/cpuinfo")
	if err != nil {
		return CPUInventory{}, fmt.Errorf("read cpuinfo: %w", err)
	}
	defer file.Close()
	values, err := scanColonValues(file)
	if err != nil {
		return CPUInventory{}, fmt.Errorf("parse cpuinfo: %w", err)
	}
	model := firstNonEmpty(values["model name"], values["hardware"], values["processor"])
	featureText := firstNonEmpty(values["flags"], values["features"])
	features := strings.Fields(featureText)
	sort.Strings(features)
	return CPUInventory{Architecture: c.Architecture, LogicalCores: c.LogicalCores, Model: model, Features: features}, nil
}

func (c Collector) collectMemory() (Memory, error) {
	file, err := c.Files.Open("/proc/meminfo")
	if err != nil {
		return Memory{}, fmt.Errorf("read meminfo: %w", err)
	}
	defer file.Close()
	values, err := scanColonValues(file)
	if err != nil {
		return Memory{}, fmt.Errorf("parse meminfo: %w", err)
	}
	total, err := parseMemoryKB(values["MemTotal"])
	if err != nil {
		return Memory{}, fmt.Errorf("parse MemTotal: %w", err)
	}
	available, err := parseMemoryKB(values["MemAvailable"])
	if err != nil {
		return Memory{}, fmt.Errorf("parse MemAvailable: %w", err)
	}
	return Memory{TotalBytes: total, AvailableBytes: available}, nil
}

func parseKeyValues(input string) map[string]string {
	values := map[string]string{}
	for _, line := range strings.Split(input, "\n") {
		key, value, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		values[strings.TrimSpace(key)] = strings.Trim(strings.TrimSpace(value), `"'`)
	}
	return values
}

func scanColonValues(reader io.Reader) (map[string]string, error) {
	values := map[string]string{}
	scanner := bufio.NewScanner(reader)
	for scanner.Scan() {
		key, value, ok := strings.Cut(scanner.Text(), ":")
		if ok && values[strings.TrimSpace(key)] == "" {
			values[strings.TrimSpace(key)] = strings.TrimSpace(value)
		}
	}
	return values, scanner.Err()
}

func parseMemoryKB(value string) (uint64, error) {
	fields := strings.Fields(value)
	if len(fields) == 0 {
		return 0, errors.New("value is missing")
	}
	kilobytes, err := strconv.ParseUint(fields[0], 10, 64)
	if err != nil {
		return 0, err
	}
	return kilobytes * 1024, nil
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if value != "" {
			return value
		}
	}
	return ""
}
