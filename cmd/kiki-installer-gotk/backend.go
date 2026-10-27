package main

import (
	"context"
	"errors"
	"fmt"
	"gopkg.in/yaml.v3"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
)

var diskName = regexp.MustCompile("^(sd[a-z]+|vd[a-z]+|xvd[a-z]+|nvme[0-9]+n[0-9]+|mmcblk[0-9]+)$")
var packageName = regexp.MustCompile("^[a-zA-Z0-9][a-zA-Z0-9+_.-]*$")

func installerSession(cmdline string) bool {
	for _, token := range strings.Fields(cmdline) {
		if token == "kiki.boot=installer" {
			return true
		}
	}
	return false
}

type Config struct {
	Values                 map[string]string
	Password, Confirmation string
	Erase                  bool
}

func defaults() Config {
	return Config{Values: map[string]string{
		"disk": "", "swap": "auto", "hostname": "kiki.local", "user": "kiki",
		"locale": "ko_KR.UTF-8", "keymap": "kr", "timezone": "Asia/Seoul",
		"network": "dhcp", "network_interface": "", "address": "", "gateway": "", "dns": "",
		"profile": "server-core", "runtime": "profile-default", "ai": "local",
		"ai_endpoint": "http://127.0.0.1:8080/v1/chat/completions", "groups": "",
	}}
}

func addPackageGroup(groups, group string) string {
	for _, existing := range strings.Split(groups, ",") {
		if strings.TrimSpace(existing) == group {
			return groups
		}
	}
	if strings.TrimSpace(groups) == "" {
		return group
	}
	return groups + "," + group
}
func (c Config) validate(install bool) error {
	for key, value := range c.Values {
		if strings.ContainsAny(value, "\r\n\x00") || !utf8.ValidString(value) || len(value) > 512 {
			return fmt.Errorf("%s: invalid or oversized value", key)
		}
	}
	if !strings.HasPrefix(c.Values["disk"], "/dev/") || !diskName.MatchString(strings.TrimPrefix(c.Values["disk"], "/dev/")) {
		return errors.New("select a whole disk")
	}
	if c.Values["network"] != "off" && c.Values["network_interface"] == "" {
		return errors.New("select a network interface or offline mode")
	}
	if c.Values["network"] == "static" {
		if _, _, err := net.ParseCIDR(c.Values["address"]); err != nil {
			return errors.New("static address requires a valid CIDR prefix")
		}
		if g := c.Values["gateway"]; g != "" && net.ParseIP(g) == nil {
			return errors.New("invalid gateway")
		}
	}
	for _, dns := range strings.Fields(strings.ReplaceAll(c.Values["dns"], ",", " ")) {
		if net.ParseIP(dns) == nil {
			return errors.New("invalid DNS address")
		}
	}
	if strings.HasPrefix(c.Values["profile"], "kiki-kube-") && c.Values["swap"] == "on" {
		return errors.New("Kubernetes profiles require swap off or auto")
	}
	if install {
		if !c.Erase {
			return errors.New("confirm deletion of the selected disk")
		}
		if len(c.Password) < 8 || len(c.Password) > 95 || strings.ContainsAny(c.Password, "\r\n\x00") || !utf8.ValidString(c.Password) {
			return errors.New("password must be 8–95 UTF-8 bytes without line breaks")
		}
		if c.Password != c.Confirmation {
			return errors.New("passwords do not match")
		}
	}
	return nil
}
func (c Config) planArgs(path string) []string {
	args := []string{"--write", "--plan", path, "--mode", "guided", "--source", "local", "--source-location", "/run/install-media"}
	for _, key := range []string{"disk", "swap", "hostname", "user", "locale", "keymap", "timezone", "network", "network_interface", "address", "gateway", "dns", "profile", "runtime", "ai", "ai_endpoint", "groups"} {
		if key == "runtime" && c.Values[key] == "profile-default" || key == "groups" && c.Values[key] == "" {
			continue
		}
		args = append(args, "--"+strings.ReplaceAll(key, "_", "-"), c.Values[key])
	}
	return args
}

