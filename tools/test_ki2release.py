import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock

import ki2release as release
import ki2ci_ko as ko
from ki2iso_preserved import preserved_guard


class KoreanTests(unittest.TestCase):
    def test_iso_result_uses_korean_labels_and_keeps_unverified_scope_visible(self):
        r=dict(snapshot='candidate',file='test.iso',bytes=100,sha256='a'*64,media_packages=182,root_regular_files_checked=25597,bios_catalog=True,uefi_catalog=True,fresh_install_tested=False,gdm_login_tested=False,secure_boot_signed=False,validation='SHA 통과')
        result=release.result_panel('iso',r)
        visible=result.split('<details>')[0]
        self.assertIn('GDM/Wayland 로그인</th><td>미검증',visible)
        self.assertIn('Secure Boot 서명</th><td>미서명',visible)
        self.assertNotIn('fresh_install_tested',visible)
        self.assertIn('fresh_install_tested',result)

    def test_candidate_overview_is_distinct_from_old_build_paths(self):
        out=ko.localize_html("<nav></nav><option value='installer-iso'>Installer ISO</option><p>Present:</p><p>Missing:</p>",'/')
        self.assertIn('release-overview',out)
        self.assertIn('기존 빌드 경로 기준',out)
        self.assertNotIn("value='installer-iso'",out)
        self.assertIn('설치됨:',out);self.assertIn('누락됨:',out)

    def test_ui_is_translated_without_modifying_commands_or_log_evidence(self):
        raw="<html lang='en'><head><title>KIKI Build Job</title></head><body><nav>Jobs</nav><h2>Build one KI2 recipe</h2><label>Package</label><button>Build package</button><pre>running package source</pre><code>native-inputs</code></body></html>"
        out=ko.localize_html(raw)
        for text in ['lang=\'ko\'','KIKI 빌드 작업 상세','패키지 빌드 시작','/iso-build']:
            self.assertIn(text,out)
        self.assertIn('<pre>running package source</pre>',out)
        self.assertIn('<code>native-inputs</code>',out)

    def test_api_machine_values_preserved_and_display_labels_added(self):
        result=ko.localize_json({'status':'running','steps':[{'name':'Native candidate: llvm','status':'running','command':['gcc']} ]})
        self.assertEqual(result['status'],'running');self.assertEqual(result['status_label'],'실행 중')
        self.assertEqual(result['steps'][0]['display_name'],'LLVM 네이티브 소스 빌드')
        self.assertEqual(result['steps'][0]['command'],['gcc'])


