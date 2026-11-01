import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
from http.server import ThreadingHTTPServer
import urllib.request
import urllib.error
import urllib.parse
import os
import shutil

import ki2build
import ki2catalog
import ki2ci


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source'
        ki2catalog.atomic(self.source / ki2catalog.GROUP_FILE, dict(schema='ki2-package-groups-v1',
            groups=[dict(id='minimal', name_ko='최소', name_en='Minimal', description_ko='최소 구성', requires=[],
                         packages=dict(mandatory=['demo'], default=[], optional=[]), services=dict(enable=[]))],
            profiles=[dict(id='desktop', name_ko='데스크톱', name_en='Desktop', groups=['minimal'], ai_default='off')]))
        ki2catalog.atomic(self.source / 'distro/recipes/demo.json', {'recipes': [dict(name='demo', version='1.0', release='1',
            summary='Original', license='MIT', source=dict(type='local', path='distro/sources/demo'), build=dict(system='copy'))]})
        payload = self.source / 'distro/sources/demo/usr/share/demo/message'
        payload.parent.mkdir(parents=True)
        payload.write_text('real package payload\n', encoding='utf-8')
        self.store = ki2catalog.Catalog(self.root / 'catalog', self.source, ki2build)

    def group(self, **kwargs):
        form = dict(id='workstation', create='yes', name_ko='워크스테이션', name_en='Workstation', description_ko='개인 개발 환경',
                    requires='minimal', mandatory='', default='', optional='', profiles='desktop', selectable='yes',
                    revision=str(self.store.current()['revision']), reason='테스트 그룹 구성')
        form.update(kwargs)
        return self.store.group(form)

    def meta(self, **kwargs):
        form = dict(name='demo', summary='Edited package', license='BSD-2-Clause', tier='desktop',
                    revision=str(self.store.current()['revision']), reason='패키지 설명 개선')
        form.update(kwargs)
        return self.store.metadata(form)

    def test_group_crud_profile_membership_and_export(self):
        self.group()
        self.assertEqual(self.store.current()['catalog']['profiles'][0]['groups'], ['minimal', 'workstation'])
        self.group(create='no', profiles='', optional='demo')
        self.group(create='no', action='delete')
        self.assertEqual(len(self.store.current()['catalog']['groups']), 1)
        self.assertEqual(len(self.store.current()['history']), 3)
        self.assertTrue((self.store.root / 'revisions/1.json').exists())

    def test_stale_revision_does_not_overwrite(self):
        self.meta()
        with self.assertRaises(ki2catalog.Conflict):
            self.meta(revision='0', summary='Stale writer')
        self.assertEqual(self.store.current()['metadata']['demo']['summary'], 'Edited package')

    def test_rejects_cycles_unknown_packages_duplicates_and_referenced_delete(self):
        for args in [dict(requires='workstation'), dict(mandatory='unknown'), dict(mandatory='demo', optional='demo'), dict(id='../escape'), dict(enable='ssh.service;exec')]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.group(**args)
            self.assertEqual(self.store.current()['revision'], 0)
        with self.assertRaises(ValueError):
            self.store.group(dict(id='minimal', revision='0', reason='삭제 시도 검사', action='delete'))

    def test_freeze_materialize_changes_recipe_digest_and_generated_inputs(self):
        original = ki2build.load_recipes(self.source / 'distro/recipes')['demo']
        self.meta(); self.group()
        pin = self.store.freeze(self.root / 'job')
        state = json.loads((self.root / 'job/catalog.json').read_text(encoding='utf-8'))
        self.meta(summary='Later edit')
        target = self.store.materialize(self.source, self.root / 'frozen', state)
        changed = ki2build.load_recipes(target / 'distro/recipes')['demo']
        self.assertEqual(changed.summary, 'Edited package')
        self.assertEqual(changed.release, '2')
        self.assertNotEqual(changed.digest, original.digest)
        self.assertIn('workstation', (target / 'cmd/kiki-installer-gtk/catalog.generated.h').read_text(encoding='utf-8'))
        self.assertEqual(ki2build.load_recipes(self.source / 'distro/recipes')['demo'].summary, 'Original')
        self.assertEqual(pin['revision'], 2)

    def test_changed_upstream_version_requires_review(self):
        state = self.meta()
        with self.assertRaises(ValueError):
            self.store.apply_metadata(dict(name='demo', version='2.0'), state)

    def test_newer_git_release_is_not_downgraded_by_preserved_metadata(self):
        state=self.meta()
        raw=self.store.apply_metadata(dict(name='demo',version='1.0',release='20'),state)
        self.assertEqual(raw['release'],'21')

    @unittest.skipUnless(os.name == 'posix', 'Linux source symlinks')
    def test_source_snapshot_preserves_links_without_reading_external_targets(self):
        link=self.source/'distro/sources/demo/external'
        link.symlink_to('/unavailable/external-file')
        target=self.store.materialize(self.source,self.root/'links',self.meta())
        self.assertTrue((target/'distro/sources/demo/external').is_symlink())

    def test_reset_keeps_history_and_original_recipe(self):
        self.meta(); self.meta(action='reset')
        self.assertEqual(self.store.current()['metadata'], {})
        self.assertEqual(self.store.current()['revision'], 2)

    def test_restore_deleted_group_as_new_revision(self):
        self.group(profiles='')
        self.group(create='no', action='delete')
        self.store.restore(dict(target='1', revision='2', reason='삭제한 그룹 복구'))
        self.assertIn('workstation', [g['id'] for g in self.store.current()['catalog']['groups']])
        self.assertEqual(self.store.current()['revision'], 3)

    def test_http_forms_save_conflict_and_encoded_text(self):
        config = ki2ci.CiConfig(self.source, self.root / 'ci', 'x86_64', 1, 'test', self.root / 'publish')
        server = ki2ci.BuildServer(config)
        self.addCleanup(server.close)
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), ki2ci.make_handler(server))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True); thread.start()
        self.addCleanup(httpd.server_close); self.addCleanup(httpd.shutdown)
        base = 'http://127.0.0.1:' + str(httpd.server_port)
        for route in ['/package-groups', '/package-groups/edit', '/package-groups/history', '/packages/edit?name=demo', '/api/package-groups']:
            with urllib.request.urlopen(base + route) as response:
                self.assertEqual(response.status, 200)
        fields = dict(name='demo', summary='<script>alert(1)</script>', license='MIT', tier='base', revision='0', reason='메타정보 보안 테스트')
        request = urllib.request.Request(base + '/packages/metadata', urllib.parse.urlencode(fields).encode(), headers={'Content-Type':'application/x-www-form-urlencoded'})
        with urllib.request.urlopen(request) as response:
            self.assertIn(b'&lt;script&gt;', response.read())
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        self.assertEqual(error.exception.code, 409); error.exception.close()

    def test_submitted_job_pins_catalog_before_worker(self):
        config = ki2ci.CiConfig(self.source, self.root / 'ci', 'x86_64', 1, 'test', self.root / 'publish')
        server = ki2ci.BuildServer(config); self.addCleanup(server.close)
        server.catalog.metadata(dict(name='demo', summary='Pinned', license='MIT', tier='base', revision='0', reason='카탈로그 입력 고정'))
        with mock.patch.object(server, '_start_worker'):
            job = server.submit_package('demo', source='preserved')
        self.assertEqual(job['catalog']['revision'], 1)
        self.assertTrue((server.store.jobs_dir / job['id'] / 'catalog.json').exists())
        job.update(status='failed');server.store.write(job)
        (server.store.jobs_dir/job['id']/'catalog.json').write_text('{}',encoding='utf-8')
        with self.assertRaises(ki2ci.CiError):server.retry(job['id'])

    @unittest.skipUnless(os.name == 'posix', 'KI2 payload permissions require Linux')
    def test_real_job_builds_edited_metadata_into_archive(self):
        (self.source / 'tools').mkdir()
        (self.source / 'tools/ki2build.py').write_text("raise RuntimeError('old source engine must not run')\n")
        config = ki2ci.CiConfig(self.source, self.root / 'ci', 'x86_64', 1, 'catalog-test', self.root / 'publish')
        server = ki2ci.BuildServer(config); self.addCleanup(server.close)
        server.catalog.metadata(dict(name='demo', summary='Built web metadata', license='MIT', tier='desktop', revision='0', reason='실제 KI2 생성 검사'))
        with mock.patch.object(server, '_start_worker'):
            job = server.submit_package('demo', source='preserved')
        ki2ci.run_job(config, server.store, job['id'])
        finished = server.store.read(job['id'])
        self.assertEqual(finished['status'], 'succeeded', server.store.log_path(job['id']).read_text())
        package = next((server.store.jobs_dir / job['id'] / 'packages').rglob('*.ki2'))
        manifest = ki2build.read_package_manifest(package)
        self.assertEqual((manifest['summary'], manifest['release']), ('Built web metadata', '2'))

    @unittest.skipUnless(os.name == 'posix', 'KI2 payload permissions require Linux')
    def test_real_ki2ctl_job_bundles_authored_groups(self):
        import tarfile
        recipe_path=self.source/'distro/recipes/demo.json'
        data=json.loads(recipe_path.read_text(encoding='utf-8'))
        data['recipes'][0].update(name='ki2ctl',source={'type':'local','path':'distro/sources/ki2ctl'})
        ki2catalog.atomic(recipe_path,data)
        (self.source/'tools').mkdir()
        shutil.copy2(ki2build.__file__,self.source/'tools/ki2build.py')
        config=ki2ci.CiConfig(self.source,self.root/'ci','x86_64',1,'catalog-test',self.root/'publish')
        server=ki2ci.BuildServer(config);self.addCleanup(server.close)
        self.store=server.catalog;self.group(profiles='')
        with mock.patch.object(server,'_start_worker'):job=server.submit_package('ki2ctl',source='preserved')
        ki2ci.run_job(config,server.store,job['id'])
        self.assertEqual(server.store.read(job['id'])['status'],'succeeded',server.store.log_path(job['id']).read_text())
        package=next((server.store.jobs_dir/job['id']/'packages').rglob('*.ki2'))
        with tarfile.open(package) as archive:
            payload=json.load(archive.extractfile('rootfs/usr/share/ki2/package-groups.json'))
        self.assertIn('workstation',[g['id'] for g in payload['groups']])


if __name__ == '__main__':
    unittest.main()
