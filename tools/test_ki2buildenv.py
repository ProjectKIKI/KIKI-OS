import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ki2buildenv


class BuildEnvironmentTests(unittest.TestCase):
    def test_refresh_cannot_accept_modified_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'manifests').mkdir()
            data = {k: {} for k in ('python', 'venv_files', 'stdlib', 'tools_and_host_libraries', 'lock')}
            path = root / 'manifests/environment.json'
            path.write_text(json.dumps({'fingerprint': 'old', 'data': data}))
            changed = json.loads(json.dumps(data));changed['venv_files']['meson'] = 'tampered'
            with patch.object(ki2buildenv, 'config', return_value=({}, {}, root)), \
                 patch.object(ki2buildenv, 'snapshot', return_value={'fingerprint': 'new', 'data': changed}):
                with self.assertRaisesRegex(ki2buildenv.BuildEnvironmentError, 'changed runtime'):
                    ki2buildenv.refresh(root / 'profile')
            self.assertEqual(json.loads(path.read_text())['fingerprint'], 'old')

    def test_parent_search_paths_and_loader_flags_are_not_inherited(self):
        with patch.dict(os.environ, {'PATH': '/user/bin', 'LD_LIBRARY_PATH': '/target/lib',
                                     'PYTHONPATH': '/user/python', 'CFLAGS': '-I/host/include'}):
            env = ki2buildenv.clean_environment(Path('/build/isolated'))
        self.assertEqual(env['PATH'], '/build/isolated/venv/bin:/usr/bin:/bin')
        for name in ('LD_LIBRARY_PATH', 'LD_PRELOAD', 'PYTHONPATH', 'CFLAGS', 'PKG_CONFIG_PATH'):
            self.assertNotIn(name, env)
        self.assertEqual(env['PYTHONNOUSERSITE'], '1')

    def test_changed_installed_environment_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'manifests').mkdir()
            (root / 'manifests/environment.json').write_text(json.dumps({'fingerprint': 'original'}))
            with patch.object(ki2buildenv, 'config', return_value=({}, {}, root)), \
                 patch.object(ki2buildenv, 'snapshot', return_value={'fingerprint': 'changed'}):
                with self.assertRaisesRegex(ki2buildenv.BuildEnvironmentError, 'fingerprint changed'):
                    ki2buildenv.check(root / 'profile')

    def test_fingerprint_tracks_environment_and_not_json_order(self):
        self.assertEqual(ki2buildenv.stable({'a': 1, 'b': 2}), ki2buildenv.stable({'b': 2, 'a': 1}))
        self.assertNotEqual(ki2buildenv.stable({'meson': '1.9.2'}), ki2buildenv.stable({'meson': '1.11.1'}))

    def test_wrong_base_python_hash_fails_before_running_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'python'
            path.write_bytes(b'not the approved interpreter')
            with patch.object(ki2buildenv, 'capture') as capture:
                with self.assertRaisesRegex(ki2buildenv.BuildEnvironmentError, 'SHA-256'):
                    ki2buildenv.base_check({'python': str(path), 'python_sha256': '0' * 64}, {})
                capture.assert_not_called()


if __name__ == '__main__':
    unittest.main()
