import gzip
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

import ki2bootiso


class Ki2BootIsoTests(unittest.TestCase):
    @staticmethod
    def write_fake_package(path: Path, files: dict[str, bytes]) -> None:
        with tarfile.open(path, "w:gz") as tar:
            for rel, payload in files.items():
                info = tarfile.TarInfo(f"rootfs/{rel}")
                info.size = len(payload)
                info.mode = 0o755
                tar.addfile(info, io.BytesIO(payload))

    def test_iso_default_output_uses_date_and_revision_stamp(self):
        root = Path("/repo")
        build_info = {"stamp": ki2bootiso.format_iso_build_stamp("2026-05-26", "42")}

        output = ki2bootiso.default_iso_output(root, "stage2-v2", "installer", "x86_64", build_info)

        self.assertEqual(output, root / "dist/iso/kiki-stage2-v2-installer-x86_64-20260526-rev42.iso")

    def test_dirty_iso_build_stamp_can_be_made_unique(self):
        stamp = f"{ki2bootiso.format_iso_build_stamp('2026-08-25', '20')}-dirty-a6b3a3e"
        output = ki2bootiso.default_iso_output(
            Path("/repo"), "stage3-v3", "installer", "x86_64", {"stamp": stamp}
        )

        self.assertEqual(
            output,
            Path("/repo/dist/iso/kiki-stage3-v3-installer-x86_64-20260825-rev20-dirty-a6b3a3e.iso"),
        )

    def test_iso_release_name_prefers_repository_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "metadata.x86_64.json").write_text('{"channel":"stage2-v2"}\n', encoding="utf-8")

            self.assertEqual(ki2bootiso.iso_release_name(repo, "x86_64", "bootstrap-stage1"), "stage2-v2")
            self.assertEqual(ki2bootiso.iso_release_name(repo, "x86_64", "bootstrap-stage1", "testing"), "testing")

    def test_iso_release_name_uses_stage1_fallback_without_repository_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)

            self.assertEqual(ki2bootiso.iso_release_name(repo, "x86_64", "bootstrap-stage1"), "stage1-v1")

    def test_prepare_boot_iso_tree_writes_boot_files_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rootfs = root / "rootfs"
            repo = root / "repo"
            packages = root / "packages"
            tree = root / "iso-tree"
            kernel = root / "vmlinuz-kiki"
            initramfs = root / "initramfs-kiki.img"

            (rootfs / "etc").mkdir(parents=True)
            (repo / "packages").mkdir(parents=True)
            packages.mkdir()
            (rootfs / "etc/os-release").write_text("ID=kiki-test\n", encoding="utf-8")
            (repo / "index.x86_64.json").write_text(
                '{"packages":[{"name":"base-files","file":"base-files-1-1.x86_64.ki2"}]}\n',
                encoding="utf-8",
            )
            (packages / "base-files-1-1.x86_64.ki2").write_bytes(b"fake-package")
            kernel.write_bytes(b"fake-kernel")
            initramfs.write_bytes(b"fake-initramfs")

            manifest = ki2bootiso.prepare_boot_iso_tree(
                rootfs,
                repo,
                tree,
                kernel=kernel,
                initramfs=initramfs,
                arch="x86_64",
                profile="bootstrap-stage1",
                label="KIKI_TEST_BOOT",
                packages_dir=packages,
            )

            self.assertEqual(manifest["schema"], "ki2-bootiso-v1")
            self.assertTrue(manifest["bootable"])
            self.assertEqual(manifest["boot_mode"], "vm-smoke")
            self.assertTrue(manifest["firmware"]["bios"])
            self.assertTrue(manifest["firmware"]["uefi"])
            self.assertFalse(manifest["firmware"]["secure_boot"])
            self.assertTrue((tree / "boot/vmlinuz-kiki").exists())
            self.assertTrue((tree / "boot/initramfs-kiki.img").exists())
            self.assertTrue((tree / "kiki/rootfs.tar.gz").exists())
            self.assertEqual((tree / "kiki/packages/x86_64/base-files-1-1.x86_64.ki2").read_bytes(), b"fake-package")
            self.assertEqual(manifest["package_media"]["copied"], 1)
            self.assertIn("initrd /boot/initramfs-kiki.img", (tree / "boot/grub/grub.cfg").read_text())

            manifest_file = json.loads((tree / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest_file["profile"], "bootstrap-stage1")

    def test_prepare_boot_iso_tree_can_enable_installer_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rootfs = root / "rootfs"
            repo = root / "repo"
            tree = root / "iso-tree"
            kernel = root / "vmlinuz-kiki"
            initramfs = root / "initramfs-kiki.img"

            rootfs.mkdir()
            repo.mkdir()
            kernel.write_bytes(b"fake-kernel")
            initramfs.write_bytes(b"fake-initramfs")
            install_image = root / "kiki-stage1.img"
            install_image.write_bytes(b"fake-install-image")
            installed_initramfs = root / "installed-initramfs.img"
            installed_initramfs.write_bytes(b"fake-installed-initramfs")
            efi_bootloader = root / "BOOTX64.EFI"
            efi_bootloader.write_bytes(b"fake-efi")

            manifest = ki2bootiso.prepare_boot_iso_tree(
                rootfs,
                repo,
                tree,
                kernel=kernel,
                initramfs=initramfs,
                arch="x86_64",
                profile="bootstrap-stage1",
                label="KIKI_TEST_INSTALLER",
                installer=True,
                install_image=install_image,
                installed_initramfs=installed_initramfs,
                efi_bootloader=efi_bootloader,
            )

            self.assertEqual(manifest["boot_mode"], "installer-stage1")
            self.assertTrue(manifest["installer"]["enabled"])
            self.assertEqual(
                manifest["installer"]["strategy"],
                "guided-disk-partition-format-extract-selected-packages-uefi-boot",
            )
            self.assertTrue(manifest["installer"]["package_selection"])
            self.assertEqual(manifest["installer"]["install_image"]["size"], len(b"fake-install-image"))
            self.assertEqual(manifest["installer"]["installed_initramfs"]["size"], len(b"fake-installed-initramfs"))
            self.assertEqual(manifest["installer"]["uefi_fallback_bootloader"]["size"], len(b"fake-efi"))
            self.assertEqual((tree / "install/kiki-stage1.img").read_bytes(), b"fake-install-image")
            self.assertEqual((tree / "boot/initramfs-kiki-installed.img").read_bytes(), b"fake-installed-initramfs")
            self.assertEqual((tree / "kiki/bootloader/EFI/BOOT/BOOTX64.EFI").read_bytes(), b"fake-efi")
            grub = (tree / "boot/grub/grub.cfg").read_text(encoding="utf-8")
            self.assertIn("loadfont /boot/grub/fonts/unicode.pf2", grub)
            self.assertIn("terminal_output gfxterm console serial", grub)
            self.assertIn("terminal_output console serial", grub)
            self.assertIn("set default=0", grub)
            self.assertIn("kiki.boot=installer", grub)
            self.assertIn('menuentry "KIKI OS graphical installer (default)"', grub)
            self.assertIn("kiki.ui=gui", grub)
            self.assertIn('menuentry "KIKI OS full-screen TUI installer (x86_64)"', grub)
            self.assertIn("kiki.ui=tui", grub)
            self.assertIn('menuentry "KIKI OS CLI installer (x86_64, safe fallback)"', grub)
            self.assertIn("kiki.ui=cli", grub)
            self.assertLess(grub.index("kiki.ui=gui"), grub.index("kiki.ui=tui"))
            self.assertLess(grub.index("kiki.ui=tui"), grub.index("kiki.ui=cli"))
            self.assertEqual(manifest["installer"]["interface"], "gui-tui-cli")
            self.assertEqual(manifest["installer"]["interface_order"], ["gtk4", "fullscreen-tui", "cli"])
            self.assertIn("quiet loglevel=3", grub)
            self.assertIn("graphical installer (default)", grub)
            self.assertIn("UEFI framebuffer", grub)
            self.assertIn("Hyper-V framebuffer", grub)
            self.assertIn("BIOS VGA text", grub)
            self.assertIn("serial + VGA", grub)
            self.assertIn("debug Hyper-V EFI", grub)
            self.assertIn("set gfxpayload=keep", grub)
            self.assertIn("video=hyperv_fb:1024x768", grub)

    def test_prepare_boot_iso_tree_can_describe_installed_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rootfs = root / "rootfs"
            repo = root / "repo"
            tree = root / "iso-tree"
            kernel = root / "vmlinuz-kiki"
            initramfs = root / "initramfs-kiki.img"

            rootfs.mkdir()
            repo.mkdir()
            kernel.write_bytes(b"fake-kernel")
            initramfs.write_bytes(b"fake-initramfs")

            manifest = ki2bootiso.prepare_boot_iso_tree(
                rootfs,
                repo,
                tree,
                kernel=kernel,
                initramfs=initramfs,
                arch="x86_64",
                profile="bootstrap-stage1",
                label="KIKI_TEST_INSTALLED",
                installed=True,
            )

            self.assertEqual(manifest["boot_mode"], "installed-systemd-handoff")
            grub = (tree / "boot/grub/grub.cfg").read_text(encoding="utf-8")
            self.assertIn("kiki.boot=installed", grub)
            self.assertIn("quiet loglevel=3", grub)

    def test_generated_init_contains_stage1_prompt(self):
        self.assertIn("KIKI stage-1 prompt ready", ki2bootiso.INIT_C)
        self.assertIn('say("kiki# ");', ki2bootiso.INIT_C)
        self.assertIn("basic services:", ki2bootiso.INIT_C)
        self.assertIn("BOS/ki2 package media", ki2bootiso.INIT_C)
        self.assertIn("Network tools", ki2bootiso.INIT_C)
        self.assertIn("Disk tools", ki2bootiso.INIT_C)
        self.assertIn("Package selection", ki2bootiso.INIT_C)
        self.assertIn("Select minimal-systemd default package set", ki2bootiso.INIT_C)
        self.assertIn("Select server-core general OS package set", ki2bootiso.INIT_C)
        self.assertIn("Select kiki-kube-bootstrap package set", ki2bootiso.INIT_C)
        self.assertIn("Select kiki-kube-control package set", ki2bootiso.INIT_C)
        self.assertIn("Select kiki-kube-compute package set", ki2bootiso.INIT_C)
        self.assertIn("kiki-kube-bootstrap package set (first control-plane bootstrap)", ki2bootiso.INIT_C)
        self.assertIn("kiki-kube-control package set (additional control-plane node)", ki2bootiso.INIT_C)
        self.assertIn("kiki-kube-compute package set (compute node)", ki2bootiso.INIT_C)
        self.assertIn("Kubernetes profiles keep swap off", ki2bootiso.INIT_C)
        self.assertIn("ensure_selected_profile_packages", ki2bootiso.INIT_C)
        self.assertIn("Required Kubernetes package missing from repository index", ki2bootiso.INIT_C)
        self.assertIn("Kubernetes profile cannot be installed until all required packages are present", ki2bootiso.INIT_C)
        self.assertIn('"kubelet"', ki2bootiso.INIT_C)
        self.assertIn('"kubeadm"', ki2bootiso.INIT_C)
        self.assertIn('"kubectl"', ki2bootiso.INIT_C)
        self.assertIn('"kiki-kubeadm"', ki2bootiso.INIT_C)
        self.assertIn('"cri-o"', ki2bootiso.INIT_C)
        self.assertIn('"containerd"', ki2bootiso.INIT_C)
        self.assertIn('"kube-node-config-containerd"', ki2bootiso.INIT_C)
        self.assertIn('"kiki-netconfig"', ki2bootiso.INIT_C)
        self.assertIn('"server-core"', ki2bootiso.INIT_C)
        self.assertIn("Use containerd", ki2bootiso.INIT_C)
        self.assertIn("selected_container_runtime", ki2bootiso.INIT_C)
        self.assertIn("unique package names", ki2bootiso.INIT_C)
        self.assertIn("KIKI OS installer TUI", ki2bootiso.INIT_C)
        self.assertIn("KIKI OS Installer", ki2bootiso.INIT_C)
        self.assertIn("1) Language / keyboard / timezone", ki2bootiso.INIT_C)
        self.assertIn("5) Package source / trust", ki2bootiso.INIT_C)
        self.assertIn("8) AI management console", ki2bootiso.INIT_C)
        self.assertIn("10) Start install", ki2bootiso.INIT_C)
        self.assertIn("s) Shell", ki2bootiso.INIT_C)
        self.assertIn("q) Power off", ki2bootiso.INIT_C)
        self.assertIn("Review install plan", ki2bootiso.INIT_C)
        self.assertIn("Declarative install plan preview", ki2bootiso.INIT_C)
        self.assertIn("kiki-install-plan-v1", ki2bootiso.INIT_C)
        self.assertIn("/run/kiki/install-plan.yaml", ki2bootiso.INIT_C)
        self.assertIn("/var/lib/ki2/install-plan.yaml", ki2bootiso.INIT_C)
        self.assertIn('"channel", "stage2-v2"', ki2bootiso.INIT_C)
        self.assertIn("selected_kubernetes_role", ki2bootiso.INIT_C)
        self.assertIn("selected_kubeadm_template", ki2bootiso.INIT_C)
        self.assertIn("kubeadm.k8s.io/v1beta4", ki2bootiso.INIT_C)
        self.assertIn("kubeadm init --config /etc/kubernetes/kiki/kubeadm.local.yaml", ki2bootiso.INIT_C)
        self.assertIn("kubeadm join --config /etc/kubernetes/kiki/kubeadm.local.yaml", ki2bootiso.INIT_C)
        self.assertIn("/etc/kubernetes/kiki/kubeadm-join-compute.yaml", ki2bootiso.INIT_C)
        self.assertIn("unix:///run/containerd/containerd.sock", ki2bootiso.INIT_C)
        self.assertIn("unix:///var/run/crio/crio.sock", ki2bootiso.INIT_C)
        self.assertIn("runtime-input-not-written-to-plan", ki2bootiso.INIT_C)
        self.assertIn("dependency_resolution", ki2bootiso.INIT_C)
        self.assertIn('"  localization:\\n"', ki2bootiso.INIT_C)
        self.assertIn('"require_approval"', ki2bootiso.INIT_C)
        self.assertIn("kiki-ai-console@tty1.service", ki2bootiso.INIT_C)
        self.assertIn("getty@tty2.service", ki2bootiso.INIT_C)
        self.assertIn("ensure_selected_ai_packages", ki2bootiso.INIT_C)
        self.assertIn("Network setup", ki2bootiso.INIT_C)
        self.assertIn("systemd-networkd DHCP", ki2bootiso.INIT_C)
        self.assertIn("interface_match", ki2bootiso.INIT_C)
        self.assertIn("write_target_network_config", ki2bootiso.INIT_C)
        self.assertIn("RequiredForOnline=routable", ki2bootiso.INIT_C)
        self.assertIn("DHCP=ipv4", ki2bootiso.INIT_C)
        self.assertIn("show_saved_install_plan", ki2bootiso.INIT_C)
        self.assertIn("find_default_install_disk", ki2bootiso.INIT_C)
        self.assertIn("kiki.autoinstall", ki2bootiso.INIT_C)
        self.assertIn("kiki.profile", ki2bootiso.INIT_C)
        self.assertIn("kiki.runtime", ki2bootiso.INIT_C)
        self.assertIn("kiki.target", ki2bootiso.INIT_C)
        self.assertIn("kiki.hostname", ki2bootiso.INIT_C)
        self.assertIn("kiki.locale", ki2bootiso.INIT_C)
        self.assertIn("kiki.timezone", ki2bootiso.INIT_C)
        self.assertIn("kiki.ai-endpoint", ki2bootiso.INIT_C)
        self.assertIn("maybe_run_cmdline_autoinstall", ki2bootiso.INIT_C)
        self.assertIn("try_graphical_installer", ki2bootiso.INIT_C)
        self.assertIn("GTK installer is not present in this initramfs; falling back to the TUI", ki2bootiso.INIT_C)
        self.assertIn('"/usr/bin/cage"', ki2bootiso.INIT_C)
        self.assertIn('"XDG_RUNTIME_DIR=/run/kiki-wayland"', ki2bootiso.INIT_C)
        self.assertIn('"GDK_BACKEND=wayland"', ki2bootiso.INIT_C)
        self.assertIn('"LIBSEAT_BACKEND=builtin"', ki2bootiso.INIT_C)
        self.assertIn('"/usr/lib/systemd/systemd-udevd"', ki2bootiso.INIT_C)
        self.assertIn('"/usr/bin/udevadm"', ki2bootiso.INIT_C)
        self.assertIn('"/run/kiki/gui-installer.log"', ki2bootiso.INIT_C)
        self.assertIn('"--ascii"', ki2bootiso.INIT_C)
        self.assertIn('"LANG=C.UTF-8"', ki2bootiso.INIT_C)
        self.assertIn("run_guided_package_installer(1, 1)", ki2bootiso.INIT_C)
        self.assertIn("select_named_package_profile", ki2bootiso.INIT_C)
        self.assertIn("Autoinstall target disk", ki2bootiso.INIT_C)
        self.assertIn("Press Enter or type yes to continue", ki2bootiso.INIT_C)
        self.assertIn("Hostname [localhost.localdomain]", ki2bootiso.INIT_C)
        self.assertIn("User setup", ki2bootiso.INIT_C)
        self.assertIn("Admin username [kiki]", ki2bootiso.INIT_C)
        self.assertIn("Disable direct root login", ki2bootiso.INIT_C)
        self.assertIn("KIKI_LAB_PASSWORD_HASH", ki2bootiso.INIT_C)
        self.assertIn("Writing lab default admin account directly", ki2bootiso.INIT_C)
        self.assertIn("write_target_lab_admin_account", ki2bootiso.INIT_C)
        self.assertIn('"/bin/sh"', ki2bootiso.INIT_C)
        self.assertIn("/usr/sbin/useradd", ki2bootiso.INIT_C)
        self.assertIn("/usr/sbin/chpasswd", ki2bootiso.INIT_C)
        self.assertIn("/etc/sudoers.d/kiki-admin", ki2bootiso.INIT_C)
        self.assertIn('"sudo"', ki2bootiso.INIT_C)
        self.assertIn("Automatic whole-disk layout: ESP + swap + root", ki2bootiso.INIT_C)
        self.assertIn("Manual partitions: use shell/fdisk/cfdisk first", ki2bootiso.INIT_C)
        self.assertIn("Disk actions", ki2bootiso.INIT_C)
        self.assertIn("Open cfdisk on a disk", ki2bootiso.INIT_C)
        self.assertIn("Open fdisk on a disk", ki2bootiso.INIT_C)
        self.assertIn("prompt_whole_disk", ki2bootiso.INIT_C)
        self.assertIn("run_partition_editor", ki2bootiso.INIT_C)
        self.assertIn('"ncurses"', ki2bootiso.INIT_C)
        self.assertIn('"cfdisk"', ki2bootiso.INIT_C)
        self.assertIn("preferred_install_disk", ki2bootiso.INIT_C)
        self.assertIn("Detected partition candidates from", ki2bootiso.INIT_C)
        self.assertIn("prompt_partition_path", ki2bootiso.INIT_C)
        self.assertIn("type none", ki2bootiso.INIT_C)
        self.assertIn("BLKRRPART", ki2bootiso.INIT_C)
        self.assertIn("fdisk /dev/<disk>", ki2bootiso.INIT_C)
        self.assertIn("Running partition command", ki2bootiso.INIT_C)
        self.assertIn("not a partition such as /dev/sda1", ki2bootiso.INIT_C)
        self.assertIn("Formatting swap partition", ki2bootiso.INIT_C)
        self.assertIn("/usr/sbin/mke2fs", ki2bootiso.INIT_C)
        self.assertIn("LABEL=KIKI_ROOT / ext4 defaults", ki2bootiso.INIT_C)
        self.assertIn("LABEL=KIKI_EFI /boot/efi", ki2bootiso.INIT_C)
        self.assertIn("LABEL=KIKI_SWAP none swap defaults,nofail,x-systemd.device-timeout=10s", ki2bootiso.INIT_C)
        self.assertIn("noauto,nofail,x-systemd.device-timeout=3s", ki2bootiso.INIT_C)
        self.assertIn("kiki-installer-tui", ki2bootiso.INIT_C)
        self.assertIn("Formatting root partition as ext4", ki2bootiso.INIT_C)
        self.assertIn("Switching to installed systemd PID 1", ki2bootiso.INIT_C)
        self.assertIn("/usr/lib/systemd", ki2bootiso.INIT_C)
        self.assertIn("Refreshing target shared-library cache", ki2bootiso.INIT_C)
        self.assertIn("-r", ki2bootiso.INIT_C)
        self.assertIn("ensure_target_baseline_layout", ki2bootiso.INIT_C)
        self.assertIn("/mnt/target/usr/sbin/sulogin", ki2bootiso.INIT_C)
        self.assertIn("/mnt/target/lib64/ld-linux-x86-64.so.2", ki2bootiso.INIT_C)
        self.assertIn("/mnt/target/lib64/libcrypt.so.2", ki2bootiso.INIT_C)
        self.assertIn("/mnt/target/etc/systemd/system/kiki-agent.service", ki2bootiso.INIT_C)
        self.assertIn("/mnt/target/var/tmp", ki2bootiso.INIT_C)
        self.assertIn("systemd-logind.service", ki2bootiso.INIT_C)
        self.assertIn("getty.target.wants", ki2bootiso.INIT_C)
        self.assertIn("systemd-networkd.socket", ki2bootiso.INIT_C)
        self.assertIn("kiki-boot-prepare.service", ki2bootiso.INIT_C)
        self.assertIn("KIKI OS installed (systemd handoff)", ki2bootiso.INIT_C)
        self.assertIn("/boot/grub/fonts/unicode.pf2", ki2bootiso.INIT_C)
        source = Path(ki2bootiso.__file__).read_text(encoding="utf-8")
        self.assertIn("lib/libncursesw.so", source)
        self.assertIn("lib/libtinfo.so", source)
        self.assertIn("lib/libsmartcols.so.1", source)
        self.assertIn("static IPv4", source)
        self.assertIn("Address=", source)
        self.assertIn("Gateway=", source)

    def test_generated_init_c_has_valid_syntax_when_gcc_is_available(self):
        gcc = shutil.which("gcc")
        if not gcc:
            self.skipTest("gcc is not available")
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "init.c"
            source.write_text(ki2bootiso.INIT_C, encoding="utf-8")

            subprocess.run([gcc, "-Wall", "-Wextra", "-fsyntax-only", str(source)], check=True)

    def test_add_installer_runtime_includes_cfdisk_libraries(self):
        if os.name == "nt":
            self.skipTest("Windows symlink permissions can block busybox applet links")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packages = root / "packages"
            target = root / "initramfs-root"
            packages.mkdir()

            self.write_fake_package(
                packages / "glibc-2.40-1.x86_64.ki2",
                {
                    "etc/ld.so.cache": b"cache",
                    "lib64/ld-linux-x86-64.so.2": b"loader",
                },
            )
            self.write_fake_package(packages / "busybox-1.36-1.x86_64.ki2", {"bin/busybox": b"busybox"})
            self.write_fake_package(
                packages / "e2fsprogs-1.47-1.x86_64.ki2",
                {
                    "usr/sbin/mke2fs": b"mke2fs",
                    "usr/sbin/mkfs.ext4": b"mkfs.ext4",
                },
            )
            self.write_fake_package(
                packages / "util-linux-2.40-1.x86_64.ki2",
                {
                    "sbin/cfdisk": b"cfdisk",
                    "sbin/fdisk": b"fdisk",
                    "sbin/sfdisk": b"sfdisk",
                    "lib/libblkid.so.1": b"blkid",
                    "lib/libblkid.so.1.1.0": b"blkid-real",
                    "lib/libfdisk.so.1": b"fdisk-lib",
                    "lib/libfdisk.so.1.1.0": b"fdisk-real",
                    "lib/libmount.so.1": b"mount",
                    "lib/libmount.so.1.1.0": b"mount-real",
                    "lib/libsmartcols.so.1": b"smartcols",
                    "lib/libsmartcols.so.1.1.0": b"smartcols-real",
                    "lib/libuuid.so.1": b"uuid",
                    "lib/libuuid.so.1.3.0": b"uuid-real",
                },
            )
            self.write_fake_package(
                packages / "ncurses-6.5-1.x86_64.ki2",
                {
                    "lib/libncursesw.so.6": b"ncursesw",
                    "lib/libtinfo.so.6": b"tinfo",
                    "usr/share/terminfo/x/xterm": b"terminfo",
                },
            )
            self.write_fake_package(
                packages / "kiki-installer-tui-0.1.0-5.x86_64.ki2",
                {"usr/bin/kiki-installer-tui": b"static-tui"},
            )
            self.write_fake_package(
                packages / "kiki-installer-gtk-0.1.0-1.x86_64.ki2",
                {
                    "usr/bin/cage": b"cage",
                    "usr/bin/kiki-installer-gtk": b"gtk",
                    "usr/lib64/libwlroots.so.11": b"wlroots",
                    "usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc": b"font",
                },
            )

            runtime = ki2bootiso.add_installer_runtime(target, packages)

            self.assertEqual(runtime["packages"]["util-linux"], "util-linux-2.40-1.x86_64.ki2")
            self.assertEqual(runtime["packages"]["kiki-installer-tui"], "kiki-installer-tui-0.1.0-5.x86_64.ki2")
            self.assertEqual((target / "usr/bin/kiki-installer-tui").read_bytes(), b"static-tui")
            self.assertIn("/usr/bin/kiki-installer-tui", runtime["tools"])
            self.assertTrue(runtime["graphical"]["enabled"])
            self.assertEqual((target / "usr/bin/cage").read_bytes(), b"cage")
            self.assertEqual((target / "usr/bin/kiki-installer-gtk").read_bytes(), b"gtk")
            self.assertTrue((target / "usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc").exists())
            self.assertTrue((target / "sbin/cfdisk").exists())
            self.assertTrue((target / "lib/libsmartcols.so.1").exists())
            self.assertTrue((target / "lib/libsmartcols.so.1.1.0").exists())
            self.assertTrue((target / "lib/libtinfo.so.6").exists())
            self.assertTrue((target / "lib/libncursesw.so.6").exists())
            self.assertTrue((target / "lib64/libsmartcols.so.1").is_symlink())
            self.assertTrue((target / "lib64/libfdisk.so.1").is_symlink())
            self.assertEqual(os.readlink(target / "lib64/libsmartcols.so.1"), "../lib/libsmartcols.so.1")

    def test_extract_package_members_preserves_hardlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "e2fsprogs-test.ki2"
            target = root / "initramfs-root"
            payload = b"fake-mke2fs"

            with tarfile.open(package, "w:gz") as tar:
                info = tarfile.TarInfo("rootfs/usr/sbin/mke2fs")
                info.size = len(payload)
                info.mode = 0o755
                tar.addfile(info, io.BytesIO(payload))

                link = tarfile.TarInfo("rootfs/usr/sbin/mkfs.ext4")
                link.type = tarfile.LNKTYPE
                link.linkname = "rootfs/usr/sbin/mke2fs"
                link.mode = 0o755
                tar.addfile(link)

            extracted = ki2bootiso.extract_package_members(
                package,
                target,
                {"usr/sbin/mke2fs", "usr/sbin/mkfs.ext4"},
            )

            self.assertEqual(extracted, 2)
            self.assertEqual((target / "usr/sbin/mke2fs").read_bytes(), payload)
            self.assertEqual((target / "usr/sbin/mkfs.ext4").read_bytes(), payload)

    def test_chmod_dynamic_loaders_marks_interpreter_executable(self):
        if os.name == "nt":
            self.skipTest("Windows chmod does not reliably expose executable mode bits")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            loader = root / "lib64/ld-linux-x86-64.so.2"
            loader.parent.mkdir(parents=True)
            loader.write_bytes(b"fake-loader")
            loader.chmod(0o644)

            ki2bootiso.chmod_dynamic_loaders(root)

            self.assertEqual(loader.stat().st_mode & 0o777, 0o755)

    def test_default_hyperv_vhdx_output_uses_dist_iso(self):
        root = Path("/repo")
        output = ki2bootiso.default_hyperv_vhdx_output(root, "bootstrap-stage1", "x86_64")
        self.assertEqual(output, root / "dist/iso/kiki-stage1-v1-installed-hyperv-x86_64.vhdx")

    def test_write_newc_gzip_contains_init_and_trailer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "initramfs-root"
            output = root / "initramfs.img"
            source.mkdir()
            init = source / "init"
            init.write_text("#!/bin/sh\n", encoding="utf-8")
            init.chmod(0o755)

            ki2bootiso.write_newc_gzip(source, output)

            payload = gzip.decompress(output.read_bytes())
            self.assertIn(b"070701", payload)
            self.assertIn(b"init\x00", payload)
            self.assertIn(b"TRAILER!!!", payload)


if __name__ == "__main__":
    unittest.main()
