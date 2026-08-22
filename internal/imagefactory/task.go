package imagefactory

import (
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"sort"
	"strings"

	"example.com/aos-pkg/internal/buildsystem"
)

type Request struct {
	BuildID    string             `json:"build_id"`
	Type       string             `json:"type"`
	Source     buildsystem.Source `json:"source"`
	Release    string             `json:"release"`
	Arch       string             `json:"arch"`
	BootModes  []string           `json:"boot_modes"`
	OutputName string             `json:"output_name"`
}

type Task struct {
	APIVersion string    `json:"api_version"`
	Request    Request   `json:"request"`
	Steps      []string  `json:"steps"`
	Isolation  Isolation `json:"isolation"`
}

type Isolation struct {
	DisposableVMRequired bool `json:"disposable_vm_required"`
	KVMRequired          bool `json:"kvm_required"`
	GeneralNodeAllowed   bool `json:"general_node_allowed"`
}

var idPattern = regexp.MustCompile(`^[a-z0-9]([-a-z0-9.]{0,61}[a-z0-9])?$`)
var revisionPattern = regexp.MustCompile(`^[a-f0-9]{40}([a-f0-9]{24})?$`)

func CreateTask(request Request, allowedGitHosts []string) (Task, error) {
	if !idPattern.MatchString(request.BuildID) || !revisionPattern.MatchString(request.Source.Revision) {
		return Task{}, errors.New("invalid build ID or immutable source revision")
	}
	if request.Type != "iso" && request.Type != "pxe" && request.Type != "disk" {
		return Task{}, errors.New("image type must be iso, pxe, or disk")
	}
	parsed, err := url.Parse(request.Source.URL)
	if err != nil || parsed.Scheme != "https" || parsed.Hostname() == "" || parsed.User != nil || !allowed(parsed.Hostname(), allowedGitHosts) {
		return Task{}, errors.New("source must use an allow-listed credential-free HTTPS host")
	}
	if request.Release != "v3.20" || request.Arch != "x86_64" {
		return Task{}, errors.New("current Image Factory supports Alpine v3.20 x86_64")
	}
	if len(request.BootModes) == 0 {
		return Task{}, errors.New("at least one boot mode is required")
	}
	if request.Type == "disk" && len(request.BootModes) != 1 {
		return Task{}, errors.New("disk images require exactly one boot mode per artifact")
	}
	modes := append([]string(nil), request.BootModes...)
	sort.Strings(modes)
	for index, mode := range modes {
		if mode != "bios" && mode != "uefi" {
			return Task{}, fmt.Errorf("unsupported boot mode %q", mode)
		}
		if index > 0 && modes[index-1] == mode {
			return Task{}, errors.New("duplicate boot mode")
		}
	}
	if !strings.HasSuffix(request.OutputName, extension(request.Type)) || strings.ContainsAny(request.OutputName, `/\\`) {
		return Task{}, errors.New("output filename does not match image type")
	}
	steps := []string{"source.fetch", "source.verify", "image.build"}
	for _, mode := range modes {
		steps = append(steps, "qemu.verify."+mode)
	}
	steps = append(steps, "artifact.hash", "artifact.publish")
	return Task{APIVersion: "factory.kiki.io/v1alpha1", Request: request, Steps: steps, Isolation: Isolation{DisposableVMRequired: true, KVMRequired: true, GeneralNodeAllowed: false}}, nil
}

func extension(kind string) string {
	switch kind {
	case "iso":
		return ".iso"
	case "pxe":
		return ".tar.gz"
	case "disk":
		return ".qcow2"
	default:
		return ""
	}
}

func allowed(host string, values []string) bool {
	for _, value := range values {
		if strings.EqualFold(host, strings.TrimSpace(value)) {
			return true
		}
	}
	return false
}
