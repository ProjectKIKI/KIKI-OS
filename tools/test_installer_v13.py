"""Contract tests for the isolated C installer rollout and immutable runtime refresh."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import tarfile
import tempfile
import unittest

import ki2build
import ki2graphics
import ki2refreshinstaller
import ki2osbuild


class InstallerV13Tests(unittest.TestCase):
    def test_os_build_uses_c_without_silent_compatibility_fallback(self):
        args = ki2osbuild.build_parser().parse_args(['plan'])
        ctx = ki2osbuild.make_context(args)
        ctx.plan['graphics'] = {'enabled': True}
        for choice in (None, 'gotk'):
            if choice:ctx.plan['graphics']['installer_ui'] = choice
            command = next(s.command for s in ki2osbuild.build_steps(ctx) if 'tools/ki2graphics.py' in s.command)
            self.assertEqual(command[command.index('--installer-ui') + 1], choice or 'c')
        ctx.plan['graphics']['installer_ui'] = 'unknown'
        with self.assertRaises(ki2osbuild.OsBuildError):ki2osbuild.build_steps(ctx)

    def test_official_default_and_explicit_compatibility(self):
        self.assertEqual(ki2graphics.parser().parse_args(['prepare']).installer_ui, 'c')
        self.assertEqual(ki2graphics.parser().parse_args(['prepare', '--installer-ui', 'gotk']).installer_ui, 'gotk')

    def test_refresh_preserves_runtime_and_rejects_implementation_or_catalog_changes(self):
        repo = Path(__file__).resolve().parents[1]
        recipe = ki2build.load_recipes(repo / 'distro/recipes')['kiki-installer-gtk']
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = root / 'payload'
            runtime = payload / 'usr/share/kiki-installer-gtk/runtime-manifest.json'
            runtime.parent.mkdir(parents=True)
            executable = payload / 'usr/bin/kiki-installer-gtk'
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b'preserved baseline binary')
            executable.chmod(0o755)
            private = payload / 'usr/lib/kiki-private/keep'
            private.parent.mkdir(parents=True)
            private.write_bytes(b'preserve shared ABI bytes')
            catalog = repo / 'distro/sources/ki2ctl/usr/share/ki2/package-groups.json'
            manifest = dict(schema='kiki-graphics-runtime-v1', installer_ui='c', bytes=1000,
                            catalog_sha256=hashlib.sha256(catalog.read_bytes()).hexdigest())
            runtime.write_text(json.dumps(manifest))
            baseline = root / 'old.ki2'
            ki2build.create_package(SimpleNamespace(arch='x86_64'), replace(recipe, release='28'),
                                   payload, baseline, 'fixture-baseline', {})
            old_hash = hashlib.sha256(baseline.read_bytes()).hexdigest()
            binary = root / 'new-binary'
            binary.write_bytes(b'KIKI_INSTALLER_UI_V13_C fixture replacement')
            output = root / 'new.ki2'
            ki2refreshinstaller.refresh(baseline, binary, output, 29, repo)
            with tarfile.open(output, 'r:gz') as archive:
                self.assertEqual(archive.extractfile('rootfs/usr/lib/kiki-private/keep').read(), private.read_bytes())
                self.assertEqual(archive.extractfile('rootfs/usr/bin/kiki-installer-gtk').read(), binary.read_bytes())
                updated = json.load(archive.extractfile('rootfs/usr/share/kiki-installer-gtk/runtime-manifest.json'))
                self.assertEqual(updated['installer_ui'], 'c')
                self.assertEqual(updated['installer_binary_sha256'], hashlib.sha256(binary.read_bytes()).hexdigest())
                self.assertEqual(updated['catalog_sha256'], manifest['catalog_sha256'])
            self.assertEqual(hashlib.sha256(baseline.read_bytes()).hexdigest(), old_hash)
            with self.assertRaisesRegex(ValueError, 'overwrite'):
                ki2refreshinstaller.refresh(baseline, binary, output, 29, repo)
            with self.assertRaisesRegex(ValueError, 'greater'):
                ki2refreshinstaller.refresh(baseline, binary, root / 'bad-release.ki2', 28, repo)
            manifest['installer_ui'] = 'gotk'
            runtime.write_text(json.dumps(manifest))
            wrong = root / 'wrong-ui.ki2'
            ki2build.create_package(SimpleNamespace(arch='x86_64'), replace(recipe, release='28'),
                                   payload, wrong, 'fixture-other-ui', {})
            with self.assertRaisesRegex(ValueError, 'implementations'):
                ki2refreshinstaller.refresh(wrong, binary, root / 'rejected-ui.ki2', 29, repo)
            manifest.update(installer_ui='c', catalog_sha256='0' * 64)
            runtime.write_text(json.dumps(manifest))
            wrong_catalog = root / 'wrong-catalog.ki2'
            ki2build.create_package(SimpleNamespace(arch='x86_64'), replace(recipe, release='28'),
                                   payload, wrong_catalog, 'fixture-other-catalog', {})
            with self.assertRaisesRegex(ValueError, 'catalog changed'):
                ki2refreshinstaller.refresh(wrong_catalog, binary, root / 'rejected-catalog.ki2', 29, repo)
            self.assertFalse((root / 'rejected-ui.ki2').exists())
            self.assertFalse((root / 'rejected-catalog.ki2').exists())


if __name__ == '__main__':
    unittest.main()
