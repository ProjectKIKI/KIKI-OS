"""Opt-in packaged Fontconfig CLI/cache test in a temporary target chroot."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import ki2build

@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_FONTCONFIG") == "1",
                     "set KIKI_TEST_FONTCONFIG=1 on Linux as root")
class FontconfigRuntimeTests(unittest.TestCase):
    def test_korean_font_cache_lifecycle(self):
        self.assertEqual(os.geteuid(), 0)
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        with tempfile.TemporaryDirectory(prefix="kiki-fontconfig-runtime-") as tmp:
            root = Path(tmp) / "root"
            for name in ki2build.dependency_closure(recipes, ["fontconfig"], "x86_64", include_build_deps=False):
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            for sub in ("usr/share/fonts", "var/cache/fontconfig", "tmp", "root"):
                (root / sub).mkdir(parents=True, exist_ok=True)
            def run(command):
                result = subprocess.run(command, env={"PATH":"/usr/sbin:/usr/bin:/bin", "LC_ALL":"C", "HOME":"/root"},
                                        capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout
            self.assertTrue((root / "etc/fonts/fonts.conf").is_file())
            self.assertTrue((root / "usr/share/licenses/fontconfig/COPYING").is_file())
            for config in (root / "etc/fonts").rglob("*"):
                if config.is_file() and not config.is_symlink():
                    self.assertNotIn(b"/tmp/kiki-", config.read_bytes())
            self.assertNotRegex(run(["readelf", "-d", str(root / "usr/lib/libfontconfig.so.1")]),
                                r"\((?:RPATH|RUNPATH)\)")
            loaders = [p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            base = ["chroot", str(root), "/" + str(loaders[0].relative_to(root)),
                    "--inhibit-cache", "--library-path", "/usr/lib:/usr/lib64:/lib:/lib64"]
            def fc(tool, *args):
                return run(base + ["/usr/bin/" + tool, *args])
            self.assertEqual(fc("fc-list", "--format=%{file}\n").strip(), "")
            font = root / "usr/share/fonts/NotoSansCJK-Regular.ttc"
            shutil.copyfile(repo / "build/ki2/host-graphics/rootfs/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc", font)
            fc("fc-cache", "--force", "/usr/share/fonts")
            self.assertTrue(list((root / "var/cache/fontconfig").glob("*cache*")))
            match = fc("fc-match", "--format=%{file}\n%{family}\n", "sans-serif:lang=ko")
            self.assertIn("/usr/share/fonts/NotoSansCJK-Regular.ttc", match)
            self.assertIn("Noto Sans CJK", match)
            self.assertEqual(match, fc("fc-match", "--format=%{file}\n%{family}\n", "sans-serif:lang=ko"))
            self.assertIn("NotoSansCJK-Regular.ttc", fc("fc-list", ":lang=ko", "--format=%{file}\n"))
            # Only the temporary test font is removed; host fonts are untouched.
            font.unlink()
            fc("fc-cache", "--force", "/usr/share/fonts")
            self.assertEqual(fc("fc-list", "--format=%{file}\n").strip(), "")

if __name__ == "__main__":
    unittest.main()
