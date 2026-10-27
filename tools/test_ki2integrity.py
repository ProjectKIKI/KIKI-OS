import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

import ki2integrity


class IntegrityTests(unittest.TestCase):
    def package(self, path, payload, declared=b'correct', extra=False):
        manifest = {'name': 'probe', 'files': [{'path': '/usr/share/probe',
            'type': 'file', 'mode': '0o644', 'size': len(declared),
            'sha256': hashlib.sha256(declared).hexdigest()}]}
        with tarfile.open(path, 'w:gz') as archive:
            for name, data in [('manifest.json', json.dumps(manifest).encode()),
                               ('rootfs/usr/share/probe', payload)]:
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(data), 0o644
                archive.addfile(info, io.BytesIO(data))
            if extra:
                info = tarfile.TarInfo('rootfs/../../escape')
                info.size = 1
                archive.addfile(info, io.BytesIO(b'x'))

    def test_valid_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'probe.ki2'
            self.package(path, b'correct')
            self.assertEqual(ki2integrity.audit_payload(path)['errors'], [])

    def test_tampering_detected_without_external_archive_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'probe.ki2'
            self.package(path, b'changed')
            self.assertIn('sha256 mismatch: /usr/share/probe', ki2integrity.audit_payload(path)['errors'])

    def test_archive_escape_reported_without_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'probe.ki2'
            self.package(path, b'correct', extra=True)
            self.assertTrue(any('unexpected archive path' in s for s in ki2integrity.audit_payload(path)['errors']))
            self.assertFalse((Path(tmp) / 'escape').exists())

    def test_stale_repository_blocks_build_even_with_valid_payloads(self):
        summary = {'source_hash_mismatches': 0, 'package_payload_failures': 0,
                   'files_changed_during_audit': 0, 'missing_recipe_sources': 0,
                   'index_statuses': {'match': 10, 'mismatch': 1}}
        self.assertFalse(ki2integrity.build_gate({'summary': summary}))
        summary['index_statuses'] = {'match': 11}
        self.assertTrue(ki2integrity.build_gate({'summary': summary}))


if __name__ == '__main__':
    unittest.main()
