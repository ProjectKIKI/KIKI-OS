import copy
import json
from pathlib import Path
import tempfile
import unittest
import threading
import urllib.request
from http.server import ThreadingHTTPServer
import ki2build
import ki2sources


class SourceManifestTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(__file__).resolve().parents[1]
        self.manifest=json.loads((self.root/ki2sources.DEFAULT).read_text(encoding='utf-8'))

    def test_complete_real_release_and_catalog(self):
        result=ki2sources.validate(self.root,self.manifest)
        self.assertEqual(result['packages'],231)
        self.assertEqual(result['recorded_recipes'],231)
        self.assertGreater(result['bootstrap'],0)
        recipes=ki2build.load_recipes(self.root/'distro/recipes')
        self.assertEqual(ki2build.validate_recipes(recipes,'x86_64',None,512),[])

    def test_missing_package_or_runtime_dependency_is_rejected(self):
        for mutation in ['package','dependency','identity']:
            manifest=copy.deepcopy(self.manifest)
            if mutation=='package':manifest['packages'].pop('glibc')
            elif mutation=='dependency':manifest['packages']['nautilus']['dependencies']['runtime'].append('missing-source-package')
            else:manifest['packages']['nautilus']['sha256']='a'*64
            with self.assertRaises(ValueError):ki2sources.validate(self.root,manifest)

    def test_changed_recipe_or_pipeline_and_unsafe_url_are_rejected(self):
        for mutation in ['recipe','pipeline','url']:
            manifest=copy.deepcopy(self.manifest)
            if mutation=='recipe':manifest['packages']['nautilus']['recorded_recipe']['sha256']='a'*64
            elif mutation=='pipeline':manifest['build_inputs']['tools/gnome_native/context.py']='a'*64
            else:manifest['packages']['nautilus']['source']['url']='https://localhost/private'
            with self.assertRaises(ValueError):ki2sources.validate(self.root,manifest)

    def test_missing_or_changed_source_archives_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'source archive'):
                ki2sources.validate(self.root,self.manifest,object_roots=[tmp])

    def test_paths_and_page_cannot_escape_or_execute(self):
        for value in ['../outside','/etc/passwd','C:/outside','a\\b','tools/../LICENSE']:
            with self.assertRaises(ValueError):ki2sources.local(self.root,value)
        self.manifest['packages']['nautilus']['provenance_note']='<script>alert(1)</script>'
        page=ki2sources.page(self.manifest)
        self.assertNotIn('<script>',page)
        self.assertIn('&lt;script&gt;',page)

    def test_staged_native_outputs_never_masquerade_as_source_builds(self):
        recipe=ki2build.load_recipes(self.root/'distro/recipes')['nautilus']
        self.assertEqual(recipe.source['type'],'url')
        with self.assertRaisesRegex(ki2build.Ki2Error,'native SDK pipeline'):
            ki2build.default_commands(recipe,{})
        import ki2ci
        with tempfile.TemporaryDirectory() as tmp:
            config=ki2ci.CiConfig(self.root,Path(tmp),'x86_64',1,'source-test',Path(tmp)/'publish')
            with self.assertRaisesRegex(ki2ci.CiError,'native SDK'):
                ki2ci.validate_package(config,'nautilus')

    def test_source_page_and_json_are_served_from_configured_repository(self):
        import ki2ci
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp);config=ki2ci.CiConfig(self.root,state,'x86_64',1,'source-test',state/'publish')
            server=ki2ci.BuildServer(config)
            http=ThreadingHTTPServer(('127.0.0.1',0),ki2ci.make_handler(server))
            thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
            try:
                base='http://127.0.0.1:'+str(http.server_port)
                with urllib.request.urlopen(base+'/source-manifest',timeout=5) as r:
                    self.assertIn('릴리즈 전체 소스 명세',r.read().decode())
                with urllib.request.urlopen(base+'/api/source-manifest',timeout=5) as r:
                    self.assertEqual(len(json.load(r)['packages']),231)
            finally:http.shutdown();http.server_close();server.close();thread.join(timeout=2)


if __name__=='__main__':unittest.main()
