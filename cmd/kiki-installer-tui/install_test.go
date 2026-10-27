package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestInstallRequestValidation(t *testing.T) {
	plan := NewDefaultPlan("server-core")
	plan.Target.Disk = "/dev/sda"
	good, err := installRequest(plan, "/run/kiki/install-plan.yaml", "test-password", "INSTALL /dev/sda")
	if err != nil {
		t.Fatal(err)
	}
	for _, text := range []string{"version=2\n", "disk=/dev/sda\n", "password=test-password\n", "package="} {
		if !bytes.Contains(good, []byte(text)) {
			t.Fatalf("missing %q", text)
		}
	}
	for _, password := range []string{"short", "test-password\npackage=evil", strings.Repeat("x", 96)} {
		if _, err := installRequest(plan, "/run/plan", password, "INSTALL /dev/sda"); err == nil {
			t.Fatal("invalid password accepted")
		}
	}
	if _, err := installRequest(plan, "/run/plan", "test-password", "INSTALL /dev/sdb"); err == nil {
		t.Fatal("wrong disk accepted")
	}
	plan.Source.Type = "remote"
	if _, err := installRequest(plan, "/run/plan", "test-password", "INSTALL /dev/sda"); err == nil {
		t.Fatal("remote source accepted")
	}
}

func TestDHCPWithManualDNS(t *testing.T) {
	plan := NewDefaultPlan("server-core")
	if err := applyNetwork(&plan, "dhcp", "eth0", "", "", "1.1.1.1,8.8.8.8"); err != nil {
		t.Fatal(err)
	}
	if plan.Network.DNS != "1.1.1.1 8.8.8.8" || !plan.Network.DHCP4 {
		t.Fatalf("manual DNS lost: %+v", plan.Network)
	}
	if err := applyNetwork(&plan, "off", "eth0", "", "", "1.1.1.1"); err != nil {
		t.Fatal(err)
	}
	if plan.Network.DNS != "" {
		t.Fatal("offline mode retained DNS")
	}
}

func TestPrivateRequestPermissions(t *testing.T) {
	path := filepath.Join(t.TempDir(), "request")
	if err := writePrivateRequest(path, []byte("secret")); err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0600 {
		t.Fatalf("request permissions: %v", info.Mode())
	}
	data, err := os.ReadFile(path)
	if err != nil || string(data) != "secret" {
		t.Fatal("request content mismatch")
	}
}

func TestPasswordInputDoesNotEcho(t *testing.T) {
	var out bytes.Buffer
	secret, ok, err := readPassword(strings.NewReader("password-test\r"), &out, "Password")
	if err != nil || !ok || secret != "password-test" {
		t.Fatal("password input failed")
	}
	if strings.Contains(out.String(), secret) {
		t.Fatal("password leaked to terminal")
	}
}

func TestKoreanPasswordBackspaceAndInvalidUTF8(t *testing.T) {
	for _, erase := range []string{"\x7f", "\x08"} {
		var out bytes.Buffer
		got, ok, err := readPassword(strings.NewReader("암호가"+erase+"나1234\r"), &out, "Password")
		if err != nil || !ok || got != "암호나1234" {
			t.Fatalf("Korean backspace failed: %q, %v", got, err)
		}
		if strings.Contains(out.String(), "암호") {
			t.Fatal("Korean password was echoed")
		}
	}
	plan := NewDefaultPlan("server-core")
	plan.Target.Disk = "/dev/sda"
	if _, err := installRequest(plan, "/run/plan", "암호나1234", "INSTALL /dev/sda"); err != nil {
		t.Fatal("valid Korean password rejected", err)
	}
	if _, err := installRequest(plan, "/run/plan", "password\xff", "INSTALL /dev/sda"); err == nil {
		t.Fatal("malformed UTF-8 password accepted")
	}
}

func TestInstallProgressValidation(t *testing.T) {
	input := "version=1\nstate=running\npercent=50\npackages_installed=2\npackages_total=10\npackage=test\n"
	p, err := parseInstallProgress([]byte(input))
	if err != nil || p.Percent != 50 || p.Installed != 2 || p.Total != 10 {
		t.Fatal("progress parse failed", err)
	}
	for _, bad := range []string{input + "state=completed\n", strings.Replace(input, "percent=50", "percent=101", 1), strings.Replace(input, "packages_installed=2", "packages_installed=11", 1)} {
		if _, err := parseInstallProgress([]byte(bad)); err == nil {
			t.Fatal("invalid progress accepted")
		}
	}
}

func TestProgressWatchIsAdvisoryAndRecovers(t *testing.T) {
	now := time.Unix(1000, 0)
	w := progressWatch{}
	if got := w.observe(now, []byte("running=1"), true); got != "" {
		t.Fatal(got)
	}
	if got := w.observe(now.Add(2*time.Minute), []byte("running=1"), true); !strings.Contains(got, "does not prove") {
		t.Fatal("missing advisory", got)
	}
	if got := w.observe(now.Add(3*time.Minute), nil, false); !strings.Contains(got, "Do not reboot") {
		t.Fatal("missing status-loss warning", got)
	}
	if got := w.observe(now.Add(4*time.Minute), []byte("running=2"), true); got != "" {
		t.Fatal("warning did not clear after new progress", got)
	}
}

func TestIncompleteCompletionRejected(t *testing.T) {
	base := "version=1\nstate=completed\npercent=100\npackages_installed=10\npackages_total=10\n"
	if _, err := parseInstallProgress([]byte(base)); err != nil {
		t.Fatal(err)
	}
	for _, bad := range []string{strings.Replace(base, "percent=100", "percent=99", 1), strings.Replace(base, "packages_installed=10", "packages_installed=9", 1)} {
		if _, err := parseInstallProgress([]byte(bad)); err == nil {
			t.Fatal("incomplete installation accepted as completed")
		}
	}
}
