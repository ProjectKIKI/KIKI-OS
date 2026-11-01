import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import ki2cloudseed as cloud


class CloudSeedTests(unittest.TestCase):
    def seed(self):
        return dict(schema='kiki-cloud-install-v1', job_id='a'*32, volume_id='12345678-1234-1234-1234-123456789abc',
                    iso_sha256='a'*64, expires_at=2000, disk_size_gb=32, username='kiki', hostname='kiki-cloud',
                    password='A'*32, report_secret='b'*64, ssh_public_key='ssh-ed25519 '+'A'*68,
                    profile='desktop-gnome', packages=['pkg'+str(n) for n in range(10)], catalog_sha256='c'*64)

    def test_expired_and_line_injection_rejected(self):
        seed=self.seed(); cloud.validate_seed(seed, 1000)
        for field,value in [('expires_at',999),('password','secret\nconfirmed=INSTALL /dev/sda'),('username','root:0'),('packages',['bad\n']*10),('ssh_public_key','ssh-rsa test')]:
            bad=copy.deepcopy(seed);bad[field]=value
            with self.subTest(field=field), self.assertRaises(ValueError):cloud.validate_seed(bad,1000)

    def test_only_unique_empty_matching_volume(self):
        with tempfile.TemporaryDirectory() as temp:
            sysblock=Path(temp)
            for name,serial in [('sda','12345678123412341234123456789abc'),('sdb','unrelated-old-disk')]:
                disk=sysblock/name;(disk/'device').mkdir(parents=True)
                (disk/'device/serial').write_text(serial);(disk/'size').write_text(str(32*1024**3//512))
            self.assertEqual(cloud.choose_disk(self.seed(),sysblock,probe=False),str(Path('/dev/sda')))
            (sysblock/'sda/sda1').mkdir();(sysblock/'sda/sda1/partition').write_text('1')
            with self.assertRaisesRegex(ValueError,'already has partitions'):cloud.choose_disk(self.seed(),sysblock,probe=False)

    def test_ambiguous_or_nonempty_target_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            sysblock=Path(temp)
            disk=sysblock/'sda';(disk/'device').mkdir(parents=True)
            (disk/'device/serial').write_text('12345678123412341234');(disk/'size').write_text(str(32*1024**3//512))
            with patch.object(cloud.subprocess,'run') as run:
                run.return_value.returncode=0
                with self.assertRaisesRegex(ValueError,'not empty'):cloud.choose_disk(self.seed(),sysblock)
            other=sysblock/'sdb';(other/'device').mkdir(parents=True)
            (other/'device/serial').write_text('12345678123412341234');(other/'size').write_text(str(32*1024**3//512))
            with self.assertRaisesRegex(ValueError,'exactly one'):cloud.choose_disk(self.seed(),sysblock,probe=False)

    def test_backend_hook_fails_on_drift(self):
        with self.assertRaisesRegex(ValueError,'does not match backend'):cloud.inject_init('unexpected backend')

    def test_scsi_vpd_serial_matches_only_the_explicit_volume(self):
        with tempfile.TemporaryDirectory() as temp:
            sysblock=Path(temp);disk=sysblock/'sda';(disk/'device').mkdir(parents=True)
            serial=self.seed()['volume_id'].encode();(disk/'device/vpd_pg80').write_bytes(bytes([0,0x80,0,len(serial)])+serial)
            (disk/'size').write_text(str(32*1024**3//512))
            self.assertEqual(cloud.choose_disk(self.seed(),sysblock,probe=False),str(Path('/dev/sda')))
            (disk/'device/vpd_pg80').write_bytes(b'\x00\x80\x00\xffinvalid')
            with self.assertRaisesRegex(ValueError,'exactly one'):cloud.choose_disk(self.seed(),sysblock,probe=False)

    def test_absent_seed_keeps_normal_interactive_boot(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(cloud,'RUN',Path(temp)), patch.object(cloud,'find_seed',return_value=None), patch.object(cloud.subprocess,'run'):
            # The freestanding init normalizes child statuses to 0/1. Absence
            # must therefore be success without the seed-present marker.
            self.assertEqual(cloud.prepare(),0)
            self.assertFalse((Path(temp)/'seed-present').exists())

    def test_host_key_failure_still_unmounts_only_its_device_bind(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(cloud.os.path,'ismount',return_value=False), patch.object(cloud,'command') as run:
            run.side_effect=[None,ValueError('key generation failed'),None]
            with self.assertRaisesRegex(ValueError,'key generation failed'):cloud.generate_host_key(Path(temp))
            self.assertEqual(run.call_args_list[-1].args[0],['/bin/busybox','umount',str(Path(temp)/'dev')])
        with tempfile.TemporaryDirectory() as temp, patch.object(cloud.os.path,'ismount',return_value=True), patch.object(cloud,'command') as run:
            with self.assertRaisesRegex(ValueError,'existing target'):cloud.generate_host_key(Path(temp))
            run.assert_not_called()


if __name__=='__main__':unittest.main()
