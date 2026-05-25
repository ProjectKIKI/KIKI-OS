import gzip
import io
import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path

import ki2bootiso


class Ki2BootIsoTests(unittest.TestCase):
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
            self.assertIn("quiet loglevel=3", grub)
            self.assertIn("auto console", grub)
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

            self.assertEqual(manifest["boot_mode"], "installed-stage1")
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
        self.assertIn("KIKI OS installer TUI", ki2bootiso.INIT_C)
        self.assertIn("Quick VM install (auto disk, ESP + swap + root)", ki2bootiso.INIT_C)
        self.assertIn("Guided install (partition mode and package review)", ki2bootiso.INIT_C)
        self.assertIn("Review saved install plan", ki2bootiso.INIT_C)
        self.assertIn("Declarative install plan preview", ki2bootiso.INIT_C)
        self.assertIn("kiki-install-plan-v1", ki2bootiso.INIT_C)
        self.assertIn("/run/kiki/install-plan.yaml", ki2bootiso.INIT_C)
        self.assertIn("/var/lib/ki2/install-plan.yaml", ki2bootiso.INIT_C)
        self.assertIn("runtime-input-not-written-to-plan", ki2bootiso.INIT_C)
        self.assertIn("dependency_resolution", ki2bootiso.INIT_C)
        self.assertIn("Network setup", ki2bootiso.INIT_C)
        self.assertIn("systemd-networkd DHCP", ki2bootiso.INIT_C)
        self.assertIn("interface_match", ki2bootiso.INIT_C)
        self.assertIn("write_target_network_config", ki2bootiso.INIT_C)
        self.assertIn("RequiredForOnline=routable", ki2bootiso.INIT_C)
        self.assertIn("DHCP=ipv4", ki2bootiso.INIT_C)
        self.assertIn("show_saved_install_plan", ki2bootiso.INIT_C)
        self.assertIn("find_default_install_disk", ki2bootiso.INIT_C)
        self.assertIn("Press Enter or type yes to continue", ki2bootiso.INIT_C)
        self.assertIn("Hostname [localhost.localdomain]", ki2bootiso.INIT_C)
        self.assertIn("User setup", ki2bootiso.INIT_C)
        self.assertIn("Admin username [admin]", ki2bootiso.INIT_C)
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
        self.assertIn("fdisk /dev/<disk>", ki2bootiso.INIT_C)
        self.assertIn("Running partition command", ki2bootiso.INIT_C)
        self.assertIn("not a partition such as /dev/sda1", ki2bootiso.INIT_C)
        self.assertIn("Formatting swap partition", ki2bootiso.INIT_C)
        self.assertIn("/usr/sbin/mke2fs", ki2bootiso.INIT_C)
        self.assertIn("none swap defaults", ki2bootiso.INIT_C)
        self.assertIn("noauto,nofail,x-systemd.device-timeout=3s", ki2bootiso.INIT_C)
        self.assertIn("Formatting root partition as ext4", ki2bootiso.INIT_C)
        self.assertIn("Switching to installed systemd", ki2bootiso.INIT_C)
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
        self.assertIn("KIKI OS installed (auto console)", ki2bootiso.INIT_C)
        self.assertIn("/boot/grub/fonts/unicode.pf2", ki2bootiso.INIT_C)

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
        self.assertEqual(output, root / "dist/iso/kiki-bootstrap-stage1-installed-hyperv-x86_64.vhdx")

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
