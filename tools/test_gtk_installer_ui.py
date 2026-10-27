"""Build and run the native GTK frontend with isolated backend fixtures."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest


class GtkInstallerUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sys.platform != "linux" or not all(shutil.which(tool) for tool in ("cc", "pkg-config", "go", "xvfb-run")):
            raise unittest.SkipTest("Linux, GTK 4 development files, Go and Xvfb required")
        flags = subprocess.run(["pkg-config", "--cflags", "--libs", "gtk4"], capture_output=True, text=True)
        if flags.returncode:
            raise unittest.SkipTest("GTK 4 development files required")
        cls.repo = Path(__file__).resolve().parents[1]
        cls.temporary = tempfile.TemporaryDirectory(prefix="kiki-gtk-tests-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.work = Path(cls.temporary.name)
        cls.artifacts = Path(os.environ.get("KIKI_GTK_TEST_ARTIFACTS", cls.work)).resolve()
        cls.artifacts.mkdir(parents=True, exist_ok=True)
        cls.env = dict(os.environ, GDK_BACKEND="x11", GSK_RENDERER="cairo", GTK_A11Y="none")
        cls.tui = cls.work / "kiki-installer-tui"
        subprocess.run(["go", "build", "-o", str(cls.tui), "./cmd/kiki-installer-tui"], cwd=cls.repo, check=True)
        for name in ("ui_test", "network_test", "disk_test"):
            subprocess.run(["cc", "-O2", "-Wall", "-Wextra", "-Werror",
                            str(cls.repo / "cmd/kiki-installer-gtk" / f"{name}.c"),
                            "-o", str(cls.work / name), *shlex.split(flags.stdout)], check=True)

    def run_probe(self, name, *args, display=False):
        command = [str(self.work / name), *map(str, args)]
        if display:
            command = ["xvfb-run", "-a", *command]
        result = subprocess.run(command, cwd=self.repo, env=self.env, capture_output=True, text=True, timeout=90)
        (self.artifacts / f"{name}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS:", result.stdout)

    def test_actual_gtk_navigation_plan_request_and_progress(self):
        self.run_probe("ui_test", self.tui, self.artifacts, display=True)

    def test_network_discovery_and_mode_transitions(self):
        fixture = self.work / "network"
        fixture.mkdir()
        self.run_probe("network_test", fixture, display=True)

    def test_whole_writable_disk_discovery(self):
        fixture = self.work / "block"
        fixture.mkdir()
        self.run_probe("disk_test", fixture)


if __name__ == "__main__":
    unittest.main()
