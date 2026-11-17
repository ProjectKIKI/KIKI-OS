"""Exercise real Xvfb readiness, exit propagation, timeout and cleanup."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(sys.platform == "linux" and shutil.which("Xvfb"), "Linux Xvfb required")
class XvfbRunnerTests(unittest.TestCase):
    def run_fixture(self, code, timeout="5", env=None):
        with tempfile.TemporaryDirectory(prefix="kiki-xvfb-check-") as temporary:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("ki2xvfb.py")),
                 "--artifacts", temporary, "--command-timeout", timeout,
                 "--", sys.executable, "-c", code],
                env=env, capture_output=True, text=True, timeout=20,
            )
            reports = list(Path(temporary).glob("*.json"))
            self.assertEqual(len(reports), 1, result.stderr)
            record = json.loads(reports[0].read_text())
            if "server_pid" in record:
                with self.assertRaises(ProcessLookupError):
                    os.kill(record["server_pid"], 0)
            if "application_pid" in record:
                with self.assertRaises(ProcessLookupError):
                    os.kill(record["application_pid"], 0)
            return result, record

    def test_real_setup_and_success(self):
        result, record = self.run_fixture(
            "import os; assert os.environ['DISPLAY'].startswith(':'); "
            "assert os.environ['GDK_BACKEND']=='x11'",
            env=dict(os.environ, GDK_BACKEND="wayland"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(record["ready"])

    def test_child_failure_is_not_hidden(self):
        result, record = self.run_fixture("raise SystemExit(23)")
        self.assertEqual(result.returncode, 23)
        self.assertEqual(record["exit"], 23)
        self.assertTrue(record["ready"])

    def test_timeout_stops_server(self):
        result, record = self.run_fixture("import time; time.sleep(5)", timeout="0.1")
        self.assertEqual(result.returncode, 124)
        self.assertIn("timeout", record["error"])

    def test_missing_server_is_failure(self):
        result, record = self.run_fixture("pass", env=dict(os.environ, PATH="/nonexistent"))
        self.assertEqual(result.returncode, 125)
        self.assertFalse(record["ready"])
        self.assertIn("error", record)


if __name__ == "__main__":
    unittest.main()
