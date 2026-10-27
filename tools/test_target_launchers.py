"""Host/target environment separation; mock loader, no host settings changed."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'posix', 'requires POSIX shell')
class TargetLaunchers(unittest.TestCase):
    def test_target_launch_arguments_and_environment(self):
        with tempfile.TemporaryDirectory(prefix='kiki-launch-test-') as tmp:
            root = Path(tmp)
            loader = root / 'usr/lib64/ld-linux-x86-64.so.2'
            loader.parent.mkdir(parents=True)
            loader.write_text('#!/bin/sh\n[ "${LD_LIBRARY_PATH+x}" != x ] || exit 91\n'
                              '[ "${LD_PRELOAD+x}" != x ] || exit 92\n'
                              'printf "%s\\n" "$@"\n')
            loader.chmod(0o755)
            env = dict(os.environ, KI2_SYSROOT=str(root),
                       KI2_SYSROOT_LIBRARY_PATH=str(root / 'usr/lib'),
                       KI2_REPO_ROOT=str(REPO), KI2_USE_TARGET_LOADER='1',
                       LD_LIBRARY_PATH='/nonexistent/kiki-test-libs', LD_PRELOAD='')
            for script, args, expected in [
                ('ki2-target-python3', ['-c', 'print(1)'], ['-c', 'print(1)']),
                ('ki2-target-g-ir-scanner', ['--version'],
                 [str(root / 'usr/bin/g-ir-scanner'),
                  '--lib-dirs-envvar=KI2_SYSROOT_LIBRARY_PATH', '--version']),
            ]:
                with self.subTest(script=script):
                    result = subprocess.run(['/bin/sh', str(REPO / 'distro/scripts' / script), *args],
                                            env=env, text=True, capture_output=True, check=True)
                    self.assertEqual(result.stdout.splitlines(),
                                     ['--inhibit-cache', '--library-path', str(root / 'usr/lib'),
                                      str(root / 'usr/bin/python3.12'), *expected])

    def test_missing_loader_fails(self):
        with tempfile.TemporaryDirectory(prefix='kiki-launch-test-') as tmp:
            env = dict(os.environ, KI2_SYSROOT=tmp, KI2_SYSROOT_LIBRARY_PATH=tmp)
            result = subprocess.run(['/bin/sh', str(REPO / 'distro/scripts/ki2-target-run'), '/bin/true'],
                                    env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 126)
            self.assertIn('target loader not found', result.stderr)


if __name__ == '__main__':
    unittest.main()
