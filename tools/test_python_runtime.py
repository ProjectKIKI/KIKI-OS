"""Opt-in target Python modules needed by the installer and GIR tools."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import ki2build

PROBE = r'''
import ctypes, hashlib, json, lzma, math, ssl, sys, zlib
import xml.etree.ElementTree as ET
assert sys.version_info[:3] == (3, 12, 4)
assert math.sqrt(81) == 9
payload = '한국어 설치 및 GIR 검사'.encode()
assert zlib.decompress(zlib.compress(payload)) == payload
assert lzma.decompress(lzma.compress(payload)) == payload
assert json.loads(json.dumps({'text': payload.decode()}, ensure_ascii=False))['text'] == payload.decode()
assert ET.fromstring('<root>한국어</root>').text == '한국어'
assert hashlib.sha256(b'abc').hexdigest() == 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
assert ssl.OPENSSL_VERSION.startswith('OpenSSL ')
libc = ctypes.CDLL('libc.so.6')
libc.gnu_get_libc_version.restype = ctypes.c_char_p
assert libc.gnu_get_libc_version() == b'2.39'
libc.strlen.argtypes = [ctypes.c_char_p]
libc.strlen.restype = ctypes.c_size_t
assert libc.strlen(payload) == len(payload)
callback = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int)(lambda number: number + 7)
assert callback(35) == 42
print('target Python required modules and libffi callback passed')
'''

@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_PYTHON") == "1",
                     "set KIKI_TEST_PYTHON=1 on Linux as root")
class PythonRuntimeTests(unittest.TestCase):
    def test_required_modules(self):
        self.assertEqual(os.geteuid(), 0)
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        with tempfile.TemporaryDirectory(prefix="kiki-python-runtime-") as tmp:
            root = Path(tmp) / "root"
            for name in ki2build.dependency_closure(recipes, ["python"], "x86_64", include_build_deps=False):
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            (root / "tmp").mkdir(exist_ok=True)
            (root / "probe.py").write_text(PROBE)
            loaders = [p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            result = subprocess.run([
                "chroot", str(root), "/" + str(loaders[0].relative_to(root)),
                "--inhibit-cache", "--library-path", "/usr/lib:/usr/lib64:/lib:/lib64",
                "/usr/bin/python3.12", "-I", "-B", "/probe.py"],
                env={"PATH":"/usr/sbin:/usr/bin:/bin", "LC_ALL":"C"},
                capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("required modules and libffi callback passed", result.stdout)

if __name__ == "__main__":
    unittest.main()
