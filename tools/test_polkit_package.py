"""Opt-in checks against the actual Polkit package, not a live authorization test."""
import json
import gettext
import os
from pathlib import Path
import tarfile
import xml.etree.ElementTree as ET
import unittest
import ki2build

@unittest.skipUnless(os.environ.get("KIKI_TEST_POLKIT_PACKAGE") == "1",
                     "set KIKI_TEST_POLKIT_PACKAGE=1")
class PolkitPackageTests(unittest.TestCase):
    def test_layout_modes_policy_and_introspection(self):
        repo = Path(__file__).resolve().parents[1]
        recipe = ki2build.load_recipes(repo / "distro/recipes")["polkit"]
        package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipe, "x86_64")
        with tarfile.open(package, "r:gz") as archive:
            members = {m.name: m for m in archive.getmembers()}
            manifest = json.load(archive.extractfile("manifest.json"))
            files = {m["path"]: m for m in manifest["files"]}
            expected = {
                "usr/bin/pkexec": 0o4755,
                "usr/lib/polkit-1/polkitd": 0o755,
                "usr/lib/polkit-1/polkit-agent-helper-1": 0o4755,
                "etc/polkit-1/rules.d": 0o750,
                "etc/pam.d/polkit-1": 0o644,
                "usr/lib/systemd/system/polkit.service": 0o644,
                "usr/lib/systemd/system/polkit-agent-helper.socket": 0o644,
                "usr/lib/systemd/system/polkit-agent-helper@.service": 0o644,
                "usr/lib/sysusers.d/polkit.conf": 0o644,
                "usr/lib/tmpfiles.d/polkit-tmpfiles.conf": 0o644,
                "usr/lib/girepository-1.0/Polkit-1.0.typelib": 0o644,
                "usr/lib/girepository-1.0/PolkitAgent-1.0.typelib": 0o644,
                "usr/share/licenses/polkit/COPYING": 0o644,
                "usr/share/locale/ko/LC_MESSAGES/polkit-1.mo": 0o644,
            }
            for path, mode in expected.items():
                with self.subTest(path=path):
                    member = members["rootfs/" + path]
                    self.assertEqual(member.mode, mode)
                    self.assertEqual((member.uid, member.gid), (0, 0))
                    self.assertEqual(files["/" + path]["mode"], oct(mode))
            self.assertFalse(any(n.startswith("rootfs/tmp/") for n in members))
            # Catalog presence is required; actual UI coverage remains separate.
            translation = gettext.GNUTranslations(archive.extractfile(
                "rootfs/usr/share/locale/ko/LC_MESSAGES/polkit-1.mo"))
            self.assertEqual(translation.gettext("Show version"), "버전 표시")
            self.assertEqual(translation.gettext(
                "Authentication is needed to run `$(cmdline_short)' as user $(user.display)"),
                "$(user.display) 사용자 권한으로 '$(cmdline_short)' 명령을 실행하려면 인증이 필요합니다")
            policy_xml = ET.fromstring(archive.extractfile(
                "rootfs/usr/share/polkit-1/actions/org.freedesktop.policykit.policy").read())
            korean_messages = [m.text for m in policy_xml.iter("message")
                               if m.get("{http://www.w3.org/XML/1998/namespace}lang") == "ko"]
            self.assertIn("다른 사용자 권한으로 프로그램을 실행하려면 인증이 필요합니다", korean_messages)
            policy = archive.extractfile("rootfs/etc/pam.d/polkit-1").read()
            self.assertEqual(policy, (repo / "distro/sources/polkit/etc/pam.d/polkit-1").read_bytes())
            for line in policy.decode().splitlines():
                if line.strip() and not line.startswith("#"):
                    self.assertNotIn("include", line.split())
                    self.assertNotIn("nullok", line.split())
            for path in expected:
                if path.endswith((".service", ".socket", ".conf")):
                    self.assertNotIn(b"/tmp/kiki-", archive.extractfile("rootfs/" + path).read())

if __name__ == "__main__":
    unittest.main()
