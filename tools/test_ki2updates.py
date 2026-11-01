import copy
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import ki2release as core
import ki2upstream as upstream
from ki2updatebuild import digest, read_plan
from test_ki2release import LibraryTests


class UpdateTests(unittest.TestCase):
    package=LibraryTests.package
    def setUp(self):
        LibraryTests.setUp(self)
        self.manager=self.lib.updates;self.manager.recipe_file=self.root/'recipes.json'
        self.raw={'name':'demo','version':'1.0','release':'1','summary':'demo','license':'MIT','architectures':['x86_64'],
                  'source':{'type':'url','url':'https://example.org/demo-1.0.tar.xz','sha256':'a'*64},'dependencies':{'runtime':[],'build':[]},'build':{'system':'gnu'}}
        r=self.lib.build.normalize_recipe(self.raw,Path('fixture.toml'))
        p=self.package(recipe_digest=r.digest)
        self.binary=self.lib.add_binary(p,core.sha(p),'test',self.raw['source'])
        self.lib.snapshot('base',{'demo':core.sha(p)},'fixture')
        core.save(self.manager.recipe_file,{'demo':{'recipe':self.raw,'digest':r.digest}})
        core.save(self.manager.root/'config.json',{'enabled':False,'baseline':'base','vm_profiles':[{'vm_id':'test-vm','profile':'gnome50'}]})

    def proposal(self):
        with mock.patch.object(core,'public_https',side_effect=lambda v:v):
            return self.manager.create({'base':'base','package':'demo','notes':'same source; compatible maintenance rebuild','compatibility':'compatible'})

    def test_same_upstream_version_increments_release_and_pins_baseline(self):
        row=self.proposal()
        self.assertEqual(row['release'],'2');self.assertEqual(row['version'],'1.0')
        self.assertEqual(row['base_manifest_sha256'],core.sha(self.lib.root/'snapshots/base/manifest.json'))
        self.assertFalse((self.manager.root/'stable.json').exists())

    def test_web_metadata_is_captured_in_candidate_without_changing_baseline(self):
        core.save(self.lib.legacy_backend/'build/ki2ci/catalog/current.json',dict(revision=7,metadata={'demo':dict(base_version='1.0',summary='웹 편집 설명',license='BSD-2-Clause',tier='desktop')}))
        row=self.proposal()
        self.assertEqual(row['recipes'][0]['summary'],'웹 편집 설명')
        self.assertEqual(row['release'],'2')
        self.assertEqual(row['web_catalog']['revision'],7)
        self.assertEqual(self.raw['summary'],'demo')

    def test_ki2ctl_update_freezes_authored_group_catalog(self):
        import tarfile
        raw=copy.deepcopy(self.raw);raw.update(name='ki2ctl',source={'type':'local','path':'distro/sources/ki2ctl'},build={'system':'copy'})
        recipe=self.lib.build.normalize_recipe(raw,Path('group-test.json'))
        package=self.package(name='ki2ctl',recipe_digest=recipe.digest)
        binary=self.lib.add_binary(package,core.sha(package),'fixture',raw['source'])
        self.lib.snapshot('group-base',{'ki2ctl':binary['sha256']},'fixture')
        core.save(self.manager.recipe_file,{'ki2ctl':{'recipe':raw}})
        group=dict(schema='ki2-package-groups-v1',groups=[{'id':'authored-group'}],profiles=[])
        path=self.lib.legacy_backend/'build/ki2ci/catalog/current.json'
        core.save(path,dict(revision=5,metadata={},catalog=group))
        source=self.lib.backend/'distro/sources/ki2ctl/usr/share/ki2/package-groups.json'
        core.save(source,{'original':True})
        row=self.manager.create({'base':'group-base','package':'ki2ctl','notes':'Freeze authored package groups','compatibility':'compatible'})
        core.save(path,dict(revision=6,metadata={},catalog={'later':True}))
        with mock.patch.object(self.manager,'enqueue',return_value={}):self.manager.prepare({'values':{'proposal':row['id']}})
        plan=read_plan(self.manager.root/'plans'/(row['id']+'.json'))
        self.assertEqual(plan['web_catalog']['revision'],5)
        with tarfile.open(self.lib.root/'objects'/plan['local_archives'][0]['sha256']) as archive:
            payload=json.load(archive.extractfile('distro/sources/ki2ctl/usr/share/ki2/package-groups.json'))
        self.assertEqual(payload,group)
        self.assertEqual(core.read(source),{'original':True})

    def test_later_candidate_uses_a_new_filename_even_with_the_same_baseline(self):
        existing=dict(self.binary,release='2');self.lib.catalog['binaries']['c'*64]=existing
        self.assertEqual(self.proposal()['release'],'3')

    def test_pending_proposals_reserve_distinct_release_numbers(self):
        self.assertEqual(self.proposal()['release'],'2')
        self.assertEqual(self.proposal()['release'],'3')

    def test_unsupported_staging_recipe_is_not_a_buildable_source(self):
        raw=copy.deepcopy(self.raw);raw['source']={'type':'local','path':'/tmp/unrecorded/dest'}
        recipe=self.lib.build.normalize_recipe(raw,Path('fixture.toml'));p=dict(self.binary,recipe_digest=recipe.digest)
        core.save(self.manager.recipe_file,{'demo':{'recipe':raw}})
        with self.assertRaisesRegex(ValueError,'staging'):self.manager.recipe_for('demo',p)

    def test_kernel_recipe_without_initramfs_pipeline_is_explicitly_blocked(self):
        raw=copy.deepcopy(self.raw);raw['build']['system']='kernel'
        recipe=self.lib.build.normalize_recipe(raw,Path('fixture.toml'));p=dict(self.binary,recipe_digest=recipe.digest)
        core.save(self.manager.recipe_file,{'demo':{'recipe':raw}})
        with self.assertRaisesRegex(ValueError,'initramfs'):self.manager.recipe_for('demo',p)

    def test_reverse_dependency_analysis_is_transitive(self):
        data={n:{'dependencies':{'runtime':deps}} for n,deps in [('lib',[]),('app',['lib']),('desktop',['app']),('other',[])]}
        self.assertEqual(self.manager.affected(data,'lib'),['app','desktop'])

    def test_source_hash_mismatch_never_reaches_build_queue(self):
        row=self.proposal();job=self.lib.submit('update-prepare',{'proposal':row['id']})
        response=io.BytesIO(b'wrong source bytes')
        opener=mock.Mock();opener.open.return_value=response
        with mock.patch.object(core,'public_https',side_effect=lambda v:v),mock.patch('urllib.request.build_opener',return_value=opener):
            with self.assertRaisesRegex(ValueError,'SHA-256'):self.manager.prepare(job)
        self.assertEqual(self.manager.get(row['id'])['status'],'prepare-failed')
        self.assertFalse((self.manager.root/'plans'/(row['id']+'.json')).exists())

    def test_update_requests_share_queue_limits_and_are_deduplicated(self):
        self.lib.submit('update-check',{'base':'base'})
        with self.assertRaisesRegex(ValueError,'같은 요청'):self.lib.submit('update-check',{'base':'base'})

    def test_retry_keeps_frozen_source_bytes_and_does_not_download_again(self):
        row=self.proposal();row['status']='prepare-failed'
        plan={'schema':'ki2-update-build-v1','id':row['id'],'base':'base','base_manifest_sha256':row['base_manifest_sha256'],
              'packages':{'demo':self.binary},'recipes':row['recipes']}
        plan['sha256']=digest(plan);row['plan_sha256']=plan['sha256'];self.manager.save(row)
        path=self.manager.root/'plans'/(row['id']+'.json');core.save(path,plan);before=path.read_bytes()
        with mock.patch.object(self.manager,'enqueue',return_value={'ok':True}) as enqueue,mock.patch('urllib.request.build_opener') as download:
            self.assertEqual(self.manager.prepare({'values':{'proposal':row['id']}}),{'ok':True})
            enqueue.assert_called_once();download.assert_not_called()
        self.assertEqual(path.read_bytes(),before)

    def test_local_auxiliary_inputs_are_frozen_with_the_primary_source(self):
        raw=copy.deepcopy(self.raw);raw['source']={'type':'local','path':'cmd/demo','inputs':['distro/sources/demo']}
        recipe=self.lib.build.normalize_recipe(raw,Path('local.json'));package=self.package(recipe_digest=recipe.digest)
        binary=self.lib.add_binary(package,core.sha(package),'fixture',raw['source'])
        self.lib.snapshot('local-base',{'demo':binary['sha256']},'fixture')
        core.save(self.manager.recipe_file,{'demo':{'recipe':raw}})
        for relative in ['cmd/demo','distro/sources/demo']:
            folder=self.lib.backend/relative;folder.mkdir(parents=True);(folder/'marker').write_text(relative)
        row=self.manager.create({'base':'local-base','package':'demo','notes':'Freeze source and helper together','compatibility':'compatible'})
        with mock.patch.object(self.manager,'enqueue',return_value={}):self.manager.prepare({'values':{'proposal':row['id']}})
        plan=read_plan(self.manager.root/'plans'/(row['id']+'.json'))
        self.assertEqual({a['path'] for a in plan['local_archives']},{'cmd/demo','distro/sources/demo'})
        for entry in plan['local_archives']:
            self.assertTrue((self.lib.root/'objects'/entry['sha256']).is_file())

    def evidence(self,checks=None):
        row=self.proposal();self.lib.snapshot('update-'+row['id'],{'demo':self.binary['sha256']},'fixture candidate')
        folder=self.lib.root/'snapshots'/('update-'+row['id'])
        row.update(status='testing',snapshot=folder.name,plan_sha256='b'*64,candidate_manifest_sha256=core.sha(folder/'manifest.json'),index_sha256=core.sha(folder/'repo/index.x86_64.json'))
        self.manager.save(row);row=self.manager.request_validation(row['id'])
        key=self.root/'validator.key';pub=self.root/'validator.pub'
        subprocess.run(['openssl','genpkey','-algorithm','Ed25519','-out',str(key)],check=True,capture_output=True)
        subprocess.run(['openssl','pkey','-in',str(key),'-pubout','-out',str(pub)],check=True,capture_output=True)
        self.key_patch=mock.patch('ki2updates.Path',wraps=Path)
        # Public key location is operator controlled; patch only that fixed lookup via with_name.
        report={k:row[k] for k in ['plan_sha256','base_manifest_sha256','candidate_manifest_sha256','index_sha256']}
        report.update(proposal=row['id'],nonce=row['validation_nonce'],vm_id='test-vm',profile='gnome50',boot_id_before='old',boot_id_after='new',base_packages={'demo':self.binary['sha256']},packages={'demo':self.binary['sha256']},
                      checks=checks or {k:True for k in ['signature_verified','offline_apply_succeeded','package_inventory','user_config_preserved','services_healthy','rebooted','gnome_session','kernel_recovery']})
        path=self.manager.root/'evidence'/(row['validation_nonce']+'.json');core.save(path,report)
        subprocess.run(['openssl','pkeyutl','-sign','-inkey',str(key),'-rawin','-in',str(path),'-out',str(path.with_suffix('.sig'))],check=True,capture_output=True)
        return row,report,path,pub,key

    def verify_with(self,row,pub,func):
        # Keep real Path behavior everywhere except the verifier public key's sibling lookup.
        original=Path.with_name
        def sibling(p,name):return pub if name=='update-verifier.pub' else original(p,name)
        with mock.patch.object(Path,'with_name',sibling):return func(row['id'])

    def test_valid_signature_is_required_and_bound_to_exact_report_bytes(self):
        row,report,path,pub,key=self.evidence()
        report['nonce']='other';core.save(path,report)
        with self.assertRaisesRegex(ValueError,'서명'):self.verify_with(row,pub,self.manager.accept_validation)
        self.assertFalse(self.manager.stable())

    def test_requested_scap_scan_cannot_be_omitted_from_a_signed_report(self):
        row,report,path,pub,key=self.evidence()
        row['security_policy']={'sha256':'f'*64,'profile':'desktop'};self.manager.save(row)
        with self.assertRaisesRegex(ValueError,'OpenSCAP'):self.verify_with(row,pub,self.manager.accept_validation)

    def test_scap_configuration_failures_remain_visible_in_advisory_mode(self):
        row,report,path,pub,key=self.evidence()
        row['security_policy']={'sha256':'f'*64,'profile':'desktop','rules':['rule1']};self.manager.save(row)
        scan={'status':'completed','policy_sha256':'f'*64,'profile':'desktop','rules':[{'id':'rule1','result':'fail'}],'summary':{'fail':1}}
        report['security']={'before':scan,'after':scan};report['checks']['security_scan_executed']=True
        core.save(path,report);subprocess.run(['openssl','pkeyutl','-sign','-inkey',str(key),'-rawin','-in',str(path),'-out',str(path.with_suffix('.sig'))],check=True,capture_output=True)
        accepted=self.verify_with(row,pub,self.manager.accept_validation)
        self.assertEqual(accepted['validation']['security']['after']['summary']['fail'],1)

    def test_scap_report_with_missing_required_rules_is_rejected(self):
        row,report,path,pub,key=self.evidence()
        row['security_policy']={'sha256':'f'*64,'profile':'desktop','rules':['rule1','rule2']};self.manager.save(row)
        scan={'status':'completed','policy_sha256':'f'*64,'profile':'desktop','rules':[{'id':'rule1','result':'pass'}]}
        report['security']={'before':scan,'after':scan};report['checks']['security_scan_executed']=True
        core.save(path,report);subprocess.run(['openssl','pkeyutl','-sign','-inkey',str(key),'-rawin','-in',str(path),'-out',str(path.with_suffix('.sig'))],check=True,capture_output=True)
        with self.assertRaisesRegex(ValueError,'필수 규칙'):self.verify_with(row,pub,self.manager.accept_validation)

    def test_signed_report_for_another_candidate_is_rejected(self):
        row,report,path,pub,key=self.evidence();report['index_sha256']='c'*64;core.save(path,report)
        subprocess.run(['openssl','pkeyutl','-sign','-inkey',str(key),'-rawin','-in',str(path),'-out',str(path.with_suffix('.sig'))],check=True,capture_output=True)
        with self.assertRaisesRegex(ValueError,'다른 후보'):self.verify_with(row,pub,self.manager.accept_validation)

    def test_only_verified_vm_candidate_can_advance_stable_pointer(self):
        row,report,path,pub,key=self.evidence()
        with self.assertRaisesRegex(ValueError,'먼저'):self.manager.promote({'values':{'proposal':row['id']}})
        self.verify_with(row,pub,self.manager.accept_validation)
        result=self.verify_with(row,pub,lambda key:self.manager.promote({'values':{'proposal':key}}))
        self.assertEqual(self.manager.stable()['version'],row['snapshot']);self.assertEqual(result['channel'],'stable')
        with self.assertRaisesRegex(ValueError,'이미 안정'):self.verify_with(row,pub,self.manager.accept_validation)
        self.assertEqual(self.manager.get(row['id'])['status'],'stable')

    def test_changed_stable_baseline_blocks_stale_candidate(self):
        row,report,path,pub,key=self.evidence();self.verify_with(row,pub,self.manager.accept_validation)
        core.save(self.manager.root/'stable.json',{'version':'another'})
        with self.assertRaisesRegex(ValueError,'안정 채널이 변경'):self.verify_with(row,pub,lambda key:self.manager.promote({'values':{'proposal':key}}))
        self.assertEqual(self.manager.stable()['version'],'another')

    def test_signed_failed_boot_check_cannot_promote(self):
        row,report,path,pub,key=self.evidence({'rebooted':False})
        with self.assertRaises(ValueError):self.verify_with(row,pub,self.manager.accept_validation)
        self.assertFalse(self.manager.stable())

    def test_signed_report_without_offline_completion_cannot_promote(self):
        row,report,path,pub,key=self.evidence();report['checks'].pop('offline_apply_succeeded');core.save(path,report)
        subprocess.run(['openssl','pkeyutl','-sign','-inkey',str(key),'-rawin','-in',str(path),'-out',str(path.with_suffix('.sig'))],check=True,capture_output=True)
        with self.assertRaises(ValueError):self.verify_with(row,pub,self.manager.accept_validation)
        self.assertFalse(self.manager.stable())


