package imagefactory

import (
	"archive/tar"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

type Runner interface {
	Run(context.Context, string, string, ...string) error
}

type Worker struct {
	Runner   Runner
	RootDir  string
	Timeout  time.Duration
	Progress func(context.Context, string) error
}

type Result struct {
	BuildID           string   `json:"build_id"`
	ArtifactPath      string   `json:"artifact_path"`
	Digest            string   `json:"digest"`
	SizeBytes         int64    `json:"size_bytes"`
	VerifiedBootModes []string `json:"verified_boot_modes"`
}

func (worker Worker) Execute(ctx context.Context, task Task) (Result, error) {
	if worker.Runner == nil || worker.RootDir == "" {
		return Result{}, errors.New("worker runner and root directory are required")
	}
	if task.APIVersion != "factory.kiki.io/v1alpha1" || !task.Isolation.DisposableVMRequired || task.Isolation.GeneralNodeAllowed {
		return Result{}, errors.New("unsafe or unsupported Image Factory task")
	}
	if task.Request.Type != "iso" && task.Request.Type != "pxe" && task.Request.Type != "disk" {
		return Result{}, errors.New("worker supports ISO, PXE, and disk tasks")
	}
	timeout := worker.Timeout
	if timeout <= 0 {
		timeout = 90 * time.Minute
	}
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	if err := os.MkdirAll(worker.RootDir, 0o750); err != nil {
		return Result{}, fmt.Errorf("create artifact root: %w", err)
	}
	workspace, err := os.MkdirTemp(worker.RootDir, "kiki-image-factory-")
	if err != nil {
		return Result{}, err
	}
	defer os.RemoveAll(workspace)
	repository := filepath.Join(workspace, "source")
	if err := worker.Runner.Run(ctx, workspace, "git", "clone", "--no-checkout", "--filter=blob:none", task.Request.Source.URL, repository); err != nil {
		return Result{}, fmt.Errorf("clone source: %w", err)
	}
	if err := worker.Runner.Run(ctx, repository, "git", "checkout", "--detach", task.Request.Source.Revision); err != nil {
		return Result{}, fmt.Errorf("checkout source: %w", err)
	}
	if err := worker.report(ctx, "Validating"); err != nil {
		return Result{}, err
	}
	outDir := filepath.Join(workspace, "output")
	workDir := filepath.Join(workspace, "work")
	if err := os.MkdirAll(outDir, 0o750); err != nil {
		return Result{}, err
	}
	if err := worker.report(ctx, "Building"); err != nil {
		return Result{}, err
	}
	if task.Request.Type == "disk" {
		template := filepath.Join(repository, "installer/configs/install.example.yaml")
		if task.Request.BootModes[0] == "uefi" {
			template = filepath.Join(repository, "installer/configs/install.uefi.example.yaml")
		}
		configOutput := filepath.Join(repository, "installer/alpine/overlay/etc/kiki/install.yaml")
		renderScript := filepath.Join(repository, "installer/scripts/render-install-config.py")
		if err := worker.Runner.Run(ctx, repository, "python3", renderScript, "--template", template, "--hostname", "kiki-unprovisioned", "--role", "compute", "--disk", "/dev/vda", "--boot-mode", task.Request.BootModes[0], "--registration-disabled", "--output", configOutput); err != nil {
			return Result{}, fmt.Errorf("render credential-free disk install config: %w", err)
		}
	}
	buildScript := filepath.Join(repository, "installer/scripts/build-alpine-iso.sh")
	buildArguments := []string{buildScript, "--runner", "podman", "--release", task.Request.Release, "--arch", task.Request.Arch, "--work-dir", workDir, "--out-dir", outDir}
	if task.Request.Type == "disk" {
		buildArguments = append(buildArguments, "--autoinstall")
	}
	if err := worker.Runner.Run(ctx, repository, "sh", buildArguments...); err != nil {
		return Result{}, fmt.Errorf("build ISO: %w", err)
	}
	images, err := filepath.Glob(filepath.Join(outDir, "*.iso"))
	if err != nil || len(images) != 1 {
		return Result{}, fmt.Errorf("expected exactly one ISO output, got %d", len(images))
	}
	artifactSource := images[0]
	var kernel string
	var initramfs string
	if task.Request.Type == "pxe" {
		pxeRoot := filepath.Join(workspace, "pxe-root")
		if err := os.MkdirAll(pxeRoot, 0o750); err != nil {
			return Result{}, err
		}
		if err := worker.Runner.Run(ctx, repository, "xorriso", "-osirrox", "on", "-indev", images[0], "-extract", "/", pxeRoot); err != nil {
			return Result{}, fmt.Errorf("extract PXE root: %w", err)
		}
		kernel, initramfs, err = findPXEBootFiles(pxeRoot)
		if err != nil {
			return Result{}, err
		}
		if err := writeIPXEScript(pxeRoot, kernel, initramfs); err != nil {
			return Result{}, err
		}
		artifactSource = filepath.Join(workspace, task.Request.OutputName)
		if err := writeDeterministicTarGz(pxeRoot, artifactSource); err != nil {
			return Result{}, fmt.Errorf("package PXE bundle: %w", err)
		}
	} else if task.Request.Type == "disk" {
		disk := filepath.Join(workspace, "installed.qcow2")
		serial := filepath.Join(workspace, "install.log")
		testScript := filepath.Join(repository, "installer/scripts/test-qemu-install.sh")
		if err := worker.Runner.Run(ctx, repository, "sh", testScript, "--iso", images[0], "--mode", task.Request.BootModes[0], "--disk", disk, "--disk-size", "20G", "--memory", "4096", "--cpus", "2", "--smoke-seconds", "1800", "--serial-log", serial, "--expect", "KIKI_AUTOINSTALL_COMPLETE"); err != nil {
			return Result{}, fmt.Errorf("install %s disk image: %w", task.Request.BootModes[0], err)
		}
		serial = filepath.Join(workspace, "installed-boot.log")
		if err := worker.Runner.Run(ctx, repository, "sh", testScript, "--boot-disk", "--mode", task.Request.BootModes[0], "--disk", disk, "--memory", "2048", "--cpus", "2", "--smoke-seconds", "120", "--serial-log", serial, "--expect", "Debian GNU/Linux"); err != nil {
			return Result{}, fmt.Errorf("verify installed %s disk image: %w", task.Request.BootModes[0], err)
		}
		artifactSource = disk
	}
	if err := worker.report(ctx, "Testing"); err != nil {
		return Result{}, err
	}
	verified := append([]string(nil), task.Request.BootModes...)
	sort.Strings(verified)
	for _, mode := range verified {
		if task.Request.Type == "disk" {
			continue
		}
		disk := filepath.Join(workspace, "qemu-"+mode+".qcow2")
		serial := filepath.Join(workspace, "qemu-"+mode+".log")
		testScript := filepath.Join(repository, "installer/scripts/test-qemu-install.sh")
		arguments := []string{"--mode", mode, "--disk", disk, "--memory", "2048", "--cpus", "2", "--smoke-seconds", "45", "--serial-log", serial}
		if task.Request.Type == "iso" {
			arguments = append(arguments, "--iso", images[0], "--expect", "KIKI")
		} else {
			arguments = append(arguments, "--kernel", kernel, "--initrd", initramfs, "--append", "console=ttyS0", "--expect", "Alpine")
		}
		commandArguments := append([]string{testScript}, arguments...)
		if err := worker.Runner.Run(ctx, repository, "sh", commandArguments...); err != nil {
			return Result{}, fmt.Errorf("verify %s boot: %w", mode, err)
		}
	}
	artifact := filepath.Join(worker.RootDir, task.Request.OutputName)
	if _, err := os.Lstat(artifact); err == nil {
		return Result{}, fmt.Errorf("artifact already exists: %s", task.Request.OutputName)
	} else if !errors.Is(err, os.ErrNotExist) {
		return Result{}, err
	}
	if err := copyFile(artifactSource, artifact); err != nil {
		return Result{}, err
	}
	digest, size, err := hashFile(artifact)
	if err != nil {
		return Result{}, err
	}
	return Result{BuildID: task.Request.BuildID, ArtifactPath: artifact, Digest: digest, SizeBytes: size, VerifiedBootModes: verified}, nil
}

func findPXEBootFiles(root string) (string, string, error) {
	kernels, err := filepath.Glob(filepath.Join(root, "boot", "vmlinuz-*"))
	if err != nil || len(kernels) != 1 {
		return "", "", fmt.Errorf("PXE root requires exactly one kernel, got %d", len(kernels))
	}
	initramfs, err := filepath.Glob(filepath.Join(root, "boot", "initramfs-*"))
	if err != nil || len(initramfs) != 1 {
		return "", "", fmt.Errorf("PXE root requires exactly one initramfs, got %d", len(initramfs))
	}
	return kernels[0], initramfs[0], nil
}

func writeIPXEScript(root, kernel, initramfs string) error {
	kernelRelative, err := filepath.Rel(root, kernel)
	if err != nil {
		return err
	}
	initramfsRelative, err := filepath.Rel(root, initramfs)
	if err != nil {
		return err
	}
	content := "#!ipxe\nset base-url ${base-url}\nkernel ${base-url}/" + filepath.ToSlash(kernelRelative) + " console=ttyS0\ninitrd ${base-url}/" + filepath.ToSlash(initramfsRelative) + "\nboot\n"
	return os.WriteFile(filepath.Join(root, "boot.ipxe"), []byte(content), 0o640)
}

func writeDeterministicTarGz(root, destination string) error {
	file, err := os.OpenFile(destination, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o640)
	if err != nil {
		return err
	}
	committed := false
	defer func() {
		_ = file.Close()
		if !committed {
			_ = os.Remove(destination)
		}
	}()
	gzipWriter, err := gzip.NewWriterLevel(file, gzip.BestCompression)
	if err != nil {
		return err
	}
	gzipWriter.Header.ModTime = time.Unix(0, 0)
	gzipWriter.Header.OS = 255
	tarWriter := tar.NewWriter(gzipWriter)
	var paths []string
	err = filepath.Walk(root, func(path string, info os.FileInfo, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if path == root {
			return nil
		}
		if info.Mode()&os.ModeSymlink != 0 || (!info.Mode().IsRegular() && !info.IsDir()) {
			return fmt.Errorf("unsupported PXE entry: %s", path)
		}
		paths = append(paths, path)
		return nil
	})
	if err != nil {
		return err
	}
	sort.Strings(paths)
	for _, path := range paths {
		info, err := os.Stat(path)
		if err != nil {
			return err
		}
		relative, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		header, err := tar.FileInfoHeader(info, "")
		if err != nil {
			return err
		}
		header.Name = filepath.ToSlash(relative)
		header.ModTime = time.Unix(0, 0)
		header.AccessTime = time.Time{}
		header.ChangeTime = time.Time{}
		header.Uid = 0
		header.Gid = 0
		header.Uname = ""
		header.Gname = ""
		if info.IsDir() && !strings.HasSuffix(header.Name, "/") {
			header.Name += "/"
		}
		if err := tarWriter.WriteHeader(header); err != nil {
			return err
		}
		if info.Mode().IsRegular() {
			source, err := os.Open(path)
			if err != nil {
				return err
			}
			_, copyErr := io.Copy(tarWriter, source)
			closeErr := source.Close()
			if copyErr != nil {
				return copyErr
			}
			if closeErr != nil {
				return closeErr
			}
		}
	}
	if err := tarWriter.Close(); err != nil {
		return err
	}
	if err := gzipWriter.Close(); err != nil {
		return err
	}
	if err := file.Sync(); err != nil {
		return err
	}
	if err := file.Close(); err != nil {
		return err
	}
	committed = true
	return nil
}

func (worker Worker) report(ctx context.Context, phase string) error {
	if worker.Progress == nil {
		return nil
	}
	if err := worker.Progress(ctx, phase); err != nil {
		return fmt.Errorf("report %s phase: %w", phase, err)
	}
	return nil
}

func copyFile(source, destination string) error {
	input, err := os.Open(source)
	if err != nil {
		return err
	}
	defer input.Close()
	temporary, err := os.CreateTemp(filepath.Dir(destination), ".image-*.tmp")
	if err != nil {
		return err
	}
	name := temporary.Name()
	committed := false
	defer func() {
		_ = temporary.Close()
		if !committed {
			_ = os.Remove(name)
		}
	}()
	if err := temporary.Chmod(0o640); err != nil {
		return err
	}
	if _, err := io.Copy(temporary, input); err != nil {
		return err
	}
	if err := temporary.Sync(); err != nil {
		return err
	}
	if err := temporary.Close(); err != nil {
		return err
	}
	if err := os.Rename(name, destination); err != nil {
		return err
	}
	committed = true
	return nil
}

func hashFile(path string) (string, int64, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", 0, err
	}
	defer file.Close()
	hash := sha256.New()
	size, err := io.Copy(hash, file)
	if err != nil {
		return "", 0, err
	}
	return "sha256:" + hex.EncodeToString(hash.Sum(nil)), size, nil
}
