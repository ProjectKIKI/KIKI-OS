import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import build_kiki_admin as build


class CandidateExportTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.base=Path(tmp.name);self.work=self.base/'work';self.output=self.base/'candidate';self.baseline=self.base/'baseline'
        self.repository=self.work/'repo';self.repository.mkdir(parents=True)
        self.packages=self.work/'packages/x86_64';self.packages.mkdir(parents=True)
        self.public=self.baseline/'desktop-installer.ed25519.pub';self.public.parent.mkdir();self.public.write_bytes(b'fixture public key')
        records=[]
        for name in ['kiki-admin','ki2ctl']:
            package=self.packages/(name+'.ki2')
            with tarfile.open(package,'w:gz') as archive:
                body=json.dumps(dict(name=name,files=[])).encode();member=tarfile.TarInfo('manifest.json');member.size=len(body)
                archive.addfile(member,io.BytesIO(body))
            records.append(dict(name=name,file=package.name,sha256=hashlib.sha256(package.read_bytes()).hexdigest()))
        index=self.repository/'index.x86_64.json';index.write_text(json.dumps(dict(packages=records)))
        (self.repository/'metadata.x86_64.json').write_text(json.dumps(dict(index=dict(sha256=hashlib.sha256(index.read_bytes()).hexdigest()))))
        (self.repository/'channels.json').write_text('{}')
        for name,value in [('verify_metadata_ed25519',True)]:
            patcher=patch.object(build.ki2repo,name,return_value=value);patcher.start();self.addCleanup(patcher.stop)
        patcher=patch.object(build.ki2installcatalog,'load',return_value={});patcher.start();self.addCleanup(patcher.stop)
        patcher=patch.object(build.ki2installcatalog,'expand',return_value=dict(packages=['kiki-admin','ki2ctl']));patcher.start();self.addCleanup(patcher.stop)
        patcher=patch.object(build.ki2media,'runtime_closure',return_value=['kiki-admin','ki2ctl']);patcher.start();self.addCleanup(patcher.stop)

    def export(self):
        build.export_candidate(self.work,self.output,self.public,self.baseline)

    def test_only_public_metadata_is_exported_and_completed_candidate_is_immutable(self):
        (self.repository/'do-not-publish.pem').write_bytes(b'fixture, not a credential')
        self.export()
        self.assertFalse((self.output/'repo/do-not-publish.pem').exists())
        before=(self.output/'admin-build.json').read_bytes()
        with self.assertRaisesRegex(AssertionError,'immutable'):self.export()
        self.assertEqual(before,(self.output/'admin-build.json').read_bytes())

    def test_low_space_export_can_resume_without_rebuilding_or_changing_metadata(self):
        with patch.object(build.shutil,'disk_usage',return_value=SimpleNamespace(free=0)):
            with self.assertRaisesRegex(RuntimeError,'free space'):self.export()
        self.assertFalse((self.output/'admin-build.json').exists())
        self.export()
        self.assertTrue((self.output/'admin-build.json').exists())

    @unittest.skipUnless(os.name=='posix','hardlink semantics on Linux')
    def test_partial_export_never_overwrites_a_shared_baseline_inode(self):
        target=self.output/'packages/x86_64/kiki-admin.ki2';target.parent.mkdir(parents=True)
        original=self.base/'original';original.write_bytes(b'preserve these existing bytes')
        os.link(original,target)
        self.export()
        self.assertEqual(original.read_bytes(),b'preserve these existing bytes')
        self.assertEqual(target.read_bytes(),(self.packages/'kiki-admin.ki2').read_bytes())

    def test_resume_rejects_changed_repository_metadata(self):
        directory=self.output/'repo';directory.mkdir(parents=True)
        (directory/'index.x86_64.json').write_text('{}')
        with self.assertRaisesRegex(AssertionError,'metadata'):self.export()


if __name__=='__main__':unittest.main()
