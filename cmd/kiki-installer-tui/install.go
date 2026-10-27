package main

import (
	"bytes"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
)

const requestPath = "/run/kiki/gui-install.request"
const progressPath = "/run/kiki/install-progress.state"
const rebootPath = "/run/kiki/gui-reboot.request"
const backendReadyPath = "/run/kiki/tui-backend.ready"

func installRequest(plan InstallPlan, planPath, password, confirmation string) ([]byte, error) {
	if !ReviewReady(plan) || plan.Source.Type != "local-installer-media" {
		return nil, fmt.Errorf("a valid local install plan is required")
	}
	if len(password) < 8 || len(password) > 95 {
		return nil, fmt.Errorf("password must be 8-95 UTF-8 bytes")
	}
	if confirmation != "INSTALL "+plan.Target.Disk {
		return nil, fmt.Errorf("disk erase confirmation did not match")
	}
	swap := "off"
	if plan.Target.Filesystems.Swap.Enabled {
		swap = "on"
	}
	fields := [][2]string{{"version", "2"}, {"plan", planPath}, {"disk", plan.Target.Disk},
		{"swap", swap}, {"hostname", plan.Identity.Hostname}, {"user", plan.Users.Admin.Name},
		{"password", password}, {"confirmed", confirmation}, {"locale", plan.Localization.Locale},
		{"keymap", plan.Localization.Keymap}, {"timezone", plan.Localization.Timezone},
		{"network", plan.Network.Mode}, {"network_interface", plan.Network.InterfaceMatch},
		{"address", plan.Network.Address}, {"gateway", plan.Network.Gateway}, {"dns", plan.Network.DNS},
		{"profile", plan.Packages.Profile}, {"runtime", plan.Runtime.ContainerRuntime},
		{"ai", plan.AI.Mode}, {"ai_endpoint", plan.AI.Endpoint}}
	for _, name := range plan.Packages.Selected {
		fields = append(fields, [2]string{"package", name})
	}
	var out bytes.Buffer
	for _, field := range fields {
		if !utf8.ValidString(field[1]) {
			return nil, fmt.Errorf("invalid UTF-8 in %s", field[0])
		}
		if strings.ContainsAny(field[1], "\r\n\x00") {
			return nil, fmt.Errorf("invalid control character in %s", field[0])
		}
		fmt.Fprintf(&out, "%s=%s\n", field[0], field[1])
	}
	if out.Len() >= 16*1024 {
		return nil, fmt.Errorf("install request too large")
	}
	return out.Bytes(), nil
}

func writePrivateRequest(path string, data []byte) error {
	file, err := os.CreateTemp(filepath.Dir(path), ".install-request-")
	if err != nil {
		return err
	}
	name := file.Name()
	defer os.Remove(name)
	if _, err = file.Write(data); err == nil {
		err = file.Sync()
	}
	closeErr := file.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	return os.Rename(name, path)
}

func readPassword(in io.Reader, out io.Writer, label string) (string, bool, error) {
	fmt.Fprintf(out, "\r\n%s: ", label)
	var password []byte
	defer func() {
		for i := range password {
			password[i] = 0
		}
	}()
	for {
		var b [1]byte
		if _, err := io.ReadFull(in, b[:]); err != nil {
			return "", false, err
		}
		switch b[0] {
		case '\r', '\n':
			fmt.Fprint(out, "\r\n")
			return string(password), true, nil
		case 27, 3:
			return "", false, nil
		case 127, 8:
			if len(password) > 0 {
				_, size := utf8.DecodeLastRune(password)
				end := len(password) - size
				for i := end; i < len(password); i++ {
					password[i] = 0
				}
				password = password[:end]
			}
		default:
			if b[0] >= 32 && len(password) < 96 {
				password = append(password, b[0])
			}
		}
	}
}

type installProgress struct {
	State                     string
	Percent, Installed, Total int
	Package                   string
}

func parseInstallProgress(data []byte) (installProgress, error) {
	values := map[string]string{}
	for _, line := range strings.Split(string(data), "\n") {
		if line == "" {
			continue
		}
		key, value, ok := strings.Cut(line, "=")
		if !ok {
			return installProgress{}, fmt.Errorf("invalid progress line")
		}
		if _, exists := values[key]; exists {
			return installProgress{}, fmt.Errorf("duplicate progress field")
		}
		values[key] = value
	}
	p := installProgress{State: values["state"], Package: values["package"]}
	if values["version"] != "1" {
		return p, fmt.Errorf("unsupported progress version")
	}
	for key, dest := range map[string]*int{"percent": &p.Percent, "packages_installed": &p.Installed, "packages_total": &p.Total} {
		n, err := strconv.Atoi(values[key])
		if err != nil || n < 0 {
			return p, fmt.Errorf("invalid progress number")
		}
		*dest = n
	}
	if p.Percent > 100 || p.Installed > p.Total {
		return p, fmt.Errorf("invalid progress range")
	}
	if p.State == "completed" && (p.Percent != 100 || p.Installed != p.Total) {
		return p, fmt.Errorf("inconsistent completion status")
	}
	switch p.State {
	case "running", "failed", "completed", "rebooting":
	default:
		return p, fmt.Errorf("invalid progress state")
	}
	return p, nil
}

