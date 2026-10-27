"""Static safety checks for the optional KIKI LightDM package."""

import json
import os
from pathlib import Path
import subprocess
import tarfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "distro/sources/kiki-lightdm"
PACKAGE = ROOT / "dist/ki2/lightdm-packages/x86_64/kiki-lightdm-1.30.0-1.x86_64.ki2"


class LightDMRuntimeTests(unittest.TestCase):
    def test_opt_in_without_guest_or_autologin(self):
        config = (SOURCES / "etc/lightdm/lightdm.conf.d/90-kiki.conf").read_text()
        self.assertIn("xserver-command=/usr/bin/Xorg -nolisten tcp", config)
        self.assertIn("greeter-session=lightdm-gtk-greeter", config)
        self.assertIn("session-wrapper=/usr/bin/kiki-lightdm-session", config)
        self.assertIn("allow-guest=false", config)
        self.assertNotIn("autologin-user=", config)
        helper = (SOURCES / "usr/bin/kiki-lightdm-enable").read_text()
        self.assertIn("systemctl enable lightdm.service", helper)
        self.assertNotIn("systemctl set-default graphical.target\n", helper)
        self.assertIn("Another display manager is already enabled", helper)
        self.assertIn("kiki-lightdm.conf", helper)

    def test_pam_and_shell_scripts(self):
        pam = (SOURCES / "etc/pam.d/lightdm").read_text()
        self.assertIn("pam_unix.so", pam)
        self.assertNotIn("pam_permit.so", pam)
        for name in ("kiki-lightdm-enable", "kiki-lightdm-session"):
            subprocess.run(["sh", "-n", str(SOURCES / "usr/bin" / name)], check=True)

    @unittest.skipUnless(os.getenv("KIKI_TEST_LIGHTDM_PACKAGE") == "1", "set KIKI_TEST_LIGHTDM_PACKAGE=1")
    def test_built_package(self):
        self.assertTrue(PACKAGE.is_file())
        with tarfile.open(PACKAGE) as archive:
            names = set(archive.getnames())
            for name in (
                "rootfs/usr/sbin/lightdm", "rootfs/usr/sbin/lightdm-gtk-greeter",
                "rootfs/usr/share/xgreeters/lightdm-gtk-greeter.desktop",
                "rootfs/usr/lib/systemd/system/lightdm.service",
                "rootfs/usr/lib/sysusers.d/kiki-lightdm.conf",
                "rootfs/usr/lib/tmpfiles.d/kiki-lightdm.conf",
                "rootfs/usr/share/xsessions/kiki-xterm.desktop",
                "rootfs/usr/bin/kiki-lightdm-enable", "rootfs/usr/bin/kiki-lightdm-session",
            ):
                self.assertIn(name, names)
            self.assertFalse(any(name.endswith("/libpam.so.0") for name in names))
            for name in ("rootfs/usr/lib/systemd/system/lightdm.service", "rootfs/etc/pam.d/lightdm"):
                self.assertEqual(archive.getmember(name).mode & 0o777, 0o644)
            manifest = json.load(archive.extractfile("rootfs/usr/share/kiki-lightdm/runtime-manifest.json"))
            self.assertEqual(manifest["schema"], "kiki-lightdm-bootstrap-v1")
            self.assertTrue(any("lightdm-1.30.0" in item for item in manifest["host_packages"]))


if __name__ == "__main__":
    unittest.main()
