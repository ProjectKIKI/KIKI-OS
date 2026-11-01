import copy
import os
import tempfile
from pathlib import Path
import unittest
import ki2clouddeploy as cloud


class CloudDeploymentTests(unittest.TestCase):
    def result(self):
        expected={'packages':{'linux':'a'*64},'critical_files':{'/boot/vmlinuz':'b'*64},'catalog_sha256':'c'*64,'security_policy_sha256':'d'*64}
        manifest={'job_id':'e'*32,'iso_sha256':'f'*64,'expected':expected}
        report={'status':'passed','checks':{'actual_vm_check':True},'vm_id':'runtime1','iso_sha256':manifest['iso_sha256'],'catalog_sha256':expected['catalog_sha256'],'installed_count':1,'critical_files_checked':1,'boot_id':'boot1','scap':{'policy_sha256':expected['security_policy_sha256'],'rules':[{'result':'pass'} for _ in range(9)]}}
        second=copy.deepcopy(report);second['boot_id']='boot2'
        return manifest,{'id':manifest['job_id'],'iso_sha256':manifest['iso_sha256'],'status':'passed','runtimeVmId':'runtime1','reports':[report,second]}

    def test_two_boot_report_binds_all_inputs_and_unchanged_scap(self):
        manifest,response=self.result();cloud.validate_result(response,manifest)
        for field,value in [('vm_id','wrong-vm'),('iso_sha256','wrong-iso'),('installed_count',0),('critical_files_checked',0),('boot_id','boot1'),('checks',{'failed':False})]:
            bad=copy.deepcopy(response);bad['reports'][1][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):cloud.validate_result(bad,manifest)
        bad=copy.deepcopy(response);bad['reports'][1]['scap']['rules'][0]['result']='fail'
        with self.assertRaisesRegex(ValueError,'OpenSCAP'):cloud.validate_result(bad,manifest)

    def test_different_build_and_false_pass_are_rejected(self):
        manifest,response=self.result()
        with self.assertRaisesRegex(ValueError,'identity'):cloud.validate_result({**response,'id':'other-build'},manifest)
        with self.assertRaisesRegex(ValueError,'two distinct'):cloud.validate_result({**response,'reports':[]},manifest)
        cloud.validate_result({**response,'status':'installing','reports':[]},manifest)

    def test_legacy_xccdf_anchor_requires_verified_bundle_and_all_three_files(self):
        manifest,response=self.result();critical=manifest['expected']['critical_files']
        files={'/usr/share/kiki-security/'+name:str(i)*64 for i,name in enumerate(cloud.POLICY_FILES,1)}
        critical.update(files);manifest['expected']['security_policy_sha256']=files['/usr/share/kiki-security/kiki-desktop-xccdf.xml']
        for report in response['reports']:
            report.update(policy_content_files=dict(files),critical_files_checked=len(critical))
            report['scap']['policy_sha256']='a'*64
        cloud.validate_result(response,manifest,'a'*64)
        bad=copy.deepcopy(response);bad['reports'][0]['policy_content_files'][next(iter(files))]='b'*64
        with self.assertRaisesRegex(ValueError,'file hashes'):cloud.validate_result(bad,manifest,'a'*64)
        bad=copy.deepcopy(response);bad['reports'][0]['scap']['policy_sha256']=manifest['expected']['security_policy_sha256']
        with self.assertRaisesRegex(ValueError,'OpenSCAP'):cloud.validate_result(bad,manifest,'a'*64)

    @unittest.skipUnless(os.name=='posix','existing scanner requires Linux pwd')
    def test_bundle_digest_matches_existing_scanner_and_rejects_tampering(self):
        import hashlib,io,runpy,tarfile
        scanner=runpy.run_path(str(Path(__file__).resolve().parents[1]/'distro/sources/kiki-security-content/usr/libexec/kiki-security-scan'))
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);package=root/'content.ki2';critical={}
            with tarfile.open(package,'w') as archive:
                for name in cloud.POLICY_FILES:
                    raw=('<test>'+name+'</test>').encode();(root/name).write_bytes(raw)
                    entry=tarfile.TarInfo('rootfs/usr/share/kiki-security/'+name);entry.size=len(raw)
                    archive.addfile(entry,io.BytesIO(raw));critical['/usr/share/kiki-security/'+name]=hashlib.sha256(raw).hexdigest()
            package_sha=hashlib.sha256(package.read_bytes()).hexdigest()
            self.assertEqual(cloud.package_policy_digest(package,package_sha,critical),scanner['policy_hash'](root))
            changed=dict(critical);changed[next(iter(changed))]='0'*64
            with self.assertRaisesRegex(ValueError,'payload mismatch'):cloud.package_policy_digest(package,package_sha,changed)

    def test_published_parts_reject_changed_bytes_on_retry(self):
        import hashlib
        def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);iso=root/'image.iso';iso.write_bytes(b'ISO test data');out=root/'parts'
            parts=cloud.publish_parts(iso,out,sha);self.assertEqual(cloud.publish_parts(iso,out,sha),parts)
            (out/(parts[0]['sha256']+'.part')).write_bytes(b'bad data')
            with self.assertRaisesRegex(ValueError,'part changed'):cloud.publish_parts(iso,out,sha)


if __name__=='__main__':unittest.main()
