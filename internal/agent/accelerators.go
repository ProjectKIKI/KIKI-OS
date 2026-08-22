package agent

import (
	"fmt"
	"path/filepath"
	"strconv"
	"strings"
)

// DRMDetector discovers GPUs through Linux sysfs without requiring a vendor
// utility. PCI IDs are retained when a friendly product name is unavailable.
type DRMDetector struct {
	Files Files
}

func (d DRMDetector) Detect() ([]Accelerator, error) {
	if d.Files == nil {
		return nil, nil
	}
	paths, err := d.Files.Glob("/sys/class/drm/card*/device/vendor")
	if err != nil {
		return nil, err
	}
	seen := map[string]bool{}
	var accelerators []Accelerator
	for _, vendorPath := range paths {
		deviceDir := filepath.Dir(vendorPath)
		deviceLink, err := d.Files.Readlink(deviceDir)
		if err != nil {
			continue
		}
		id := strings.ToLower(filepath.Base(deviceLink))
		if seen[id] {
			continue
		}
		vendorData, err := d.Files.ReadFile(vendorPath)
		if err != nil {
			continue
		}
		vendor, backend := acceleratorVendor(strings.TrimSpace(string(vendorData)))
		if vendor == "" {
			continue
		}
		deviceData, _ := d.Files.ReadFile(filepath.Join(deviceDir, "device"))
		deviceID := strings.TrimPrefix(strings.TrimSpace(string(deviceData)), "0x")
		memoryData, _ := d.Files.ReadFile(filepath.Join(deviceDir, "mem_info_vram_total"))
		memory, _ := strconv.ParseUint(strings.TrimSpace(string(memoryData)), 10, 64)
		driver := ""
		if link, linkErr := d.Files.Readlink(filepath.Join(deviceDir, "driver")); linkErr == nil {
			driver = filepath.Base(link)
		}
		model := vendor
		if deviceID != "" {
			model = fmt.Sprintf("%s PCI device %s", vendor, deviceID)
		}
		accelerators = append(accelerators, Accelerator{
			ID: id, Vendor: vendor, Model: model, Backend: backend,
			MemoryBytes: memory, Driver: driver,
		})
		seen[id] = true
	}
	return accelerators, nil
}

func acceleratorVendor(pciVendor string) (string, string) {
	switch strings.ToLower(strings.TrimPrefix(pciVendor, "0x")) {
	case "10de":
		return "nvidia", "cuda"
	case "1002", "1022":
		return "amd", "rocm"
	case "8086":
		return "intel", "xpu"
	default:
		return "", ""
	}
}
