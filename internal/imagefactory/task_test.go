package imagefactory

import (
	"testing"

	"example.com/aos-pkg/internal/buildsystem"
)

func TestCreateIsolatedImageFactoryTask(t *testing.T) {
	task, err := CreateTask(Request{BuildID: "image-0001", Type: "iso", Source: buildsystem.Source{URL: "https://git.example.com/kiki/os.git", Revision: "aabbccddaabbccddaabbccddaabbccddaabbccdd"}, Release: "v3.20", Arch: "x86_64", BootModes: []string{"uefi", "bios"}, OutputName: "kiki.iso"}, []string{"git.example.com"})
	if err != nil {
		t.Fatal(err)
	}
	if !task.Isolation.DisposableVMRequired || task.Isolation.GeneralNodeAllowed {
		t.Fatalf("unsafe isolation: %#v", task.Isolation)
	}
	if len(task.Steps) != 7 || task.Steps[3] != "qemu.verify.bios" || task.Steps[4] != "qemu.verify.uefi" {
		t.Fatalf("unexpected steps: %#v", task.Steps)
	}
}

func TestCreateImageFactoryTaskRejectsMutableOrGeneralInputs(t *testing.T) {
	request := Request{BuildID: "image-1", Type: "iso", Source: buildsystem.Source{URL: "https://git.example.com/os.git", Revision: "main"}, Release: "v3.20", Arch: "x86_64", BootModes: []string{"bios"}, OutputName: "kiki.iso"}
	if _, err := CreateTask(request, []string{"git.example.com"}); err == nil {
		t.Fatal("mutable revision accepted")
	}
	request.Source.Revision = "aabbccddaabbccddaabbccddaabbccddaabbccdd"
	request.Source.URL = "https://evil.example/os.git"
	if _, err := CreateTask(request, []string{"git.example.com"}); err == nil {
		t.Fatal("untrusted source accepted")
	}
}

func TestDiskTaskRequiresOneBootMode(t *testing.T) {
	request := Request{BuildID: "disk-0001", Type: "disk", Source: buildsystem.Source{URL: "https://git.example.com/kiki/os.git", Revision: "aabbccddaabbccddaabbccddaabbccddaabbccdd"}, Release: "v3.20", Arch: "x86_64", BootModes: []string{"bios", "uefi"}, OutputName: "kiki.qcow2"}
	if _, err := CreateTask(request, []string{"git.example.com"}); err == nil {
		t.Fatal("multi-firmware disk artifact was accepted")
	}
}
