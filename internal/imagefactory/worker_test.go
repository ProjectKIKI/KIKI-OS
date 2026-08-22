package imagefactory

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"example.com/aos-pkg/internal/buildsystem"
)

type fakeRunner struct{ calls []string }

func (runner *fakeRunner) Run(_ context.Context, directory, name string, args ...string) error {
	runner.calls = append(runner.calls, name+" "+strings.Join(args, " "))
	if name == "git" && len(args) > 0 && args[0] == "clone" {
		return os.MkdirAll(args[len(args)-1], 0o750)
	}
	if name == "sh" && strings.HasSuffix(args[0], "build-alpine-iso.sh") {
		for index, arg := range args {
			if arg == "--out-dir" {
				if err := os.MkdirAll(args[index+1], 0o750); err != nil {
					return err
				}
				return os.WriteFile(filepath.Join(args[index+1], "generated.iso"), []byte("ISO"), 0o640)
			}
		}
	}
	if name == "xorriso" {
		root := args[len(args)-1]
		if err := os.MkdirAll(filepath.Join(root, "boot"), 0o750); err != nil {
			return err
		}
		if err := os.WriteFile(filepath.Join(root, "boot", "vmlinuz-lts"), []byte("KERNEL"), 0o640); err != nil {
			return err
		}
		return os.WriteFile(filepath.Join(root, "boot", "initramfs-lts"), []byte("INITRD"), 0o640)
	}
	if name == "sh" && strings.HasSuffix(args[0], "test-qemu-install.sh") {
		for index, arg := range args {
			if arg == "--disk" {
				if _, err := os.Stat(args[index+1]); os.IsNotExist(err) {
					return os.WriteFile(args[index+1], []byte("QCOW2"), 0o640)
				}
			}
		}
	}
	return nil
}

func TestWorkerExecutesAllowListedISOFlow(t *testing.T) {
	root := t.TempDir()
	runner := &fakeRunner{}
	var phases []string
	task, err := CreateTask(Request{BuildID: "image-0001", Type: "iso", Source: buildsystem.Source{URL: "https://git.example.com/kiki/os.git", Revision: "aabbccddaabbccddaabbccddaabbccddaabbccdd"}, Release: "v3.20", Arch: "x86_64", BootModes: []string{"bios", "uefi"}, OutputName: "kiki.iso"}, []string{"git.example.com"})
	if err != nil {
		t.Fatal(err)
	}
	result, err := (Worker{Runner: runner, RootDir: root, Progress: func(_ context.Context, phase string) error {
		phases = append(phases, phase)
		return nil
	}}).Execute(context.Background(), task)
	if err != nil {
		t.Fatal(err)
	}
	if result.SizeBytes != 3 || !strings.HasPrefix(result.Digest, "sha256:") || len(result.VerifiedBootModes) != 2 {
		t.Fatalf("unexpected result: %#v", result)
	}
	if len(runner.calls) != 5 {
		t.Fatalf("expected clone, checkout, build, BIOS and UEFI verification: %#v", runner.calls)
	}
	if strings.Join(phases, ",") != "Validating,Building,Testing" {
		t.Fatalf("unexpected progress: %#v", phases)
	}
	if _, err := os.Stat(filepath.Join(root, "kiki.iso")); err != nil {
		t.Fatal(err)
	}
}

func TestWorkerRejectsNonDisposableTask(t *testing.T) {
	task := Task{APIVersion: "factory.kiki.io/v1alpha1", Request: Request{Type: "iso"}, Isolation: Isolation{GeneralNodeAllowed: true}}
	if _, err := (Worker{Runner: &fakeRunner{}, RootDir: t.TempDir()}).Execute(context.Background(), task); err == nil {
		t.Fatal("unsafe task accepted")
	}
}

func TestWorkerBuildsAndVerifiesPXEBundle(t *testing.T) {
	root := t.TempDir()
	runner := &fakeRunner{}
	task, err := CreateTask(Request{BuildID: "pxe-0001", Type: "pxe", Source: buildsystem.Source{URL: "https://git.example.com/kiki/os.git", Revision: "aabbccddaabbccddaabbccddaabbccddaabbccdd"}, Release: "v3.20", Arch: "x86_64", BootModes: []string{"bios", "uefi"}, OutputName: "kiki-pxe.tar.gz"}, []string{"git.example.com"})
	if err != nil {
		t.Fatal(err)
	}
	result, err := (Worker{Runner: runner, RootDir: root}).Execute(context.Background(), task)
	if err != nil {
		t.Fatal(err)
	}
	if result.SizeBytes == 0 || len(result.VerifiedBootModes) != 2 {
		t.Fatalf("unexpected PXE result: %#v", result)
	}
	if !strings.Contains(strings.Join(runner.calls, "\n"), "xorriso -osirrox on") || !strings.Contains(strings.Join(runner.calls, "\n"), "--kernel ") {
		t.Fatalf("PXE extraction or direct-kernel boot missing: %#v", runner.calls)
	}
	if _, err := os.Stat(filepath.Join(root, "kiki-pxe.tar.gz")); err != nil {
		t.Fatal(err)
	}
}

func TestWorkerBuildsCredentialFreeInstalledDisk(t *testing.T) {
	root := t.TempDir()
	runner := &fakeRunner{}
	task, err := CreateTask(Request{BuildID: "disk-0001", Type: "disk", Source: buildsystem.Source{URL: "https://git.example.com/kiki/os.git", Revision: "aabbccddaabbccddaabbccddaabbccddaabbccdd"}, Release: "v3.20", Arch: "x86_64", BootModes: []string{"uefi"}, OutputName: "kiki-uefi.qcow2"}, []string{"git.example.com"})
	if err != nil {
		t.Fatal(err)
	}
	result, err := (Worker{Runner: runner, RootDir: root}).Execute(context.Background(), task)
	if err != nil {
		t.Fatal(err)
	}
	commands := strings.Join(runner.calls, "\n")
	if !strings.Contains(commands, "--registration-disabled") || !strings.Contains(commands, "--autoinstall") || !strings.Contains(commands, "--boot-disk") || !strings.Contains(commands, "KIKI_AUTOINSTALL_COMPLETE") {
		t.Fatalf("disk safety or verification step missing: %s", commands)
	}
	if result.SizeBytes != 5 || len(result.VerifiedBootModes) != 1 || result.VerifiedBootModes[0] != "uefi" {
		t.Fatalf("unexpected disk result: %#v", result)
	}
}
