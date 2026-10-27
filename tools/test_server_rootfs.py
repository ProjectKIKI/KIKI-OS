"""Read-only CLI checks against an assembled server rootfs; not a boot test."""
import os
from pathlib import Path
import subprocess
import tarfile
import unittest
import ki2build

@unittest.skipUnless(os.environ.get("KIKI_SERVER_TEST_ROOTFS"), "set KIKI_SERVER_TEST_ROOTFS")
class ServerRootfsTests(unittest.TestCase):
    def test_kernel_and_dbus_boot_contract(self):
        root = Path(os.environ['KIKI_SERVER_TEST_ROOTFS']).resolve(strict=True)
        repo = Path(__file__).resolve().parents[1]
        recipe = ki2build.load_recipes(repo / 'distro/recipes')['linux']
        package = repo / 'dist/ki2/packages/x86_64' / ki2build.package_filename(recipe, 'x86_64')
        with tarfile.open(package, 'r:gz') as archive:
            self.assertEqual((root / 'boot/vmlinuz-kiki').read_bytes(),
                             archive.extractfile('rootfs/boot/vmlinuz-kiki').read())
        unit = (root / 'usr/lib/systemd/system/dbus.service').read_text()
        self.assertIn('Requires=dbus.socket', unit)
        self.assertIn('--address=systemd:', unit)
        self.assertIn('--systemd-activation', unit)
        self.assertTrue((root / 'usr/lib/systemd/system/dbus.socket').is_file())
        libraries = [p for p in root.glob('usr/lib*/libdbus-1.so.*') if not p.is_symlink() and p.is_file()]
        self.assertTrue(libraries, 'D-Bus runtime library missing')
        dynamic = subprocess.check_output(['readelf', '-d', str(libraries[0])], text=True)
        self.assertIn('libsystemd.so.0', dynamic, 'D-Bus was built without systemd socket support')

    def test_tui_matches_current_package(self):
        root = Path(os.environ['KIKI_SERVER_TEST_ROOTFS']).resolve(strict=True)
        repo = Path(__file__).resolve().parents[1]
        recipe = ki2build.load_recipes(repo / 'distro/recipes')['kiki-installer-tui']
        package = repo / 'dist/ki2/packages/x86_64' / ki2build.package_filename(recipe,'x86_64')
        with tarfile.open(package,'r:gz') as archive:
            expected = archive.extractfile('rootfs/usr/bin/kiki-installer-tui').read()
        self.assertTrue((root/'usr/bin/kiki-installer-tui').read_bytes() == expected,
                        'assembled TUI differs from the current package')

    def test_packaged_cli_and_generated_indexes(self):
        root = Path(os.environ["KIKI_SERVER_TEST_ROOTFS"]).resolve(strict=True)
        repo = Path(__file__).resolve().parents[1]
        self.assertEqual((root / "usr/bin/ki2ctl").read_bytes(),
                         (repo / "distro/sources/ki2ctl/usr/bin/ki2ctl").read_bytes())
        self.assertTrue((root / "usr/bin/install-info").is_file())
        self.assertIn("* gmp:", (root / "usr/share/info/dir").read_text())
        self.assertTrue((root / "usr/share/glib-2.0/schemas/gschemas.compiled").is_file())
        env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "KI2_SYSROOT": str(root),
               "PYTHONHOME": str(root / "usr"),
               "KI2_SYSROOT_LIBRARY_PATH": ":".join(str(root / p) for p in
                                                   ("usr/lib", "usr/lib64", "lib", "lib64"))}
        command = ["/bin/sh", str(repo / "distro/scripts/ki2-target-run"),
                   str(root / "usr/bin/python3.12"), "-B", str(root / "usr/bin/ki2ctl"),
                   "--root", str(root), "list"]
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        recipe = ki2build.load_recipes(repo / 'distro/recipes')['ki2ctl']
        self.assertIn(f"ki2ctl\t{recipe.version}-{recipe.release}", result.stdout)
        self.assertTrue((root / 'usr/share/zoneinfo/Asia/Seoul').is_file())
        self.assertTrue((root / 'usr/share/zoneinfo/Etc/UTC').is_file())
        self.assertIn("install-info\t7.2-2", result.stdout)
        print("Server rootfs: target Python/ki2ctl installed list, Info and GSettings indexes passed")

if __name__ == "__main__":
    unittest.main()
