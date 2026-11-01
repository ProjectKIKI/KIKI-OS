import json,os,tempfile,unittest
import subprocess,sys,socket,time,urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import ki2build as build
import ki2installcatalog as catalog
import ki2assistant as assistant
import ki2artifacts

class BuildV1Tests(unittest.TestCase):
    def test_profile_validation_is_scoped_and_full_audit_still_rejects_unfinished_recipes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);recipes=root/'distro/recipes';recipes.mkdir(parents=True)
            raw=[dict(name='reviewed',version='1',summary='Good',license='MIT'),dict(name='unfinished',version='1',summary='Draft',license='MIT',dependencies={'build':['not-yet-added']})]
            (recipes/'catalog.json').write_text(json.dumps({'recipes':raw}));profile=root/'profile.json';profile.write_text(json.dumps({'name':'reviewed','arch':'x86_64','packages':['reviewed']}))
            command=[sys.executable,str(Path(build.__file__)),'--repo-root',str(root),'validate']
            scoped=subprocess.run(command+['--profile',str(profile)],capture_output=True,text=True);self.assertEqual(scoped.returncode,0,scoped.stderr)
            full=subprocess.run(command,capture_output=True,text=True);self.assertNotEqual(full.returncode,0);self.assertIn('unknown build dependency',full.stderr)

    @unittest.skipUnless(os.name=='posix','Unix SIGTERM lifecycle')
    def test_fresh_daemon_handles_sigterm_and_releases_builder_lease(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
            process=subprocess.Popen([sys.executable,str(Path(__file__).with_name('ki2ci.py')),'serve','--host','127.0.0.1','--port',str(port),'--repo-root',str(root),'--artifact-root',str(root/'state')],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            try:
                ready=False
                for _ in range(50):
                    try:
                        with urllib.request.urlopen('http://127.0.0.1:'+str(port)+'/api/build-health',timeout=.2) as response:self.assertTrue(json.load(response)['ok']);ready=True;break
                    except OSError:time.sleep(.1)
                self.assertTrue(ready)
                process.terminate();_,error=process.communicate(timeout=5);self.assertEqual(process.returncode,0,error.decode())
                import ki2ci
                lease=ki2ci.BuilderLease(root/'state');lease.close()
            finally:
                if process.poll() is None:process.kill();process.communicate()

    def test_package_archive_is_reproducible_with_fixed_epoch_across_clean_directories(self):
        recipe=build.normalize_recipe(dict(name='repro-doc',version='1',summary='Repro test',license='MIT'),Path('fixture.json'))
        with tempfile.TemporaryDirectory() as temp,mock.patch.dict(os.environ,SOURCE_DATE_EPOCH='1793404800'):
            root=Path(temp);hashes=[]
            for n in range(2):
                dest=root/str(n);file=dest/'usr/share/doc/repro/README';file.parent.mkdir(parents=True);file.write_text('Identical clean source\n');os.utime(file,(100+n,100+n))
                output=root/('different-filename-'+str(n)+'.ki2');build.create_package(SimpleNamespace(arch='x86_64'),recipe,dest,output,'fixed-input',{})
                hashes.append(build.file_sha256(output))
            self.assertEqual(hashes[0],hashes[1])

    def test_vm_groups_preserve_graphical_target_and_enable_only_matching_agents(self):
        data=catalog.load()
        for group,unit in [('vm-kvm','qemu-guest-agent.service'),('vm-hyperv','hv-kvp-daemon.service')]:
            selected=catalog.expand(data,['desktop-gnome',group]);self.assertEqual(selected['default_target'],'graphical.target');self.assertIn(unit,selected['enable']);self.assertIn('kiki-vm-tools',selected['packages'])
            self.assertNotIn('hv-fcopy-daemon.service',selected['enable'])

    def test_quoted_secret_is_fully_removed(self):
        clean,count=assistant.redact('password="secret with spaces"\nerror: missing libfoo.so')
        self.assertEqual(count,1);self.assertNotIn('with spaces',clean);self.assertIn('missing libfoo.so',clean)

    def test_artifacts_distinguish_built_iso_from_verified_install(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);job=dict(id='a'*32,kind='iso',status='succeeded',values={'release_version':'test'},result={'file':'test.iso','sha256':'b'*64,'bytes':100,'fresh_install_tested':False})
            lib=SimpleNamespace(root=root,backend=root/'backend',legacy_backend=root/'legacy',catalog={'binaries':{},'sources':{}},jobs=lambda:[job])
            row=ki2artifacts.inventory(lib)['items'][0];self.assertIn('설치 검증 대기',row['validation'])
            directory=root/'jobs'/job['id'];directory.mkdir(parents=True);(directory/'cloud-deploy.json').write_text('{"status":"passed"}')
            job['result']['fresh_install_tested']=True;row=ki2artifacts.inventory(lib)['items'][0];self.assertEqual(row['validation'],'설치 검증 통과')
            html=ki2artifacts.page(lib,lambda title,body:body,dict(q=['test.iso'],kind=['iso'],page=['bad']))
            self.assertIn('1개 검색 결과',html);self.assertIn('1 / 1 페이지',html);self.assertIn('VM 보고서',html)
            empty=ki2artifacts.page(lib,lambda title,body:body,dict(q=['absent']))
            self.assertIn('검색 결과가 없습니다',empty)

if __name__=='__main__':unittest.main()