// The existing CLI remains the authoritative plan generator and validator.
func generatePlan(ctx context.Context, binary, path string, c Config) ([]byte, error) {
	if err := c.validate(false); err != nil {
		return nil, err
	}
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	out, err := exec.CommandContext(ctx, binary, c.planArgs(path)...).CombinedOutput()
	if err != nil {
		return nil, fmt.Errorf("plan validation failed: %w\n%s", err, out)
	}
	return os.ReadFile(path)
}
func (c Config) request(planPath string, plan []byte) ([]byte, error) {
	if err := c.validate(true); err != nil {
		return nil, err
	}
	var document struct {
		Plan struct {
			Target   struct{ Disk string }
			Packages struct{ Selected []string }
		} "yaml:\"install_plan\""
	}
	if err := yaml.Unmarshal(plan, &document); err != nil {
		return nil, err
	}
	if document.Plan.Target.Disk != c.Values["disk"] || len(document.Plan.Packages.Selected) == 0 {
		return nil, errors.New("plan disk mismatch or empty package selection")
	}
	if strings.ContainsAny(planPath, "\r\n\x00") {
		return nil, errors.New("invalid plan path")
	}
	var b strings.Builder
	fmt.Fprintf(&b, "version=2\nplan=%s\n", planPath)
	for _, key := range []string{"disk", "swap", "hostname", "user", "locale", "keymap", "timezone", "network", "network_interface", "address", "gateway", "dns", "profile", "runtime", "ai", "ai_endpoint"} {
		value := c.Values[key]
		if key == "dns" {
			value = strings.Join(strings.Fields(strings.ReplaceAll(value, ",", " ")), " ")
		}
		fmt.Fprintf(&b, "%s=%s\n", key, value)
	}
	fmt.Fprintf(&b, "password=%s\nconfirmed=INSTALL %s\n", c.Password, c.Values["disk"])
	for _, pkg := range document.Plan.Packages.Selected {
		if !packageName.MatchString(pkg) {
			return nil, errors.New("invalid package in plan")
		}
		fmt.Fprintf(&b, "package=%s\n", pkg)
	}
	if b.Len() >= 16384 {
		return nil, errors.New("install request is too large")
	}
	return []byte(b.String()), nil
}

// Atomic publication, without replacing an existing request; files are mode 0600.
func publish(path string, data []byte) error {
	dir := filepath.Dir(path)
	info, err := os.Lstat(dir)
	if err != nil {
		return err
	}
	if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return errors.New("request directory must be a real directory")
	}
	f, err := os.CreateTemp(dir, ".gotk-request-")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	if _, err = f.Write(data); err != nil {
		f.Close()
		return err
	}
	if err = f.Sync(); err != nil {
		f.Close()
		return err
	}
	if err = f.Close(); err != nil {
		return err
	}
	return os.Link(f.Name(), path)
}

type Progress struct {
	State, Phase, Message     string
	Percent, Installed, Total int
}

func parseProgress(data []byte) (Progress, error) {
	var p Progress
	bad := errors.New("invalid progress data")
	if len(data) == 0 || len(data) > 16384 || !utf8.Valid(data) || strings.ContainsRune(string(data), 0) {
		return p, bad
	}
	fields := map[string]string{}
	for _, line := range strings.Split(string(data), "\n") {
		if line == "" {
			continue
		}
		k, v, ok := strings.Cut(line, "=")
		if _, exists := fields[k]; !ok || k == "" || exists {
			return p, bad
		}
		fields[k] = v
	}
	if fields["version"] != "1" {
		return p, bad
	}
	p.State = fields["state"]
	p.Phase = fields["phase"]
	p.Message = fields["message"]
	switch p.State {
	case "running", "failed", "completed", "rebooting":
	default:
		return p, bad
	}
	for key, ptr := range map[string]*int{"percent": &p.Percent, "packages_installed": &p.Installed, "packages_total": &p.Total} {
		s := fields[key]
		if s == "" || strings.IndexFunc(s, func(r rune) bool { return r < '0' || r > '9' }) >= 0 {
			return p, bad
		}
		n, err := strconv.Atoi(s)
		if err != nil {
			return p, bad
		}
		*ptr = n
	}
	if p.Percent > 100 || p.Installed > p.Total {
		return p, bad
	}
	if (p.State == "completed" || p.State == "rebooting") && (p.Percent != 100 || p.Installed != p.Total) {
		return p, bad
	}
	return p, nil
}
func disks() []string {
	entries, _ := os.ReadDir("/sys/class/block")
	var result []string
	for _, e := range entries {
		if !diskName.MatchString(e.Name()) {
			continue
		}
		path := filepath.Join("/sys/class/block", e.Name())
		if _, err := os.Stat(filepath.Join(path, "partition")); err == nil {
			continue
		}
		ro, _ := os.ReadFile(filepath.Join(path, "ro"))
		if strings.TrimSpace(string(ro)) == "1" {
			continue
		}
		result = append(result, "/dev/"+e.Name())
	}
	return result
}
func nics() []string {
	entries, _ := os.ReadDir("/sys/class/net")
	var result []string
	for _, e := range entries {
		if _, err := os.Stat(filepath.Join("/sys/class/net", e.Name(), "device")); err == nil {
			result = append(result, e.Name())
		}
	}
	return result
}
