"""Run upstream CLI golden cases against the actual target FriBidi package."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
import ki2build

@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_FRIBIDI") == "1",
                     "set KIKI_TEST_FRIBIDI=1 on Linux as root")
class FriBidiRuntimeTests(unittest.TestCase):
    def test_upstream_cli_cases(self):
        self.assertEqual(os.geteuid(),0)
        repo=Path(__file__).resolve().parents[1]
        recipes=ki2build.load_recipes(repo/"distro/recipes")
        source=repo/"dist/sources/fribidi-1.0.16.tar.xz"
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),
                         "1b1cde5b235d40479e91be2f0e88a309e3214c8ab470ec8a2744d82a5a9ea05c")
        with tempfile.TemporaryDirectory(prefix="kiki-fribidi-runtime-") as tmp:
            root=Path(tmp)/"root"
            for name in ki2build.dependency_closure(recipes,["fribidi"],"x86_64",include_build_deps=False):
                package=repo/"dist/ki2/packages/x86_64"/ki2build.package_filename(recipes[name],"x86_64")
                self.assertTrue(package.is_file(),str(package))
                ki2build.extract_package_rootfs(package,root)
            def run(command):
                result=subprocess.run(command,env={"PATH":"/usr/sbin:/usr/bin:/bin","LC_ALL":"C"},capture_output=True,timeout=60)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                return result.stdout
            loaders=[p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders),1)
            base=["chroot",str(root),"/"+str(loaders[0].relative_to(root)),"--inhibit-cache","--library-path","/usr/lib:/usr/lib64:/lib:/lib64"]
            self.assertIn(b"libfribidi.so.0 => /",run(base+["--list","/usr/bin/fribidi"]))
            self.assertNotRegex(run(["readelf","-d",str(root/"usr/lib/libfribidi.so.0")]).decode(),r"\((?:RPATH|RUNPATH)\)")
            self.assertIn(b"1.0.16",run(base+["/usr/bin/fribidi","--version"]))
            cases=[("CapRTL","explicit"),("CapRTL","implicit"),("CapRTL","isolate"),
                   ("ISO8859-8","hebrew"),("UTF-8","persian"),("UTF-8","reordernsm")]
            with tarfile.open(source,"r:xz") as archive:
                for charset, suffix in cases:
                    with self.subTest(charset=charset,case=suffix):
                        stem="fribidi-1.0.16/test/test_"+charset+"_"+suffix
                        (root/"input").write_bytes(archive.extractfile(stem+".input").read())
                        expected=archive.extractfile(stem+".reference").read()
                        actual=run(base+["/usr/bin/fribidi","--test","--charset",charset,"/input"])
                        self.assertEqual(actual,expected)
            self.assertTrue((root/"usr/share/licenses/fribidi/COPYING").is_file())

if __name__ == "__main__":
    unittest.main()
