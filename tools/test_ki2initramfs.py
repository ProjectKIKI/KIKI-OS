import gzip
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import ki2initramfs as image


class InitramfsTests(unittest.TestCase):
    def test_helper_refresh_selects_last_archive_without_changing_init(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'base.img';dest=root/'updated.img'
            helper='usr/lib/kiki-installer/ki2cloudseed.py'
            source.write_bytes(image.archive({'init':(b'pinned C init',0o755),helper:(b'old helper',0o755)}))
            image.append(source,dest,{helper:(b'corrected helper',0o755)})
            contents=image.inspect(dest,{'init',helper})
            self.assertEqual(contents['init'],image.inspect(source,{'init'})['init'])
            self.assertEqual(contents[helper]['sha256'],hashlib.sha256(b'corrected helper').hexdigest())

    @unittest.skipUnless(shutil.which('cpio'),'independent GNU cpio verification requires Linux')
    def test_gnu_cpio_and_concatenated_members(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'init').write_bytes(b'original init remains unchanged')
            original=subprocess.run(['cpio','--null','-o','-H','newc'],input=b'init\0',cwd=root,capture_output=True,check=True).stdout
            source=root/'base.img';source.write_bytes(gzip.compress(original,mtime=0));new=root/'new.img'
            image.append(source,new,{'sbin/blkid':(b'added dependency payload',0o755)})
            contents=image.inspect(new,{'init','sbin/blkid'})
            self.assertEqual(contents['init'],image.inspect(source,{'init'})['init'])
            self.assertEqual(contents['sbin/blkid']['bytes'],len(b'added dependency payload'))
            out=root/'independent-extraction';out.mkdir()
            subprocess.run(['cpio','-id','--quiet','--no-preserve-owner','--no-absolute-filenames'],input=gzip.decompress(image.archive({'sbin/blkid':(b'added dependency payload',0o755)})),cwd=out,capture_output=True,check=True)
            self.assertEqual((out/'sbin/blkid').read_bytes(),b'added dependency payload')
            self.assertEqual((out/'sbin/blkid').stat().st_mode&0o777,0o755)

    def test_unsafe_paths_and_oversized_payload_rejected(self):
        for name in ['/etc/key','../escape','a/../../escape']:
            with self.subTest(name=name),self.assertRaises(ValueError):image.archive({name:(b'bad',0o755)})
        with self.assertRaises(ValueError):image.archive({'safe':(b'x'*(8*1024**2+1),0o755)})

    def test_truncated_payload_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'broken.img';payload=gzip.decompress(image.archive({'file':(b'x'*1024,0o644)}))
            path.write_bytes(gzip.compress(payload[:200]))
            with self.assertRaisesRegex(ValueError,'truncated'):image.inspect(path,{'file'})


if __name__=='__main__':unittest.main()
