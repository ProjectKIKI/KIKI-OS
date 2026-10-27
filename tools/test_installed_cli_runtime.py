"""Opt-in execution checks in a disposable assembled rootfs; no device access."""
import os
from pathlib import Path
import re
import subprocess
import unittest


@unittest.skipUnless(os.environ.get("KIKI_CLI_TEST_ROOTFS"), "set KIKI_CLI_TEST_ROOTFS; Linux root required")
class InstalledCliRuntimeTests(unittest.TestCase):
    def test_executable_library_closure_with_target_loader(self):
        self.assertEqual(os.geteuid(), 0)
        root = Path(os.environ["KIKI_CLI_TEST_ROOTFS"]).resolve(strict=True)
        checked = 0
        failures = []
        for directory in ("bin", "sbin", "usr/bin", "usr/sbin", "usr/lib/systemd"):
            for binary in sorted((root / directory).glob("*")):
                if binary.is_symlink() or not binary.is_file():
                    continue
                with binary.open("rb") as stream:
                    if stream.read(4) != b"\x7fELF":
                        continue
                headers = subprocess.check_output(["readelf", "-l", str(binary)], text=True, timeout=10)
                match = re.search(r"Requesting program interpreter: (.*?)\]", headers)
                if not match:
                    continue
                relative = "/" + binary.relative_to(root).as_posix()
                result = subprocess.run(["chroot", str(root), match[1], "--list", relative],
                                        capture_output=True, text=True, timeout=10,
                                        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"})
                checked += 1
                if result.returncode:
                    failures.append(relative + ": " + result.stderr.strip())
        self.assertGreater(checked, 0, "no target dynamic executables were checked")
        self.assertEqual(failures, [], "\n".join(failures))
        print(f"Target loader resolved {checked} executable library closures")

    def test_core_commands_run_without_host_libraries(self):
        self.assertEqual(os.geteuid(), 0)
        root = Path(os.environ["KIKI_CLI_TEST_ROOTFS"]).resolve(strict=True)
        commands = [
            ["/usr/bin/id", "-u"], ["/usr/bin/ls", "/etc"],
            ["/usr/bin/cp", "--version"], ["/usr/bin/mv", "--version"],
            ["/usr/bin/stat", "/etc"], ["/usr/bin/awk", "BEGIN { print 2 + 3 }"],
            ["/usr/bin/find", "/etc", "-maxdepth", "0"],
            ["/usr/bin/sed", "--version"], ["/usr/bin/grep", "--version"],
            ["/usr/bin/tar", "--version"],
        ]
        for command in commands:
            with self.subTest(command=command[0]):
                result = subprocess.run(["chroot", str(root), *command], capture_output=True,
                                        text=True, timeout=30, env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"})
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                if command[0].endswith("/awk"):
                    self.assertEqual(result.stdout.strip(), "5")


if __name__ == "__main__":
    unittest.main()