type progressWatch struct {
	lastChange time.Time
	lastData   string
}

func (w *progressWatch) observe(now time.Time, raw []byte, valid bool) string {
	if w.lastChange.IsZero() {
		w.lastChange = now
	}
	if valid && string(raw) != w.lastData {
		w.lastData = string(raw)
		w.lastChange = now
	}
	if !valid {
		return "Progress status unavailable or invalid. Installation may still be running.\r\nDo not reboot. Check /run/kiki/tui-install.log from the recovery shell."
	}
	if now.Sub(w.lastChange) >= 2*time.Minute {
		return "Progress unchanged for 2+ minutes; this does not prove installation failed.\r\nDo not reboot. Check /run/kiki/tui-install.log from the recovery shell."
	}
	return ""
}

func (t *TUI) startFullscreenInstall() (string, bool, error) {
	if _, err := os.Stat(backendReadyPath); err != nil {
		return "", false, fmt.Errorf("installation backend unavailable; boot the installer ISO")
	}
	password, ok, err := readPassword(t.In, t.Out, "Administrator password (not displayed)")
	if err != nil || !ok {
		return "Cancelled", false, err
	}
	confirmPassword, ok, err := readPassword(t.In, t.Out, "Repeat password")
	if err != nil || !ok {
		return "Cancelled", false, err
	}
	if password != confirmPassword {
		return "", false, fmt.Errorf("passwords do not match")
	}
	confirmation, ok, err := readFullscreenValue(t.In, t.Out, "Erase ALL data on "+t.Plan.Target.Disk+"? [y/N]", "")
	if err != nil || !ok {
		return "Cancelled", false, err
	}
	if !strings.EqualFold(strings.TrimSpace(confirmation), "y") && !strings.EqualFold(strings.TrimSpace(confirmation), "yes") {
		return "Cancelled", false, nil
	}
	data, err := installRequest(t.Plan, t.PlanPath, password, "INSTALL "+t.Plan.Target.Disk)
	password = ""
	confirmPassword = ""
	if err != nil {
		return "", false, err
	}
	defer func() {
		for i := range data {
			data[i] = 0
		}
	}()
	if err = WritePlanFile(t.PlanPath, t.Plan); err != nil {
		return "", false, err
	}
	if err = writePrivateRequest(requestPath, data); err != nil {
		return "", false, err
	}
	for i := range data {
		data[i] = 0
	}
	t.PlanWritten = true
	fmt.Fprint(t.Out, "\x1b[2J\x1b[HInstallation requested. Waiting for backend...\r\n")
	rebootRequested := false
	watch := progressWatch{lastChange: time.Now()}
	for {
		raw, readErr := os.ReadFile(progressPath)
		validProgress := false
		if readErr == nil {
			p, parseErr := parseInstallProgress(raw)
			if parseErr == nil {
				validProgress = true
				name := strings.Map(func(r rune) rune {
					if r < 32 || r > 126 {
						return '?'
					}
					return r
				}, p.Package)
				filled := p.Percent * 30 / 100
				fmt.Fprintf(t.Out, "\x1b[2J\x1b[HKIKI OS installation\r\n[%s%s] %d%%\r\nPackages completed: %d / %d\r\nCurrent: %s\r\nState: %s\r\nLog: /run/kiki/tui-install.log\r\n", strings.Repeat("#", filled), strings.Repeat("-", 30-filled), p.Percent, p.Installed, p.Total, name, p.State)
				if p.State == "failed" || (p.State == "completed" && !rebootRequested) {
					fmt.Fprint(t.Out, "\r\nPress q to return to CLI.")
					if p.State == "completed" {
						fmt.Fprint(t.Out, " Press r to confirm reboot.")
					}
					for {
						key, err := readFullscreenKey(t.In)
						if err != nil {
							return "", true, err
						}
						if key == "q" || key == "Q" {
							return "", true, nil
						}
						if p.State == "completed" && (key == "r" || key == "R") {
							err = writePrivateRequest(rebootPath, []byte("reboot\n"))
							if err != nil {
								return "", true, err
							}
							fmt.Fprint(t.Out, "\r\nReboot requested.\r\n")
							rebootRequested = true
							break
						}
					}
				}
			}
		}
		notice := watch.observe(time.Now(), raw, validProgress)
		fmt.Fprintf(t.Out, "\x1b[11;1H\x1b[J%s", notice)
		time.Sleep(200 * time.Millisecond)
	}
}