class LibraryTests(unittest.TestCase):
    def test_native_desktop_uses_current_catalog_and_backend(self):
        import ki2installcatalog
        self.lib.legacy_backend=self.root/'legacy'
        backend,profile,roots=self.lib.iso_inputs('gnome50',{'kiki-desktop-defaults':{}})
        self.assertEqual((backend,profile),(self.backend,'desktop-gnome'))
        self.assertEqual(roots,ki2installcatalog.expand(ki2installcatalog.load(),['desktop-gnome'])['packages'])
        for app in ['gnome-control-center','nautilus','gnome-console']:
            self.assertIn(app,roots)

    def test_preserved_desktop_keeps_original_catalog_and_backend(self):
        self.lib.legacy_backend=self.root/'legacy'
        release.save(self.base/'validation/desktop-root-plan.json',{'order':['old-desktop']})
        backend,profile,roots=self.lib.iso_inputs('gnome50',{})
        self.assertEqual((backend,profile,roots),(self.root/'legacy','gnome50',['old-desktop']))

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.base=self.root/'baseline';(self.base/'recipes').mkdir(parents=True)
        release.save(self.base/'recipes/catalog.json',{'recipes':[]})
        self.backend=self.root/'backend';self.backend.mkdir()
        self.lib=release.Library(self.root/'store',self.backend,self.base,self.root/'sources',self.root/'native')

    def package(self,name='demo',version='1.0',deps=(),recipe_digest=None):
        p=self.root/(name+'-'+version+'-1.x86_64.ki2')
        m={'schema':'ki2-package-v1','name':name,'version':version,'release':'1','arch':'x86_64','dependencies':{'runtime':list(deps),'build':[]},'files':[]}
        if recipe_digest:m['recipe_digest']=recipe_digest
        data=json.dumps(m).encode()
        with tarfile.open(p,'w:gz') as t:
            entry=tarfile.TarInfo('manifest.json');entry.size=len(data);t.addfile(entry,io.BytesIO(data))
        return p

    def test_catalog_recovers_from_empty_primary_and_preserves_evidence(self):
        p=self.package();self.lib.add_binary(p,release.sha(p),'test');self.lib.commit()
        expected=self.lib.catalog
        (self.lib.root/'catalog.json').write_bytes(b'')
        self.assertEqual(release.load_catalog(self.lib.root),expected)
        evidence=list(self.lib.root.glob('catalog.invalid-*.json'))
        self.assertEqual(len(evidence),1);self.assertEqual(evidence[0].read_bytes(),b'')

    def test_corrupt_catalog_without_backup_keeps_objects_and_fails_closed(self):
        p=self.package();self.lib.add_binary(p,release.sha(p),'test')
        (self.lib.root/'catalog.json').write_bytes(b'')
        with self.assertRaises(ValueError):release.load_catalog(self.lib.root)
        self.assertEqual((self.lib.root/'objects'/release.sha(p)).read_bytes(),p.read_bytes())
        self.assertEqual((self.lib.root/'catalog.json').read_bytes(),b'')

    def test_backup_missing_snapshot_package_is_not_accepted(self):
        release.save(self.lib.root/'catalog.last-good.json',self.lib.catalog)
        release.save(self.lib.root/'snapshots/held/manifest.json',{'packages':{'llvm':'a'*64}})
        (self.lib.root/'catalog.json').write_bytes(b'')
        with self.assertRaises(ValueError):release.load_catalog(self.lib.root)
        self.assertEqual((self.lib.root/'catalog.json').read_bytes(),b'')

    def test_unchanged_commit_does_not_rewrite_catalog(self):
        self.lib.commit()
        with mock.patch.object(release,'save',side_effect=AssertionError('unexpected disk write')):
            self.lib.commit()

    def test_atomic_replace_failure_preserves_previous_json(self):
        path=self.lib.root/'test.json';release.save(path,{'previous':True})
        with mock.patch.object(Path,'replace',side_effect=OSError('test interruption')):
            with self.assertRaises(OSError):release.save(path,{'new':True})
        self.assertEqual(release.read(path),{'previous':True})
        self.assertEqual(list(self.lib.root.glob('test.json.*.tmp')),[])

    def test_archive_sha_failure_never_registers_a_binary(self):
        p=self.package()
        with self.assertRaises(ValueError):self.lib.add_binary(p,'0'*64,'test')
        self.assertEqual(self.lib.catalog['binaries'],{})

    def test_multiple_versions_and_content_addressed_copies_preserve_inputs(self):
        for version in ['1.0','2.0']:
            p=self.package(version=version);expected=release.sha(p);mode=p.stat().st_mode
            self.lib.add_binary(p,expected,'test')
            self.assertEqual(p.stat().st_mode,mode);self.assertEqual(release.sha(p),expected)
        self.assertEqual(len(self.lib.catalog['binaries']),2)
        self.assertEqual(len(list((self.lib.root/'objects').iterdir())),2)

    def test_existing_corrupted_object_is_rejected_not_overwritten(self):
        p=self.package();expected=release.sha(p);obj=self.lib.blob(p,expected)
        obj.chmod(0o600);obj.write_bytes(b'corrupt')
        with self.assertRaises(ValueError):self.lib.blob(p,expected)
        self.assertEqual(obj.read_bytes(),b'corrupt')

    def test_dependency_resolution_rejects_missing_supplier_and_cycles(self):
        one={'dependencies':{'runtime':['two']}}
        with self.assertRaises(ValueError):release.closure({'one':one},['one'])
        with self.assertRaises(ValueError):release.closure({'one':one,'two':{'dependencies':{'runtime':['one']}}},['one'])
        self.assertEqual(release.closure({'one':one,'two':{'dependencies':{'runtime':[]}}},['one']),['two','one'])

    def test_snapshot_is_signed_pinned_and_cannot_be_overwritten(self):
        p=self.package();r=self.lib.add_binary(p,release.sha(p),'test')
        result=self.lib.snapshot('test-1',{'demo':r['sha256']},'test')
        self.assertEqual(result['packages']['demo'],r['sha256'])
        directory=self.lib.root/'snapshots/test-1'
        self.assertTrue(self.lib.repo.verify_metadata_file(directory/'repo/metadata.x86_64.json',directory/'candidate.pub'))
        before=(directory/'manifest.json').read_bytes()
        with self.assertRaises(FileExistsError):self.lib.snapshot('test-1',{'demo':r['sha256']},'changed')
        self.assertEqual((directory/'manifest.json').read_bytes(),before)
        with self.assertRaises(ValueError):self.lib.snapshot('../escape',{},'test')

    def test_missing_source_is_not_presented_as_downloadable(self):
        p=self.package();r=self.lib.add_binary(p,release.sha(p),'test',{'url':'https://example.com/demo.tar.gz','sha256':'a'*64})
        self.assertNotIn(r['source']['sha256'],self.lib.catalog['sources'])
        with self.assertRaises(ValueError):self.lib.submit('source',{'binary':'unknown'})

    def test_frozen_toml_sources_work_without_a_catalog_json(self):
        (self.base/'recipes/catalog.json').unlink()
        (self.base/'recipes/demo.toml').write_text('[[recipe]]\nname="demo"\nversion="1.0"\n[recipe.source]\nurl="https://example.com/demo.tar.gz"\nsha256="'+'a'*64+'"\n')
        lib=release.Library(self.root/'other-store',Path(__file__).resolve().parents[1],self.base,self.root/'sources',self.root/'native')
        p=self.package();r=lib.add_binary(p,release.sha(p),'test')
        self.assertEqual(r['source']['sha256'],'a'*64)

    def test_private_network_source_and_insecure_redirect_are_rejected(self):
        with self.assertRaises(ValueError):release.public_https('http://example.com/source.tar.gz')
        with mock.patch.object(release.socket,'getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(ValueError):release.public_https('https://example.com/source.tar.gz')

    def test_iso_cannot_use_unknown_snapshot_or_unreviewed_profile(self):
        with self.assertRaises(ValueError):self.lib.submit('iso',{'snapshot':'missing','profile':'gnome50'})
        (self.lib.root/'snapshots/existing').mkdir();release.save(self.lib.root/'snapshots/existing/manifest.json',{})
        with self.assertRaises(ValueError):self.lib.submit('iso',{'snapshot':'existing','profile':'arbitrary-command'})

    def test_completed_web_package_is_imported_with_runtime_status_unverified(self):
        job=self.backend/'build/ki2ci/jobs/test';(job/'packages').mkdir(parents=True)
        p=self.package();(job/'packages'/p.name).write_bytes(p.read_bytes())
        release.save(job/'metadata.json',{'id':'test','package':'demo','status':'succeeded'})
        self.lib.sync_completed_jobs();r=self.lib.catalog['binaries'][release.sha(p)]
        self.assertIn('런타임 미검증',r['validation'])
        self.lib.sync_completed_jobs();self.assertEqual(len(self.lib.catalog['binaries']),1)

    def test_pinned_installer_exception_does_not_accept_other_hashes(self):
        original=mock.Mock(side_effect=ValueError('name policy'))
        audit=mock.Mock(return_value={'name':'kiki-installer-gtk','errors':[]})
        guard=preserved_guard(original,'preserved.ki2','a'*64,lambda p:'a'*64,audit)
        guard(Path('preserved.ki2'));self.assertEqual(audit.call_count,1)
        with self.assertRaises(ValueError):guard(Path('other.ki2'))
        bad=preserved_guard(original,'preserved.ki2','b'*64,lambda p:'a'*64,audit)
        with self.assertRaises(ValueError):bad(Path('preserved.ki2'))

    def test_git_package_import_uses_its_recipe_and_preserves_commit_provenance(self):
        job=self.backend/'build/ki2ci/jobs/git-job';(job/'packages').mkdir(parents=True)
        p=self.package(recipe_digest='a'*64);(job/'packages'/p.name).write_bytes(p.read_bytes())
        git={'kind':'git','commit':'b'*40,'archive_sha256':'c'*64,'branch':'stage3','remote':'https://example.invalid/kiki.git'}
        release.save(job/'metadata.json',{'id':'git-job','package':'demo','status':'succeeded','source':git})
        recipe=mock.Mock(digest='wrong',source={'type':'url','url':'https://example.invalid/new.tar','sha256':'d'*64})
        with mock.patch.object(self.lib.build,'load_recipes',return_value={'demo':recipe}):
            with self.assertRaisesRegex(ValueError,'지문'):
                self.lib.sync_completed_jobs()
            self.assertEqual(self.lib.catalog['binaries'],{})
            recipe.digest='a'*64
            self.lib.sync_completed_jobs()
        record=self.lib.catalog['binaries'][release.sha(p)]
        self.assertEqual(record['source'],recipe.source)
        self.assertEqual(record['provenance']['git'],git)
        self.assertIn('런타임 미검증',record['validation'])

    def test_snapshot_creation_is_queued_and_rejects_path_traversal(self):
        d=self.lib.root/'snapshots/base';d.mkdir();release.save(d/'manifest.json',{'id':'base'})
        j=self.lib.submit('snapshot',{'base':'base','version':'new-version'})
        self.assertEqual(j['status'],'pending');self.assertFalse((self.lib.root/'snapshots/new-version').exists())
        with self.assertRaises(ValueError):self.lib.submit('snapshot',{'base':'base','version':'../outside'})


if __name__=='__main__':unittest.main()
