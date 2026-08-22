package agent

import "testing"

func TestDRMDetector(t *testing.T) {
	files := memoryFiles{
		"/sys/class/drm/card0/device":                     "../../../0000:65:00.0",
		"/sys/class/drm/card0/device/vendor":              "0x10de\n",
		"/sys/class/drm/card0/device/device":              "0x2684\n",
		"/sys/class/drm/card0/device/mem_info_vram_total": "25769803776\n",
		"/sys/class/drm/card0/device/driver":              "../../../../bus/pci/drivers/nvidia",
		"/sys/class/drm/card1/device":                     "../../../0000:0b:00.0",
		"/sys/class/drm/card1/device/vendor":              "0x1002\n",
		"/sys/class/drm/card1/device/device":              "0x744c\n",
		"/sys/class/drm/card1/device/mem_info_vram_total": "17179869184\n",
		"/sys/class/drm/card1/device/driver":              "../../../../bus/pci/drivers/amdgpu",
		"/sys/class/drm/card2/device":                     "../../../0000:00:02.0",
		"/sys/class/drm/card2/device/vendor":              "0x8086\n",
		"/sys/class/drm/card2/device/device":              "0x56a0\n",
		"/sys/class/drm/card2/device/driver":              "../../../../bus/pci/drivers/i915",
	}
	items, err := (DRMDetector{Files: files}).Detect()
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 3 {
		t.Fatalf("expected three accelerators, got %#v", items)
	}
	byVendor := map[string]Accelerator{}
	for _, item := range items {
		byVendor[item.Vendor] = item
	}
	if byVendor["nvidia"].Backend != "cuda" || byVendor["nvidia"].MemoryBytes != 25769803776 || byVendor["nvidia"].Driver != "nvidia" {
		t.Fatalf("unexpected NVIDIA device: %#v", byVendor["nvidia"])
	}
	if byVendor["amd"].Backend != "rocm" || byVendor["amd"].Driver != "amdgpu" {
		t.Fatalf("unexpected AMD device: %#v", byVendor["amd"])
	}
	if byVendor["intel"].Backend != "xpu" || byVendor["intel"].Driver != "i915" {
		t.Fatalf("unexpected Intel device: %#v", byVendor["intel"])
	}
}

func TestAcceleratorVendorRejectsUnknownDevices(t *testing.T) {
	if vendor, backend := acceleratorVendor("0x1234"); vendor != "" || backend != "" {
		t.Fatalf("unexpected mapping: %s/%s", vendor, backend)
	}
}
