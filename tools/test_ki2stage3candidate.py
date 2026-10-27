import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import ki2build
import ki2stage3candidate as candidate


class Stage3CandidateTests(unittest.TestCase):
    def test_recipe_snapshot_roundtrips_nested_commands_and_environment(self):
        raw = {'name': 'probe', 'version': '1', 'summary': 'fixture', 'license': 'MIT',
               'source': {'type': 'local', 'path': 'source'},
               'build': {'system': 'copy', 'configure': ['printf "a\\b"\n'],
                         'env': {'CFLAGS': '-O2'}, 'host_files': [{'source': '/a', 'destination': '/b'}]}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'catalog.toml'
            path.write_text(candidate.recipe_toml([raw]))
            self.assertEqual(ki2build.read_toml(path)['recipe'], [raw])

    def make_repository(self, root, version='6.1.187'):
        packages = root / 'packages/x86_64'
        packages.mkdir(parents=True)
        entries, locked = [], []
        for name in ('linux', 'linux-headers'):
            payload = root / ('payload-' + name)
            payload.mkdir()
            (payload / 'probe').write_text(name)
            recipe = ki2build.normalize_recipe({'name': name, 'version': version, 'summary': 'fixture', 'license': 'MIT',
                'source': {'type': 'local', 'path': str(payload)}}, root / 'fixture.toml')
            path = packages / ki2build.package_filename(recipe, 'x86_64')
            ki2build.create_package(SimpleNamespace(arch='x86_64'), recipe, payload, path, 'fixture', {})
            digest = candidate.sha256_file(path)
            entries.append({'name': name, 'version': version, 'release': '1', 'arch': 'x86_64',
                            'file': path.name, 'sha256': digest, 'size': path.stat().st_size, 'runtime_dependencies': []})
            locked.append({'name': name, 'file': path.name, 'sha256': digest})
        (root / 'repo').mkdir()
        (root / 'repo/index.x86_64.json').write_text(json.dumps({'schema': 'ki2-repository-v1', 'packages': entries}))
        (root / 'snapshot.json').write_text(json.dumps({'kernel': '6.1.187', 'packages': locked, 'sources': []}))
        return entries

    def test_valid_candidate_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_repository(root)
            self.assertEqual(candidate.verify(root)['status'], 'pass')

    def test_old_kernel_cannot_be_restored_to_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_repository(root, '6.9.9')
            with self.assertRaisesRegex(ValueError, 'rejected kernel'):
                candidate.verify(root)

    def test_index_tamper_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_repository(root)
            p = root / 'repo/index.x86_64.json'
            data = json.loads(p.read_text())
            data['packages'][0]['sha256'] = '0' * 64
            p.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'SHA/size mismatch'):
                candidate.verify(root)

    def test_verified_copy_never_overwrites_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, target = root / 'source', root / 'target'
            source.write_bytes(b'new');target.write_bytes(b'preserve')
            with self.assertRaises(FileExistsError):
                candidate.verified_copy(source, target, candidate.sha256_file(source))
            self.assertEqual(target.read_bytes(), b'preserve')


if __name__ == '__main__':
    unittest.main()
