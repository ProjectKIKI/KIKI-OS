import http.client
from http.server import ThreadingHTTPServer
import io
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import threading
import unittest
from urllib.parse import urlencode

import ki2ci_auth as auth
import ki2release as core
import ki2releases_views as pages


@unittest.skipUnless(shutil.which('openssl'),'OpenSSL is required for real signed snapshot fixtures')
class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.base=self.root/'baseline';(self.base/'recipes').mkdir(parents=True)
        core.save(self.base/'validation/desktop-root-plan.json',{'order':['demo']})
        backend=self.root/'backend';backend.mkdir()
        self.lib=core.Library(self.root/'store',backend,self.base,self.root/'sources',self.root/'native')
        self.manager=self.lib.releases;self.records={}
        for name,version,deps in [('demo','1.0',[]),('demo','2.0',[]),('linux','6.1.187',[]),('kiki-installer-gtk','0.1',['demo']),('addon','1.0',['demo'])]:
            record=self.package(name,version,deps);self.records[name+'-'+version]=record
        self.selection={n:self.records[k]['sha256'] for n,k in [('demo','demo-1.0'),('linux','linux-6.1.187'),('kiki-installer-gtk','kiki-installer-gtk-0.1')]}
        self.lib.snapshot('base',self.selection,'SHA fixture');self.lib.commit()

    def package(self,name,version,deps):
        path=self.root/(name+'-'+version+'-1.x86_64.ki2')
        manifest={'schema':'ki2-package-v1','name':name,'version':version,'release':'1','arch':'x86_64','dependencies':{'runtime':deps,'build':[]},'files':[]}
        data=json.dumps(manifest).encode()
        with tarfile.open(path,'w:gz') as archive:
            item=tarfile.TarInfo('manifest.json');item.size=len(data);archive.addfile(item,io.BytesIO(data))
        return self.lib.add_binary(path,core.sha(path),'fixture SHA · 런타임 미검증')

    def register(self,name='r1',base='base',changes=None):
        job=self.lib.submit('release',dict(release_version=name,base=base,cpu_profile='x86_64',profile='gnome50',changes=changes or {}))
        result=self.manager.register_job(job);self.lib.update(job,status='succeeded',result=result)
        return result

    def legacy(self,name='base'):
        job={'id':'a'*32,'kind':'iso','status':'succeeded','phase':'완료','created_at':core.now(),'values':{'snapshot':name,'profile':'gnome50'},'result':{'file':'legacy.iso','sha256':'f'*64}}
        self.lib.update(job);(self.lib.root/'jobs'/job['id']/'log.txt').write_text('')
        return job

    def test_legacy_inventory_is_read_only_and_keeps_iso_membership(self):
        job=self.legacy();before=(self.lib.root/'snapshots/base/manifest.json').read_bytes()
        self.assertEqual(self.manager.list()[0]['state'],'legacy')
        self.assertEqual(self.manager.isos('base')[0]['id'],job['id'])
        self.assertIn('demo',self.manager.packages('base','x86_64')[1])
        self.assertFalse(self.manager.version_path('base').exists());self.assertFalse(self.manager.metadata_path('base').exists())
        self.assertEqual((self.lib.root/'snapshots/base/manifest.json').read_bytes(),before)
        with self.assertRaises(ValueError):self.manager.manage('base','archive',0)

    def test_changed_package_creates_new_signed_snapshot_and_preserves_originals(self):
        before=(self.lib.root/'snapshots/base/manifest.json').read_bytes()
        result=self.register(changes={'demo':self.records['demo-2.0']['sha256']})
        self.assertEqual(result['changed_packages'],1);self.assertNotEqual(result['snapshot'],'base')
        snapshot,records=self.manager.packages('r1','x86_64')
        self.assertEqual(records['demo']['version'],'2.0')
        path=self.lib.root/'snapshots'/snapshot['id']
        self.assertTrue(self.lib.repo.verify_metadata_file(path/'repo/metadata.x86_64.json',path/'candidate.pub'))
        self.assertEqual((self.lib.root/'snapshots/base/manifest.json').read_bytes(),before)
        for record in self.records.values():self.assertEqual(core.sha(self.lib.root/'objects'/record['sha256']),record['sha256'])

    def test_existing_release_cpu_cannot_be_replaced(self):
        self.register();before=self.manager.version_path('r1').read_bytes()
        with self.assertRaises(ValueError):self.register(changes={'demo':self.records['demo-2.0']['sha256']})
        self.assertEqual(self.manager.version_path('r1').read_bytes(),before)

    def test_invalid_package_graph_cpu_and_paths_create_no_version(self):
        variants=[{'release_version':'../bad'},{'changes':{'linux':''}},{'changes':{'demo':''}},
                  {'changes':{'demo':'0'*64}},{'changes':{'wrong':self.records['demo-2.0']['sha256']}},
                  {'changes':'[]'},{'cpu_profile':'x86-64-v3'}]
        for extra in variants:
            values=dict(release_version='bad',base='base',cpu_profile='x86_64',profile='gnome50');values.update(extra)
            with self.subTest(extra=extra),self.assertRaises((ValueError,FileNotFoundError)):self.lib.submit('release',values)
        self.assertEqual(self.lib.release_versions(),[]);self.assertEqual(self.lib.jobs(),[])
        for reserved in ['new','register']:
            with self.assertRaises(ValueError):self.lib.submit('iso',dict(release_version=reserved,snapshot='base',profile='gnome50'))
            self.assertFalse(self.manager.version_path(reserved).exists())

    def test_pending_registration_reserves_name_and_blocks_iso_race(self):
        values=dict(release_version='r1',base='base',profile='gnome50',cpu_profile='x86_64')
        self.lib.submit('release',values)
        with self.assertRaises(ValueError):self.lib.submit('release',values)
        with self.assertRaises(ValueError):self.lib.submit('iso',dict(release_version='r1',snapshot='base',profile='gnome50'))
        self.assertFalse(self.manager.version_path('r1').exists())

    def test_queue_capacity_failure_does_not_register_release(self):
        from unittest import mock
        with mock.patch.object(self.lib,'jobs',return_value=[{'id':'x','kind':'sync','status':'running','values':{}}]*8):
            with self.assertRaises(ValueError):self.lib.submit('release',dict(release_version='r1',base='base',profile='gnome50'))
        self.assertEqual(self.lib.release_versions(),[])

    def test_lock_archive_restore_and_revision_guard_keep_pin_bytes(self):
        self.register();before=self.manager.version_path('r1').read_bytes()
        self.manager.manage('r1','lock',1)
        with self.assertRaises(ValueError):self.manager.manage('r1','archive',1)
        self.manager.manage('r1','archive',2)
        with self.assertRaises(ValueError):self.lib.submit('iso',dict(release_version='r1',snapshot='base',profile='gnome50'))
        self.assertIn('demo',self.manager.manifest('r1')['targets']['x86_64']['packages'])
        self.manager.manage('r1','edit',3,'메모 제목','보관 중 메모 수정')
        self.assertEqual(self.manager.manage('r1','restore',4)['state'],'locked')
        self.assertEqual(self.manager.manage('r1','unlock',5)['state'],'candidate')
        self.assertEqual(self.manager.version_path('r1').read_bytes(),before)
        self.assertEqual(len(self.manager.get('r1')['history']),6)

    def test_lifecycle_change_cannot_interrupt_iso_job(self):
        self.register();self.lib.submit('iso',dict(release_version='r1',snapshot='base',profile='gnome50'))
        with self.assertRaises(ValueError):self.manager.manage('r1','archive',1)
        self.assertEqual(self.manager.get('r1')['state'],'candidate')

    def test_comparison_detects_replacements_additions_and_exclusions(self):
        first=self.register('r1',changes={'addon':self.records['addon-1.0']['sha256']})
        self.register('r2',changes={'demo':self.records['demo-2.0']['sha256']})
        rows={r['package']:r['kind'] for r in self.manager.compare('r2','r1','x86_64')}
        self.assertEqual(rows,{'addon':'제외','demo':'교체'})
        self.assertEqual({r['package']:r['kind'] for r in self.manager.compare('r1','r2','x86_64')},{'addon':'추가','demo':'교체'})
        self.assertNotEqual(first['snapshot'],'base')

    def test_legacy_adoption_cannot_relabel_old_iso_package_set(self):
        self.legacy()
        with self.assertRaises(ValueError):self.register('base',changes={'demo':self.records['demo-2.0']['sha256']})
        self.register('base');self.assertEqual(self.manager.get('base')['state'],'candidate')
        self.assertEqual(len(self.manager.isos('base')),1)

    def test_tampered_snapshot_is_rejected_by_inventory_and_registration(self):
        self.register()
        job=self.lib.submit('release',dict(release_version='r2',base='base',profile='gnome50'))
        path=self.lib.root/'snapshots/base/manifest.json';value=core.read(path);value['kernel']='changed';core.save(path,value)
        with self.assertRaises(ValueError):self.manager.packages('r1','x86_64')
        with self.assertRaises(ValueError):self.manager.register_job(job)
        self.assertFalse(self.manager.version_path('r2').exists())

    def test_views_escape_notes_include_pinned_packages_isos_and_archive_rules(self):
        self.register();self.manager.manage('r1','edit',1,'<script>title</script>','<img onerror=alert(1)>')
        for tab in ['summary','packages','isos','settings','compare']:
            body=pages.detail(self.manager,core.render,'r1',{'tab':[tab]}).decode()
            self.assertNotIn('<script>title</script>',body);self.assertIn('&lt;script&gt;title&lt;/script&gt;',body)
        self.assertIn('data-release-packages',pages.new(self.manager,core.render,{}).decode())
        self.manager.manage('r1','archive',2)
        body=pages.detail(self.manager,core.render,'r1',{'tab':['isos']}).decode()
        self.assertNotIn('이 릴리즈의 ISO 생성</button>',body);self.assertIn('기존 다운로드는 유지',body)

    def test_real_gateway_routes_and_csrf_for_release_management(self):
        self.register()
        worker=ThreadingHTTPServer(('127.0.0.1',0),core.make_handler(self.lib))
        thread=threading.Thread(target=worker.serve_forever,daemon=True);thread.start()
        self.addCleanup(lambda:(worker.shutdown(),worker.server_close(),thread.join()))
        store=auth.AuthStore(self.root/'test-auth');store.bootstrap()
        store.setup((store.root/'setup-code').read_text().strip(),'qa','Synthetic gateway test password!')
        token,session=store.new_session('qa')
        url='http://127.0.0.1:'+str(worker.server_port)
        gateway=auth.AuthHTTPServer(('127.0.0.1',0),auth.make_handler(store,url,['http://localhost:18090'],release_upstream=url))
        gt=threading.Thread(target=gateway.serve_forever,daemon=True);gt.start()
        self.addCleanup(lambda:(gateway.shutdown(),gateway.server_close(),gt.join()))
        def request(path,data=None,authenticated=True,origin='http://localhost:18090'):
            headers={'Host':'localhost:18090'}
            if authenticated:headers['Cookie']=auth.COOKIE+'='+token
            if data is not None:headers.update({'Origin':origin,'Content-Type':'application/x-www-form-urlencoded'});data=urlencode(data)
            connection=http.client.HTTPConnection('127.0.0.1',gateway.server_port)
            connection.request('POST' if data is not None else 'GET',path,body=data,headers=headers)
            response=connection.getresponse();result=(response.status,response.read(),dict(response.getheaders()));connection.close();return result
        self.assertEqual(request('/releases',authenticated=False)[0],303)
        self.assertIn('릴리즈 관리'.encode(),request('/releases')[1])
        self.assertIn('r1-release.json',request('/releases/r1/manifest')[2]['Content-Disposition'])
        values={'action':'edit','revision':'1','title':'운영 후보','notes':'긴 한글 메모 '*1500,'_csrf':session['csrf']}
        self.assertGreater(len(urlencode(values)),32768)
        self.assertEqual(request('/releases/r1/manage',dict(values,_csrf='wrong'))[0],403)
        self.assertEqual(request('/releases/r1/manage',values,origin='http://other.test')[0],403)
        # Oversized notes reach application validation without weakening other form limits.
        self.assertEqual(request('/releases/r1/manage',values)[0],400)
        values['notes']='긴 한글 메모 '*800
        self.assertEqual(request('/releases/r1/manage',values)[0],303)
        self.assertEqual(self.manager.get('r1')['title'],'운영 후보')


if __name__=='__main__':unittest.main()
