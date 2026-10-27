"""Opt-in PTY test using packaged TUI and a simulated, non-destructive backend."""
import os
import pty
import select
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import ki2bootiso


@unittest.skipUnless(os.environ.get("KIKI_TEST_TUI_PTY") == "1", "explicit Linux root PTY test required")
class TUIPTYTests(unittest.TestCase):
    def test_packaged_tui_request_progress_reboot_and_failure(self):
        self.assertEqual(os.geteuid(), 0)
        packages = Path(__file__).resolve().parents[1] / "dist/ki2/packages/x86_64"
        for outcome in ("completed", "failed"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory(prefix="kiki-tui-pty-") as tmp:
                root = Path(tmp)
                run = root / "run/kiki"
                run.mkdir(parents=True)
                (run / "tui-backend.ready").write_text("ready\n")
                ki2bootiso.extract_package_members(ki2bootiso.latest_package(packages, "kiki-installer-tui"),
                                                  root, {"usr/bin/kiki-installer-tui"})
                master, slave = pty.openpty()
                proc = subprocess.Popen(["chroot", str(root), "/usr/bin/kiki-installer-tui",
                    "--fullscreen", "--ascii", "--profile", "server-core"],
                    stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
                os.close(slave)
                transcript = bytearray()
                def wait_text(text):
                    deadline = time.monotonic() + 10
                    start = len(transcript)
                    while time.monotonic() < deadline:
                        if select.select([master], [], [], .1)[0]:
                            transcript.extend(os.read(master, 65536))
                        if text.encode() in transcript[start:]:
                            return
                    self.fail(f"TUI timeout waiting for {text!r}")
                def wait_file(path):
                    deadline = time.monotonic() + 10
                    while not path.exists() and time.monotonic() < deadline:
                        time.sleep(.05)
                    self.assertTrue(path.exists(), str(path))
                def progress(state, percent, installed):
                    tmpfile = run / "progress.tmp"
                    tmpfile.write_text(f"version=1\nstate={state}\npercent={percent}\nphase=test\nmessage=test\npackages_installed={installed}\npackages_total=2\npackage=test-package\n")
                    tmpfile.replace(run / "install-progress.state")
                try:
                    wait_text("TUI fallback")
                    os.write(master, b"0\r")
                    wait_text("Administrator password")
                    secret = "암호나1234".encode()
                    os.write(master, "암호가\x7f나1234\r".encode())
                    wait_text("Repeat password")
                    os.write(master, secret + b"\r")
                    wait_text("Erase ALL data")
                    os.write(master, b"INSTALL /dev/sda\r")
                    request = run / "gui-install.request"
                    wait_file(request)
                    contents = request.read_bytes()
                    self.assertIn(b"confirmed=INSTALL /dev/sda\n", contents)
                    self.assertIn(b"password=" + secret + b"\n", contents)
                    self.assertEqual(request.stat().st_mode & 0o777, 0o600)
                    self.assertNotIn(secret, (run / "install-plan.yaml").read_bytes())
                    request.write_bytes(b"")
                    progress("running", 50, 1)
                    wait_text("Packages completed: 1 / 2")
                    progress(outcome, 100 if outcome == "completed" else 50, 2 if outcome == "completed" else 1)
                    wait_text("Press q to return to CLI.")
                    self.assertNotIn(secret, transcript)
                    self.assertNotIn("암호".encode(), transcript)
                    if outcome == "completed":
                        self.assertFalse((run / "gui-reboot.request").exists())
                        os.write(master, b"r")
                        wait_file(run / "gui-reboot.request")
                    else:
                        os.write(master, b"q")
                        self.assertEqual(proc.wait(timeout=10), 0)
                        self.assertFalse((run / "gui-reboot.request").exists())
                finally:
                    if proc.poll() is None:
                        proc.terminate()
                        try: proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            proc.kill(); proc.wait()
                    os.close(master)


if __name__ == "__main__":
    unittest.main()
