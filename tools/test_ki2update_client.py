import argparse
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import tarfile
import unittest
from unittest import mock

from test_ki2ctl import write_ki2_package
from test_ki2ctl_hooks import ctl

RECOVERY=Path(__file__).resolve().parents[1]/'distro/sources/ki2ctl/usr/libexec/ki2-kernel-recovery'
loader=importlib.machinery.SourceFileLoader('ki2_recovery_test',str(RECOVERY))
spec=importlib.util.spec_from_loader(loader.name,loader);recovery=importlib.util.module_from_spec(spec);sys.modules[spec.name]=recovery;loader.exec_module(recovery)


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)/'root';self.root.mkdir();self.repo=Path(tmp.name)/'repo';self.repo.mkdir()
        self.args=argparse.Namespace(root=self.root,arch='x86_64',command='upgrade',reinstall=False)

    def install(self,version,default):
        path=self.repo/('demo-'+version+'.ki2')
        write_ki2_package(path,name='demo',version=version,dependencies=[],files={'rootfs/etc/demo.conf':default,'rootfs/usr/bin/demo':b'program '+version.encode()})
        pkg={'name':'demo','version':version,'release':'1','arch':'x86_64','file':path.name,'sha256':ctl.file_sha256(path),'dependencies':{'runtime':[]}}
        origin=ctl.Repo('fixture',self.repo.as_uri())
        with mock.patch.object(ctl,'fetch_package',return_value=path):ctl.execute_install_plan(self.args,[(origin,pkg)])
        return pkg

    def test_modified_configuration_is_preserved_and_new_default_retained(self):
        self.install('1',b'original default')
        (self.root/'etc/demo.conf').write_bytes(b'user configuration')
        self.install('2',b'new default')
        self.assertEqual((self.root/'etc/demo.conf').read_bytes(),b'user configuration')
        sidecars=list((self.root/'etc').glob('demo.conf.ki2new-*'))
        self.assertEqual(len(sidecars),1);self.assertEqual(sidecars[0].read_bytes(),b'new default')
        self.assertEqual(ctl.load_installed(self.root)['packages']['demo']['version'],'2')

    def test_unchanged_default_is_updated_without_sidecar(self):
        self.install('1',b'original default');self.install('2',b'new default')
        self.assertEqual((self.root/'etc/demo.conf').read_bytes(),b'new default')
        self.assertFalse(list((self.root/'etc').glob('*.ki2new-*')))

    def test_legacy_record_without_default_hash_preserves_configuration(self):
        self.install('1',b'legacy default');data=ctl.load_installed(self.root);data['packages']['demo'].pop('config_hashes');ctl.save_installed(self.root,data)
        self.install('2',b'new default')
        self.assertEqual((self.root/'etc/demo.conf').read_bytes(),b'legacy default')

    def test_failure_rolls_back_file_database_and_new_default_sidecar(self):
        first=self.install('1',b'original');(self.root/'etc/demo.conf').write_bytes(b'user value')
        original=ctl.record_install
        def fail(*args,**kwargs):raise OSError('simulated database failure')
        with mock.patch.object(ctl,'record_install',side_effect=fail):
            with self.assertRaisesRegex(OSError,'simulated'):self.install('2',b'new default')
        self.assertEqual((self.root/'etc/demo.conf').read_bytes(),b'user value')
        self.assertEqual((self.root/'usr/bin/demo').read_bytes(),b'program 1')
        self.assertEqual(ctl.load_installed(self.root)['packages']['demo']['version'],'1')
        self.assertFalse(list((self.root/'etc').glob('*.ki2new-*')))

    def library_fixture(self):
        self.install('1',b'configuration');directory=self.root/'usr/lib';directory.mkdir()
        (directory/'libdemo.so.1.0').write_bytes(b'old loaded library')
        (directory/'libdemo.so.1').symlink_to('libdemo.so.1.0');(directory/'libdemo.so').symlink_to('libdemo.so.1')
        db=ctl.load_installed(self.root);db['packages']['demo']['files']+=['/usr/lib/'+n for n in ['libdemo.so','libdemo.so.1','libdemo.so.1.0']];ctl.save_installed(self.root,db)
        package=self.repo/'library.ki2'
        with tarfile.open(package,'w:gz') as tar:
            for name,target in [('libdemo.so','libdemo.so.1'),('libdemo.so.1','libdemo.so.1.0')]:
                member=tarfile.TarInfo('rootfs/usr/lib/'+name);member.type=tarfile.SYMTYPE;member.linkname=target;tar.addfile(member)
            body=b'new library';member=tarfile.TarInfo('rootfs/usr/lib/libdemo.so.1.0');member.size=len(body);member.mode=0o644;tar.addfile(member,io.BytesIO(body))
        pkg={'name':'demo','version':'2','release':'1','arch':'x86_64','file':package.name,'sha256':ctl.file_sha256(package),'dependencies':{'runtime':[]}}
        return directory,package,pkg

    def test_library_upgrade_preserves_symlink_chain_and_old_open_inode(self):
        directory,package,pkg=self.library_fixture()
        with (directory/'libdemo.so.1.0').open('rb') as loaded,mock.patch.object(ctl,'fetch_package',return_value=package):
            ctl.execute_install_plan(self.args,[(ctl.Repo('fixture',self.repo.as_uri()),pkg)])
            self.assertEqual(loaded.read(),b'old loaded library')
        self.assertEqual((directory/'libdemo.so').read_bytes(),b'new library')
        self.assertTrue((directory/'libdemo.so.1.0').is_file());self.assertFalse((directory/'libdemo.so.1.0').is_symlink())
        self.assertEqual((directory/'libdemo.so.1').readlink(),Path('libdemo.so.1.0'))

    def test_failed_library_upgrade_restores_files_and_link_objects(self):
        directory,package,pkg=self.library_fixture()
        with mock.patch.object(ctl,'fetch_package',return_value=package),mock.patch.object(ctl,'record_install',side_effect=OSError('database failure')):
            with self.assertRaisesRegex(OSError,'database failure'):ctl.execute_install_plan(self.args,[(ctl.Repo('fixture',self.repo.as_uri()),pkg)])
        self.assertEqual((directory/'libdemo.so').read_bytes(),b'old loaded library')
        self.assertEqual((directory/'libdemo.so.1').readlink(),Path('libdemo.so.1.0'))
        self.assertFalse((directory/'libdemo.so.1.0').is_symlink())

    def test_unexpected_offline_error_clears_the_boot_marker(self):
        original_is_symlink=Path.is_symlink;original_unlink=Path.unlink;original_readlink=ctl.os.readlink
        removed=[];stage=ctl.offline_directory(self.root)
        def is_link(path):return True if str(path)=='/system-update' else original_is_symlink(path)
        def unlink(path,*args,**kwargs):
            if str(path)=='/system-update':removed.append(str(path));return
            return original_unlink(path,*args,**kwargs)
        def readlink(path,*args,**kwargs):return str(stage) if str(path)=='/system-update' else original_readlink(path,*args,**kwargs)
        with mock.patch.object(ctl,'command_offline_apply',side_effect=RuntimeError('unexpected extraction failure')),mock.patch.object(Path,'is_symlink',is_link),mock.patch.object(Path,'unlink',unlink),mock.patch.object(ctl.os,'readlink',readlink):
            self.assertEqual(ctl.main(['--root',str(self.root),'offline-apply']),1)
        self.assertEqual(removed,['/system-update'])
        self.assertEqual(json.loads((stage/'failure.json').read_text())['error'],'unexpected extraction failure')


class KernelRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.esp=Path(temp.name)
        (self.esp/'EFI/BOOT').mkdir(parents=True);(self.esp/'EFI/BOOT/BOOTX64.EFI').write_bytes(b'fixture EFI')
        (self.esp/'boot/grub').mkdir(parents=True)
        (self.esp/'boot/grub/kiki-installed.cfg').write_text("set default=0\nmenuentry 'current' { }\n")
        (self.esp/'boot/vmlinuz-kiki').write_bytes(b'old kernel');(self.esp/'boot/initramfs-kiki.img').write_bytes(b'old initramfs')

    def test_previous_kernel_and_initramfs_survive_current_kernel_replacement(self):
        manifest=recovery.prepare(self.esp,'/dev/sda3')
        (self.esp/'boot/vmlinuz-kiki').write_bytes(b'new kernel')
        self.assertEqual(recovery.check(self.esp),manifest)
        path=self.esp/'boot/ki2-recovery'/manifest['id']/'vmlinuz-kiki'
        self.assertEqual(path.read_bytes(),b'old kernel')
        recovery.select(self.esp,True)
        self.assertIn("set default='kiki-recovery'",(self.esp/'boot/grub/kiki-installed.cfg').read_text())
        recovery.select(self.esp,False)
        self.assertTrue((self.esp/'boot/grub/kiki-installed.cfg').read_text().startswith('set default=0'))

    def test_corrupt_recovery_image_cannot_be_selected(self):
        manifest=recovery.prepare(self.esp,'/dev/sda3')
        (self.esp/'boot/ki2-recovery'/manifest['id']/'initramfs-kiki.img').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'checksum'):recovery.select(self.esp,True)

    def test_repeated_prepare_keeps_one_managed_menu_entry(self):
        recovery.prepare(self.esp,'/dev/sda3');recovery.prepare(self.esp,'/dev/sda3')
        self.assertEqual((self.esp/'boot/grub/kiki-installed.cfg').read_text().count('--id kiki-recovery'),1)

    def test_gpt_esp_detection_supports_512_and_4096_byte_sectors(self):
        import struct,uuid,zlib
        for sector in [512,4096]:
            entries=bytearray(4*128);entries[:16]=uuid.UUID('c12a7328-f81f-11d2-ba4b-00a0c93ec93b').bytes_le
            header=bytearray(sector);header[:8]=b'EFI PART';struct.pack_into('<I',header,12,92)
            struct.pack_into('<QIII',header,72,2,4,128,zlib.crc32(entries));struct.pack_into('<I',header,16,zlib.crc32(header[:92]))
            disk=self.esp/('disk-'+str(sector));disk.write_bytes(bytes(sector)+header+entries)
            self.assertEqual(recovery.gpt_esp_numbers(disk,sector),[1])
            damaged=bytearray(disk.read_bytes());damaged[sector+20]^=1;disk.write_bytes(damaged)
            with self.assertRaisesRegex(ValueError,'checksum'):recovery.gpt_esp_numbers(disk,sector)


if __name__=='__main__':unittest.main()
