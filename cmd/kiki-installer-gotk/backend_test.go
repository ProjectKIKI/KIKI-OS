package main

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func validConfig() Config {
	c := defaults()
	c.Values["disk"] = "/dev/sda"
	c.Values["network_interface"] = "eth0"
	c.Password = "lab-password"
	c.Confirmation = c.Password
	c.Erase = true
	return c
}

func TestInstallerSessionDoesNotRequirePremountedMedia(t *testing.T) {
	if !installerSession("console=tty0 kiki.boot=installer kiki.ui=gui") {
		t.Fatal("installer session rejected")
	}
	for _, line := range []string{"", "kiki.boot=installed", "other=kiki.boot=installer", "kiki.boot=installer-unsafe"} {
		if installerSession(line) {
			t.Fatal("non-installer session accepted")
		}
	}
}

var validPlan = []byte("install_plan:\n  target:\n    disk: /dev/sda\n  packages:\n    selected: [base-files, systemd]\n")

func TestRequestProtocol(t *testing.T) {
	c := validConfig()
	c.Values["dns"] = "1.1.1.1,8.8.8.8"
	b, err := c.request("/run/kiki/plan.yaml", validPlan)
	if err != nil {
		t.Fatal(err)
	}
	for _, s := range []string{"version=2\n", "confirmed=INSTALL /dev/sda\n", "package=base-files\n", "network_interface=eth0\n", "dns=1.1.1.1 8.8.8.8\n"} {
		if !strings.Contains(string(b), s) {
			t.Fatalf("missing %q", s)
		}
	}
	if strings.Contains(strings.Join(c.planArgs("/tmp/plan"), " "), c.Password) {
		t.Fatal("password leaked into process arguments")
	}
}
func TestRejectUnsafeInputs(t *testing.T) {
	for _, tc := range []struct {
		name   string
		mutate func(*Config)
	}{
		{"partition", func(c *Config) { c.Values["disk"] = "/dev/sda1" }},
		{"missing consent", func(c *Config) { c.Erase = false }},
		{"password mismatch", func(c *Config) { c.Confirmation = "different" }},
		{"short password", func(c *Config) { c.Password = "123" }},
		{"newline", func(c *Config) { c.Values["hostname"] = "host\npackage=bad" }},
		{"password injection", func(c *Config) { c.Password = "long\npassword" }},
		{"static prefix", func(c *Config) { c.Values["network"] = "static"; c.Values["address"] = "10.0.2.15" }},
		{"dns", func(c *Config) { c.Values["dns"] = "not-a-dns" }},
		{"no nic", func(c *Config) { c.Values["network_interface"] = "" }},
		{"kube swap", func(c *Config) { c.Values["profile"] = "kiki-kube-compute"; c.Values["swap"] = "on" }},
	} {
		t.Run(tc.name, func(t *testing.T) {
			c := validConfig()
			tc.mutate(&c)
			if _, err := c.request("/run/plan", validPlan); err == nil {
				t.Fatal("accepted invalid request")
			}
		})
	}
}
func TestRejectPlanMismatch(t *testing.T) {
	c := validConfig()
	for _, plan := range []string{strings.ReplaceAll(string(validPlan), "/dev/sda", "/dev/sdb"), "install_plan: {}", strings.ReplaceAll(string(validPlan), "base-files", "'bad\nname'")} {
		if _, err := c.request("/run/plan", []byte(plan)); err == nil {
			t.Fatal("accepted malformed plan")
		}
	}
}
func TestPublishPrivateAndExclusive(t *testing.T) {
	path := filepath.Join(t.TempDir(), "request")
	if err := publish(path, []byte("first")); err != nil {
		t.Fatal(err)
	}
	st, _ := os.Stat(path)
	if st.Mode().Perm() != 0600 {
		t.Fatalf("unsafe mode: %s", st.Mode())
	}
	if err := publish(path, []byte("second")); err == nil {
		t.Fatal("overwrote request")
	}
	b, _ := os.ReadFile(path)
	if string(b) != "first" {
		t.Fatal("request changed")
	}
	entries, _ := os.ReadDir(filepath.Dir(path))
	if len(entries) != 1 {
		t.Fatal("temporary secret file leaked")
	}
}
func TestProgress(t *testing.T) {
	base := "version=1\nstate=running\npercent=40\npackages_installed=2\npackages_total=5\nphase=packages\nmessage=Installing\n"
	if p, err := parseProgress([]byte(base)); err != nil || p.Percent != 40 {
		t.Fatalf("%+v %v", p, err)
	}
	for _, s := range []string{base + "percent=1\n", strings.Replace(base, "40", "101", 1), strings.Replace(base, "running", "completed", 1), strings.Replace(base, "=2\n", "=6\n", 1), base + "\x00"} {
		if _, err := parseProgress([]byte(s)); err == nil {
			t.Fatal("invalid progress accepted")
		}
	}
	complete := strings.NewReplacer("running", "completed", "percent=40", "percent=100", "installed=2", "installed=5").Replace(base)
	if _, err := parseProgress([]byte(complete)); err != nil {
		t.Fatal(err)
	}
}
func TestRealPlanner(t *testing.T) {
	binary := os.Getenv("KIKI_TEST_TUI")
	if binary == "" {
		t.Skip("set KIKI_TEST_TUI to test the existing installer planner")
	}
	c := validConfig()
	plan, err := generatePlan(context.Background(), binary, filepath.Join(t.TempDir(), "plan.yaml"), c)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(plan), c.Password) {
		t.Fatal("password leaked into plan")
	}
	if _, err = c.request("/run/kiki/plan.yaml", plan); err != nil {
		t.Fatal(err)
	}
}
