import json
import os
from pathlib import Path
import unittest
from unittest import mock
import ki2ci
import ki2catalog
import ki2build
import test_ki2catalog as fixtures


class NewRecipeTests(unittest.TestCase):
    setUp=fixtures.CatalogTests.setUp

    def register(self,**patch):
        form=dict(name='demo-docs',version='1.0.0',summary='New documentation',license='MIT',tier='extra',arch='all',
                  kind='documentation',content='Real newly registered package payload',reason='새 레시피 등록 시험',revision=str(self.store.current()['revision']))
        form.update(patch);return self.store.register(form)

    def test_preview_does_not_save_and_new_recipe_can_join_a_group(self):
        draft=self.register(action='preview');self.assertIn('demo-docs',draft['recipes']);self.assertEqual(self.store.current()['revision'],0)
        self.register();form=dict(id='documentation',create='yes',name_ko='문서',name_en='Docs',description_ko='등록 패키지 그룹',mandatory='demo-docs',selectable='yes',revision='1',reason='새 문서 그룹 시험')
        self.store.group(form);self.assertIn('demo-docs',self.store.known_packages())
        reopened=ki2catalog.Catalog(self.store.root,self.source,ki2build)
        self.assertIn('demo-docs',reopened.recipes())

    def test_duplicate_bad_sources_and_unknown_dependencies_do_not_save(self):
        for patch in [dict(name='../bad'),dict(runtime_dependencies='unknown'),dict(name='demo'),dict(kind='source',url='http://localhost/source.tar',sha256='a'*64),dict(kind='source',url='https://example.com/file.tar',sha256='TODO')]:
            with self.subTest(patch=patch),self.assertRaises(ValueError):self.register(**patch)
            self.assertEqual(self.store.current()['revision'],0)
        self.register()
        with self.assertRaises(ValueError):self.register()

    @unittest.skipUnless(os.name=='posix','real KI2 permissions require Linux')
    def test_real_new_package_build_uses_pinned_draft_and_input_manifest(self):
        (self.source/'tools').mkdir();(self.source/'tools/ki2build.py').write_text("raise RuntimeError('legacy engine must not run')\n")
        config=ki2ci.CiConfig(self.source,self.root/'ci','x86_64',1,'v1-test',self.root/'publish')
        server=ki2ci.BuildServer(config);self.addCleanup(server.close);self.store=server.catalog
        self.register()
        with mock.patch.object(server,'_start_worker'):job=server.submit_package('demo-docs',source='preserved')
        self.store.metadata(dict(name='demo-docs',summary='Later edit',license='MIT',tier='extra',revision='1',reason='실행 후 메타 변경'))
        ki2ci.run_job(config,server.store,job['id']);result=server.store.read(job['id'])
        self.assertEqual(result['status'],'succeeded',server.store.log_path(job['id']).read_text())
        package=next((server.store.jobs_dir/job['id']/'packages').rglob('*.ki2'));manifest=ki2build.read_package_manifest(package)
        self.assertEqual(manifest['summary'],'New documentation')
        self.assertEqual(manifest['name'],'demo-docs')
        inputs=server.store.jobs_dir/job['id']/'build-inputs.json';self.assertEqual(ki2ci.ki2buildops.sha(inputs),result['input_manifest_sha256'])
        self.assertIn('demo-docs',json.loads(inputs.read_text())['recipe_digests'])


if __name__=='__main__':unittest.main()
