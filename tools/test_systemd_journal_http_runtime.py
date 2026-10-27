"""Opt-in loopback HTTP smoke test for the packaged journal gateway."""

import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

import ki2build


@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_JOURNAL_HTTP") == "1",
                     "set KIKI_TEST_JOURNAL_HTTP=1 on Linux")
class JournalGatewayHTTPTests(unittest.TestCase):
    def test_loopback_http_response(self):
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        with tempfile.TemporaryDirectory(prefix="kiki-journal-http-") as tmp:
            root = Path(tmp) / "root"
            closure = ki2build.dependency_closure(recipes, ["systemd-journal-gatewayd"], "x86_64",
                                                   include_build_deps=False)
            for name in closure:
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                ki2build.extract_package_rootfs(package, root)

            binary = root / "usr/lib/systemd/systemd-journal-gatewayd"
            loader = next(p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink())
            dirs = ":".join(str(root / p) for p in ("usr/lib/systemd", "usr/lib", "usr/lib64", "lib", "lib64"))
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            command = ["systemd-socket-activate", "-l", f"127.0.0.1:{port}", "--",
                       str(loader), "--library-path", dirs, str(binary)]
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, start_new_session=True)
            try:
                response = None
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        self.fail(f"socket activation exited: {process.communicate()[1].decode(errors='replace')}")
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/machine", timeout=2) as reply:
                            response = (reply.status, reply.read(256))
                        break
                    except urllib.error.HTTPError as error:
                        response = (error.code, error.read(256))
                        break
                    except (OSError, urllib.error.URLError):
                        time.sleep(0.2)
                self.assertIsNotNone(response, "gateway did not return HTTP within 15 seconds")
                self.assertEqual(response[0], 200)
                self.assertTrue(response[1])
            finally:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