class DiscoveryTests(unittest.TestCase):
    def test_numeric_gnome_development_branches_are_not_stable_updates(self):
        source={'name':'gtk+-3','version':'3.24.52','url':'https://download.gnome.org/sources/gtk+/3.24/gtk+-3.24.52.tar.xz'}
        text=json.dumps([4,{'gtk+':{v:{'tar.xz':v+'/gtk+.tar.xz'} for v in ['3.24.53','3.99.5','3.24.90']}}])
        self.assertEqual([r['version'] for r in upstream.releases(source,upstream.provider(source),text)],['3.24.53'])

    def test_gnome_cache_uses_explicit_release_archive_and_excludes_rc(self):
        source={'name':'gtk','version':'4.22.4','url':'https://download.gnome.org/sources/gtk/4.22/gtk-4.22.4.tar.xz'}
        text=json.dumps([4,{'gtk':{'4.22.5':{'tar.xz':'4.22/gtk-4.22.5.tar.xz'},'4.23.rc':{'tar.xz':'4.23/gtk-4.23.rc.tar.xz'},'5.0':{'tar.xz':'5.0/gtk-5.0.tar.xz'}}}])
        result=upstream.releases(source,upstream.provider(source),text)
        self.assertEqual([r['version'] for r in result],['4.22.5'])
        self.assertEqual(result[0]['url'],'https://download.gnome.org/sources/gtk/4.22/gtk-4.22.5.tar.xz')

    def test_fetch_failure_is_not_reported_as_current(self):
        rows=[{'name':'gtk','version':'4.22.4','url':'https://download.gnome.org/sources/gtk/4.22/gtk-4.22.4.tar.xz'},{'name':'local','version':'1','url':''}]
        def fail(url):raise TimeoutError('timeout')
        result={r['name']:r for r in upstream.check_all(rows,lambda u:u,fail)}
        self.assertEqual(result['gtk']['status'],'error');self.assertEqual(result['local']['status'],'manual')

    def test_kernel_monitor_remains_on_current_lts_series(self):
        row={'name':'linux','version':'6.1.187','url':'https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.1.187.tar.xz'}
        text='<a href="linux-6.1.188.tar.xz">new</a><a href="linux-6.18.2.tar.xz">different series</a>'
        result=upstream.releases(row,upstream.provider(row),text)
        self.assertEqual([r['version'] for r in result],['6.1.188'])


if __name__=='__main__':unittest.main()
