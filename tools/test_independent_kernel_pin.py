"""Independent ISO/target kernel recipe must not silently drift to another series."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import tempfile
import ki2build
import ki2bootiso
import ki2iso_preserved
from pathlib import Path
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

class IndependentKernelPinTests(unittest.TestCase):
    def test_preserved_backend_uses_verified_snapshot_kernel(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'linux-new.ki2').write_bytes(b'new kernel')
            original=unittest.mock.Mock(return_value=root/'vmlinuz')
            guard=ki2iso_preserved.kernel_guard(original,'linux-new.ki2','expected',lambda p:'expected',lambda p:{'name':'linux','errors':[]})
            self.assertEqual(guard(root,root,root,pinned_filename='linux-old.ki2'),root/'vmlinuz')
            original.assert_called_once_with(root,root,root,pinned_filename='linux-new.ki2')
            original.reset_mock()
            bad=ki2iso_preserved.kernel_guard(original,'linux-new.ki2','expected',lambda p:'tampered',lambda p:{'name':'linux','errors':[]})
            with self.assertRaisesRegex(ValueError,'SHA mismatch'):bad(root,root,root)
            original.assert_not_called()

    def test_missing_pinned_package_never_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ctx = SimpleNamespace(packages_dir=root, arch='x86_64')
            recipes = ki2build.load_recipes(Path(__file__).resolve().parents[1] / 'distro/recipes')
            with patch.object(ki2build, 'package_artifact_by_name') as fallback:
                self.assertIsNone(ki2build.package_artifact_for_recipe(ctx, recipes['linux']))
                fallback.assert_not_called()
            (root / 'boot').mkdir()
            (root / 'boot/vmlinuz-kiki').write_bytes(b'stale')
            with self.assertRaisesRegex(ki2bootiso.BootIsoError, 'pinned kernel package missing'):
                ki2bootiso.find_kernel(root, root, root / 'work', pinned_filename=ki2build.package_filename(recipes['linux'], 'x86_64'))

    def test_vm_drivers_are_explicit(self):
        root = Path(__file__).resolve().parents[1]
        fragment = (root / 'distro/kernel/x86_64-vm-stage1.config').read_text()
        for option in ['CONFIG_DRM_BOCHS=y', 'CONFIG_DRM_HYPERV=y', 'CONFIG_HYPERV_NET=y', 'CONFIG_HYPERV_STORAGE=y']:
            self.assertIn(option, fragment)

    def test_kernel_and_headers_share_verified_61_source(self):
        root = Path(__file__).resolve().parents[1]
        recipes = tomllib.loads((root / 'distro/recipes/core.toml').read_text())['recipe']
        selected = {r['name']: r for r in recipes if r['name'] in ('linux', 'linux-headers')}
        self.assertEqual(set(selected), {'linux', 'linux-headers'})
        for recipe in selected.values():
            self.assertEqual(recipe['version'], '6.1.187')
            self.assertEqual(recipe['source']['url'], 'https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.1.187.tar.xz')
            self.assertEqual(recipe['source']['sha256'], '1b6e798aeaa708ca670a426ad5a6c86dc2237b8e59e8822876976c383873642b')

if __name__ == '__main__':
    unittest.main()
