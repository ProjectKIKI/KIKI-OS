import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest import mock

import ki2cpu
import ki2release as release
import ki2release_views as views
import ki2ci_ko as ko


class CpuTests(unittest.TestCase):
    def test_isolated_worker_entrypoint_loads_sibling_modules(self):
        result=subprocess.run([sys.executable,'-I','-B',str(Path(release.__file__).resolve()),'--help'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('--cpu-profile',result.stdout)

    def test_legacy_is_unclassified_and_cannot_be_relabelled_v3(self):
        records=[{'arch':'x86_64'}]
        self.assertEqual(ki2cpu.validate_selection('x86_64',records)['level'],'미분류')
        with self.assertRaises(ValueError):ki2cpu.validate_selection('x86-64-v3',records)

    def test_optimized_targets_require_matching_cpu_and_runtime_validation(self):
        records=[{'arch':'x86_64','cpu_profile':'x86-64-v3'}]
        with self.assertRaises(ValueError):ki2cpu.validate_selection('x86-64-v3',records)
        records[0]['cpu_validation']='runtime-verified'
        self.assertEqual(ki2cpu.validate_selection('x86-64-v3',records)['id'],'x86-64-v3')
        with self.assertRaises(ValueError):ki2cpu.validate_selection('x86_64',records)
        records.append({'arch':'x86_64','cpu_profile':'x86-64-v4','cpu_validation':'runtime-verified'})
        with self.assertRaises(ValueError):ki2cpu.validate_selection('x86-64-v3',records)

    def test_empty_or_non_x86_input_does_not_enable_cpu_targets(self):
        for records in [[],[{'arch':'aarch64'}],[{'arch':'noarch'}]]:
            self.assertFalse(any(p['available'] for p in ki2cpu.availability(records)))

    def test_localization_translates_visible_attributes_and_preserves_input_values(self):
        text=ko.localize_html("<input name='pipeline' value='running' aria-label='Follow output'><pre>running</pre>")
        self.assertIn("aria-label='최신 출력 따라가기'",text)
        self.assertIn("value='running'",text)
        self.assertIn('<pre>running</pre>',text)


class VersionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.backend=self.root/'backend';self.backend.mkdir()
        self.base=self.root/'base';(self.base/'recipes').mkdir(parents=True)
        self.lib=release.Library(self.root/'store',self.backend,self.base,self.root/'sources',self.root/'native')
        self.lib.catalog['binaries']['a'*64]={'name':'demo','arch':'x86_64'}
        for name in ['one','two']:
            release.save(self.lib.root/'snapshots'/name/'manifest.json',{'id':name,'packages':{'demo':'a'*64},'validation_scope':'SHA 확인','created_at':'2026-10-25'})

    def submit(self,**kwargs):
        return self.lib.submit('iso',dict(snapshot='one',profile='gnome50',release_version='2026.10-r1',**kwargs))

    def test_version_pins_snapshot_and_repeated_builds_preserve_previous_jobs(self):
        first=self.submit();second=self.submit()
        self.assertNotEqual(first['id'],second['id'])
        self.assertEqual(first['values']['cpu_profile'],'x86_64')
        saved=self.lib.release_versions()[0]
        self.assertEqual(saved['targets']['x86_64']['snapshot'],'one')
        self.assertEqual(saved['targets']['x86_64']['snapshot_manifest_sha256'],release.sha(self.lib.root/'snapshots/one/manifest.json'))
        before=(self.lib.root/'release-versions/2026.10-r1/manifest.json').read_bytes()
        with self.assertRaises(ValueError):self.lib.submit('iso',dict(snapshot='two',profile='gnome50',release_version='2026.10-r1'))
        self.assertEqual((self.lib.root/'release-versions/2026.10-r1/manifest.json').read_bytes(),before)

    def test_same_os_version_can_pin_separate_verified_cpu_variants(self):
        self.submit()
        self.lib.catalog['binaries']['b'*64]={'name':'demo','arch':'x86_64','cpu_profile':'x86-64-v3','cpu_validation':'runtime-verified'}
        release.save(self.lib.root/'snapshots/v3/manifest.json',{'id':'v3','packages':{'demo':'b'*64}})
        self.lib.submit('iso',dict(snapshot='v3',profile='gnome50',release_version='2026.10-r1',cpu_profile='x86-64-v3'))
        pins=self.lib.release_versions()[0]['targets']
        self.assertEqual(pins['x86_64']['snapshot'],'one')
        self.assertEqual(pins['x86-64-v3']['snapshot'],'v3')

    def test_invalid_version_and_unbuilt_cpu_cannot_create_release_records(self):
        with self.assertRaises(ValueError):self.lib.submit('iso',dict(snapshot='one',profile='gnome50',release_version='../escape'))
        with self.assertRaises(ValueError):self.submit(cpu_profile='x86-64-v3')
        self.assertEqual(self.lib.jobs(),[]);self.assertEqual(self.lib.release_versions(),[])

    def test_capacity_failure_does_not_reserve_a_version(self):
        with mock.patch.object(self.lib,'jobs',return_value=[{'status':'running'}]*8):
            with self.assertRaises(ValueError):self.submit()
        self.assertEqual(self.lib.release_versions(),[])

    def test_pending_and_legacy_iso_jobs_render_and_filters_work(self):
        pending=self.submit()
        other=self.lib.submit('iso',dict(snapshot='two',profile='minimal-systemd',release_version='2026.10-r2'))
        text=views.iso_page(self.lib,release.render,{'version':['2026.10-r1']}).decode()
        self.assertIn(pending['id'],text);self.assertNotIn('/iso-build/jobs/'+other['id'],text)
        self.assertIn("value='x86-64-v3' disabled",text)
        legacy={'values':{'snapshot':'old'}}
        self.assertEqual(views.os_version(legacy),'old')

    def test_cpu_status_page_distinguishes_planned_targets(self):
        text=views.cpu_page(self.lib,release.render).decode()
        self.assertIn('ISA 등급',text)
        self.assertIn('대상 패키지·CPU 런타임 검증 대기',text)


if __name__=='__main__':unittest.main()
