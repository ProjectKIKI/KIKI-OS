"""Required unit enablement must fail closed during rootfs assembly."""
import os
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import ki2build


@unittest.skipUnless(os.name == 'posix', 'requires native POSIX symlinks')
class SystemdEnableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='kiki-enable-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'root'
        self.units = self.root / 'usr/lib/systemd/system'
        self.units.mkdir(parents=True)

    def unit(self, name='test.service', install='WantedBy=multi-user.target\n'):
        path = self.units / name
        path.write_text('[Service]\nExecStart=/usr/bin/true\n[Install]\n' + install)
        return path

    def test_missing_empty_and_directory_units_fail(self):
        for name in ('missing.service', 'empty.service', 'directory.service'):
            if name == 'empty.service':
                (self.units / name).touch()
            elif name == 'directory.service':
                (self.units / name).mkdir()
            with self.subTest(name=name), self.assertRaises(ki2build.Ki2Error):
                ki2build.enable_systemd_units(self.root, [name])

    def test_alias_also_cycle_and_idempotence(self):
        unit = self.unit(install='WantedBy=multi-user.target\nAlias=test-alias.service\nAlso=helper.service\n')
        self.unit('helper.service', 'WantedBy=sysinit.target\nAlso=test.service\n')
        for _ in range(2):
            ki2build.enable_systemd_units(self.root, ['test.service'])
        directory = self.root / 'etc/systemd/system'
        for name in ('multi-user.target.wants/test.service', 'test-alias.service'):
            self.assertTrue((directory / name).is_symlink())
            self.assertEqual((directory / name).resolve(), unit)
        self.assertTrue((directory / 'sysinit.target.wants/helper.service').is_symlink())

    def test_conflicting_files_and_links_are_preserved(self):
        unit = self.unit()
        for kind in ('file', 'dangling', 'wrong'):
            link = self.root / kind
            if kind == 'file':
                link.write_text('keep')
            elif kind == 'dangling':
                link.symlink_to('absent')
            else:
                other = self.root / 'other'
                other.write_text('keep')
                link.symlink_to(other)
            with self.subTest(kind=kind), self.assertRaises(ki2build.Ki2Error):
                ki2build.required_unit_link(link, unit)
            self.assertEqual(link.read_text() if kind == 'file' else os.readlink(link),
                             'keep' if kind == 'file' else ('absent' if kind == 'dangling' else str(other)))

    def test_symlink_permission_failure_is_not_replaced_with_copy(self):
        self.unit()
        with mock.patch.object(Path, 'symlink_to', side_effect=PermissionError('denied')), \
             mock.patch.object(ki2build.shutil, 'copy2') as copy, \
             self.assertRaises(PermissionError):
            ki2build.enable_systemd_units(self.root, ['test.service'])
        copy.assert_not_called()

    def test_missing_also_and_external_unit_fail(self):
        self.unit(install='WantedBy=multi-user.target\nAlso=missing.service\n')
        with self.assertRaises(ki2build.Ki2Error):
            ki2build.enable_systemd_units(self.root, ['test.service'])
        outside = Path(self.tmp.name) / 'external.service'
        outside.write_text('[Service]\nExecStart=/usr/bin/true\n')
        (self.units / 'external.service').symlink_to(outside)
        with self.assertRaises(ki2build.Ki2Error):
            ki2build.enable_systemd_units(self.root, ['external.service'])

    @unittest.skipUnless(os.environ.get('KIKI_ENABLE_TEST_ROOTFS'), 'set KIKI_ENABLE_TEST_ROOTFS for assembled rootfs')
    def test_server_profile_units_from_assembled_rootfs(self):
        source = Path(os.environ['KIKI_ENABLE_TEST_ROOTFS']).resolve(strict=True)
        for relative in ('etc/systemd/system', 'usr/lib/systemd/system', 'lib/systemd/system'):
            if (source / relative).is_dir():
                shutil.copytree(source / relative, self.root / relative, symlinks=True, dirs_exist_ok=True)
        repo = Path(__file__).resolve().parents[1]
        profile = ki2build.load_profile(repo / 'distro/profiles/server-core.toml')
        units = profile['services']['enable']
        self.assertTrue(units)
        ki2build.enable_systemd_units(self.root, units)
        print('Assembled server-core unit snapshot validated:', len(units), 'requested units')


if __name__ == '__main__':
    unittest.main()
