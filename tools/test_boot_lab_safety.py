"""Destructive-boundary regression tests for disposable boot lab tooling."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import ki2bootsmoke
import ki2securebootlab


class BootLabSafetyTests(unittest.TestCase):
    def test_secure_flags_require_secure_mode(self):
        args = ['ki2bootsmoke', '--mode', 'direct', '--install-result', 'missing.json',
                '--media-root', 'missing-media', '--output-dir', 'must-not-be-created',
                '--expect-rejected']
        with mock.patch('sys.argv', args), mock.patch('subprocess.run') as run:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                ki2bootsmoke.main()
            self.assertEqual(error.exception.code, 2)
            run.assert_not_called()

    def test_missing_secure_inputs_do_not_create_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'untouched'
            args = ['ki2bootsmoke', '--mode', 'secureboot', '--install-result', 'missing.json',
                    '--media-root', 'missing-media', '--output-dir', str(output)]
            with mock.patch('sys.argv', args), mock.patch('subprocess.run') as run:
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    ki2bootsmoke.main()
                self.assertFalse(output.exists())
                run.assert_not_called()

    def test_existing_key_directory_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in ['sdk/usr/lib/systemd/boot/efi/linuxx64.efi.stub',
                             'sdk/usr/bin/sbsign', 'sdk/usr/bin/sbverify', 'sdk/usr/bin/virt-fw-vars',
                             'media/boot/vmlinuz-kiki', 'media/boot/initramfs-kiki-installed.img',
                             'rootfs/etc/os-release', 'ukify.py', 'keys/development-only.key']:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'existing-content')
            args = ['ki2securebootlab', '--sdk', str(root / 'sdk'), '--ukify', str(root / 'ukify.py'),
                    '--media-root', str(root / 'media'), '--rootfs', str(root / 'rootfs'),
                    '--output-dir', str(root / 'keys')]
            with mock.patch('sys.argv', args), mock.patch('subprocess.run') as run:
                with self.assertRaises(FileExistsError):
                    ki2securebootlab.main()
                run.assert_not_called()
            self.assertEqual((root / 'keys/development-only.key').read_bytes(), b'existing-content')


if __name__ == '__main__':
    unittest.main()
