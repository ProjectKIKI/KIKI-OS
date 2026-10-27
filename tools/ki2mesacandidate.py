#!/usr/bin/env python3
"""Assemble a separate native graphics candidate; never alter the r6 baseline."""
import argparse
import contextlib
import datetime
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import ki2mesanative as n
from ki2stage3candidate import read_manifest

c=n.c
PRIOR=n.OLD_TARGET/'validated-candidate'

def original_records():
    return {r['name']:dict(r,file=str(PRIOR/'packages/x86_64'/r['file'])) for r in json.loads((PRIOR/'repo/index.x86_64.json').read_text())['packages']}

def rewire():
    records=original_records()
    changes=[]
    for name in ['mutter','kiki-gnome-desktop']:
        old=records[name]
        if c.sha256_file(old['file'])!=old['sha256']:raise ValueError('Old archive changed')
        raw=c.build.read_toml(n.OLD_TARGET/'recipes'/(name+'.toml'))['recipe'][0]
        raw['release']=str(int(raw['release'])+1)
        raw['dependencies']['runtime']=['mesa' if x=='kiki-mesa-bootstrap' else x for x in raw['dependencies']['runtime']]
        payload=c.WORK/'payload'/name
        payload.mkdir(parents=True,exist_ok=False)
        c.build.extract_package_rootfs(Path(old['file']),payload)
        if name=='kiki-gnome-desktop':
            for p in payload.rglob('*.json'):
                text=p.read_text()
                p.write_text(text.replace('kiki-mesa-bootstrap','mesa'))
                data=json.loads(p.read_text())
                data['scope']='Minimum login candidate; GSD schemas only; native Mesa/LLVM software and VM profile; no Xwayland/PipeWire desktop support claim'
                c.save(p,data)
            raw['source']['path']=str(payload)
        with contextlib.redirect_stdout(io.StringIO()):
            c.package(raw,payload,dict(previous_package_sha256=old['sha256'],change='Replace bootstrap runtime dependency with native Mesa',mutter_runtime_payload_unchanged=name=='mutter'))
        if name=='mutter':
            for f in read_manifest(Path(old['file']))['files']:
                if f['type']=='file' and c.sha256_file(payload/f['path'].lstrip('/'))!=f['sha256']:raise ValueError('Unexpected Mutter payload change')
        changes.append(dict(name=name,previous_sha256=old['sha256'],new_release=raw['release']))
    c.save(c.TARGET/'validation/bootstrap-dependency-replacement.json',dict(changes=changes,prior_archives_unchanged=True))
    print('Mutter and desktop metadata repackaged; preserved Mutter payload unchanged',flush=True)

def meta():
    previous=json.loads((c.TARGET/'validation/kiki-gnome-desktop-build.json').read_text())
    raw=c.build.read_toml(c.TARGET/'recipes/kiki-gnome-desktop.toml')['recipe'][0]
    raw['release']=str(int(raw['release'])+1)
    payload=c.WORK/'payload/kiki-gnome-desktop'
    p=payload/'usr/share/kiki/gnome50-candidate.json'
    data=json.loads(p.read_text())
    data['scope']='Minimum login candidate; GSD schemas only; native Mesa/LLVM software and VM profile; no Xwayland/PipeWire desktop support claim'
    c.save(p,data)
    with contextlib.redirect_stdout(io.StringIO()):c.package(raw,payload,dict(previous_candidate_sha256=previous['sha256'],original_r6_sha256=original_records()['kiki-gnome-desktop']['sha256'],change='Describe native Mesa runtime scope accurately'))
    c.save(c.TARGET/'validation/desktop-meta-scope-repair.json',dict(previous_sha256=previous['sha256'],new_release=raw['release'],scope=data['scope']))
    print('Desktop metadata now describes the native Mesa/LLVM profile',flush=True)

def plan():
    records=original_records()
    records.pop('kiki-mesa-bootstrap')
    for name in ['llvm','mesa','mutter','kiki-gnome-desktop']:
        r=json.loads((c.TARGET/'validation'/(name+'-build.json')).read_text())
        records[name]=r
    roots=json.loads((n.OLD_TARGET/'validation/gnome-fresh-install-runtime.json').read_text())['installed_packages']
    roots=sorted(set('mesa' if x=='kiki-mesa-bootstrap' else x for x in roots))
    manifests={};order=[];active=[];errors=[];conflicts=[];owners={}
    def visit(name):
        if name in order:return
        if name in active:raise ValueError('Runtime cycle: '+str(active+[name]))
        if name not in records:raise ValueError('Missing dependency: '+name)
        r=records[name]
        if c.sha256_file(r['file'])!=r['sha256']:raise ValueError('Archive SHA mismatch: '+name)
        m=read_manifest(Path(r['file']));manifests[name]=m
        active.append(name)
        for dep in m.get('dependencies',{}).get('runtime',[]):visit(dep)
        active.pop();order.append(name)
    for name in roots:visit(name)
    for name in order:
        for f in manifests[name]['files']:
            if f['type']=='dir':continue
            if f['path'] in owners:conflicts.append(dict(path=f['path'],owners=[owners[f['path']],name]))
            owners[f['path']]=name
    forbidden={'kiki-mesa-bootstrap','kiki-installer-gtk','kiki-installer-tui','kiki-x11','kiki-x11-runtime','kiki-kmscon'}
    result=dict(roots=roots,order=order,packages=[records[x] for x in order],errors=errors,conflicts=conflicts,installer_bundle_in_target=bool(set(order)&forbidden))
    c.save(c.TARGET/'validation/desktop-root-plan.json',result)
    if conflicts or result['installer_bundle_in_target']:raise ValueError('Invalid native root plan')
    print('Native root plan:',len(order),'packages, SHA/dependency/ownership checks passed',flush=True)
    return result

def root():
    import ki2gnomeroot as r
    result=plan()
    r.assemble(result,c.WORK/'native-root')

def elf():
    import ki2gnomeelfaudit as a
    sys.argv=['elf','--root'];a.main()
    r=json.loads((c.TARGET/'validation/desktop-root-elf-suppliers.json').read_text())
    if r['errors'] or any(r['runtime_additions'].values()):raise ValueError('ELF dependencies must be resolved before promotion')

def probe():
    payload=c.WORK/'lab-probe';payload.mkdir(exist_ok=True)
    binary=payload/'mesa-probe'
    flags=c.environment()
    cmd=['gcc','--sysroot='+str(c.SDK),'-O2','-Wall','-Wextra',str(c.REPO/'tools/kiki_mesa_probe.c'),'-o',str(binary)]
    cmd+=flags['LDFLAGS'].split()+['-lEGL','-lGLESv2','-lgbm','-lm']
    subprocess.run(cmd,check=True)
    target=c.WORK/'native-root'
    (target/'tmp').mkdir(exist_ok=True);shutil.copy2(binary,target/'tmp/mesa-probe')
    result=subprocess.run(['chroot',str(target),'/usr/bin/env','EGL_PLATFORM=surfaceless','LIBGL_ALWAYS_SOFTWARE=1','MESA_SHADER_CACHE_DISABLE=true','/tmp/mesa-probe'],capture_output=True,text=True)
    c.save(c.TARGET/'validation/native-root-rendering.json',dict(exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr,probe_sha256=c.sha256_file(binary),passed=result.returncode==0))
    print(result.stdout,result.stderr,flush=True)
    result.check_returncode()

def media():
    result=plan()
    p=c.WORK/'mesa-lab-media-r1';p.mkdir(exist_ok=False)
    (p/'packages').mkdir()
    records=[]
    for name in ['llvm','mesa','mutter','kiki-gnome-desktop']:
        r=next(x for x in result['packages'] if x['name']==name)
        source=Path(r['file']);dest=p/'packages'/source.name
        shutil.copy2(source,dest)
        if c.sha256_file(dest)!=r['sha256']:raise ValueError('Media archive SHA mismatch')
        records.append(dict(name=name,file='packages/'+source.name,sha256=r['sha256']))
    old=original_records()['kiki-mesa-bootstrap']
    if c.sha256_file(old['file'])!=old['sha256']:raise ValueError('Bootstrap archive changed')
    c.save(p/'old-bootstrap-manifest.json',read_manifest(Path(old['file'])))
    shutil.copy2(c.REPO/'tools/ki2mesa_lab_apply.py',p/'apply.py')
    shutil.copy2(c.REPO/'tools/ki2mesa_vm_report.py',p/'mesa-report.py')
    shutil.copy2(c.REPO/'tools/ki2gnomevmreport.py',p/'session-report.py')
    shutil.copy2(c.WORK/'lab-probe/mesa-probe',p/'mesa-probe')
    native_files=[]
    for name in ['llvm','mesa']:
        r=next(x for x in result['packages'] if x['name']==name)
        native_files+=read_manifest(Path(r['file']))['files']
    c.save(p/'native-files.json',native_files)
    c.save(p/'overlay.json',dict(packages=records,vm_id='a1336b8f-2c95-44b4-b970-bd5f93501073',guest_uuid='597103df-264f-40d3-9ab4-96bdd371c1cf',probe_sha256=c.sha256_file(p/'mesa-probe'),scope='Disposable differencing VM overlay; package manager DB unchanged'))
    iso=c.TARGET/'iso/mesa-native-lab-r1.iso';iso.parent.mkdir(exist_ok=True)
    if iso.exists():raise FileExistsError(iso)
    subprocess.run(['xorriso','-as','mkisofs','-quiet','-R','-J','-V','KIKI_MESA_LAB','-o',str(iso),str(p)],check=True)
    c.save(Path(str(iso)+'.sha256.json'),dict(file=str(iso),sha256=c.sha256_file(iso),bytes=iso.stat().st_size,bootable=False,scope='Disposable Mesa runtime test media'))
    print('Created SHA-checked Mesa lab ISO',flush=True)

def publish():
    import ki2repo
    result=plan()
    runtime_path=c.TARGET/'validation/mesa-vm-runtime.json'
    runtime=json.loads(runtime_path.read_text())
    render=json.loads((c.TARGET/'validation/native-root-rendering.json').read_text())
    elf_report=json.loads((c.TARGET/'validation/desktop-root-elf-suppliers.json').read_text())
    preservation=json.loads((c.TARGET/'validation/preservation-current.json').read_text())
    signatures=json.loads((c.TARGET/'validation/source-signatures.json').read_text())
    if not all([runtime.get('passed'),render.get('passed'),preservation.get('passed'),signatures.get('passed')]):raise ValueError('Runtime/preservation/source gate failed')
    if runtime.get('candidate_plan_sha256')!=c.sha256_file(c.TARGET/'validation/desktop-root-plan.json'):raise ValueError('Runtime plan mismatch')
    audited={r['name']:r['sha256'] for r in elf_report['packages']}
    if elf_report['errors'] or any(elf_report['runtime_additions'].values()):raise ValueError('ELF dependencies unresolved')
    for r in result['packages']:
        if audited.get(r['name'])!=r['sha256']:raise ValueError('Stale ELF report')
    for name in ['llvm','mesa','mutter','kiki-gnome-desktop']:
        r=next(x for x in result['packages'] if x['name']==name)
        loaded=next(x for x in runtime['overlay']['packages'] if x['name']==name)
        if r['sha256']!=loaded['sha256']:raise ValueError('Runtime package mismatch')
        if name in ['llvm','mesa']:
            lock=next(x for x in json.loads((c.TARGET/'source-lock.json').read_text())['sources'] if x['name']==name)
            if r['provenance'].get('native_source_build') is not True or r['provenance'].get('host_libraries_copied') is not False or r['provenance'].get('source_sha256')!=lock['sha256']:raise ValueError('Native source provenance mismatch')
    llvm=next(x for x in result['packages'] if x['name']=='llvm')
    mesa=next(x for x in result['packages'] if x['name']=='mesa')
    if mesa['provenance']['llvm_package_sha256']!=llvm['sha256']:
        compatibility=json.loads((c.TARGET/'validation/llvm-compatibility-layout.json').read_text())
        if compatibility['previous_package_sha256']!=mesa['provenance']['llvm_package_sha256'] or llvm['provenance'].get('previous_candidate_sha256')!=compatibility['previous_package_sha256']:raise ValueError('Mesa build/runtime LLVM provenance diverged')
        actual={f['path']:f for f in read_manifest(Path(llvm['file']))['files']}
        for f in compatibility['regular_files_unchanged']:
            if actual[f['path']].get('sha256')!=f['sha256']:raise ValueError('LLVM runtime code changed after Mesa build')
    records=list(result['packages'])
    for name in ['kiki-installer-gtk','kiki-installer-tui']:records.append(original_records()[name])
    dest=c.TARGET/'validated-candidate';dest.mkdir(exist_ok=False)
    packages=dest/'packages/x86_64';packages.mkdir(parents=True)
    entries=[]
    for r in records:
        src=Path(r['file']);out=packages/src.name
        if c.sha256_file(src)!=r['sha256']:raise ValueError('Archive changed before promotion')
        shutil.copy2(src,out)
        if c.sha256_file(out)!=r['sha256']:raise ValueError('Promoted copy SHA mismatch')
        entries.append(ki2repo.package_entry(out,read_manifest(out)))
    repo=dest/'repo';repo.mkdir();iso=dest/'iso';iso.mkdir()
    now=datetime.datetime.now(datetime.timezone.utc).isoformat()
    ki2repo.write_json(repo/'index.x86_64.json',ki2repo.build_index(sorted(entries,key=lambda x:x['name']),'x86_64',now))
    metadata=ki2repo.build_metadata(name='kiki-mesa-native-candidate',title='KIKI native Mesa GDM/Wayland candidate',description='Native Mesa and LLVM source build verified in clean root and isolated differencing VM; preserved installer frontend; fresh installation of this revision not tested',channel='candidate',arch='x86_64',base_url='',created_at=now,repo_dir=repo,packages_dir=packages,iso_dir=iso,packages=entries)
    ki2repo.write_json(repo/'metadata.x86_64.json',metadata)
    keys=c.WORK/'candidate-keys';keys.mkdir(exist_ok=True)
    key=keys/'mesa-native.ed25519'
    if not key.exists():
        subprocess.run(['openssl','genpkey','-algorithm','Ed25519','-out',str(key)],check=True);key.chmod(0o600)
    public=dest/'mesa-native.ed25519.pub'
    subprocess.run(['openssl','pkey','-in',str(key),'-pubout','-out',str(public)],check=True)
    ki2repo.sign_metadata_file(repo/'metadata.x86_64.json',key)
    if not ki2repo.verify_metadata_file(repo/'metadata.x86_64.json',public):raise ValueError('Candidate signature verification failed')
    gate=dict(candidate_runtime_passed=True,release_ready=False,package_count=len(entries),native_root_packages=len(result['order']),index_sha256=c.sha256_file(repo/'index.x86_64.json'),metadata_sha256=c.sha256_file(repo/'metadata.x86_64.json'),signature='Ed25519 separate candidate-only key',public_key_sha256=c.sha256_file(public),fresh_install_tested=False,gtk_frontend_preserved=True,bootstrap_in_target=False,mesa_source_build=True,llvm_source_build=True,vm_runtime_report_sha256=c.sha256_file(runtime_path),physical_gpu_tested=False,vulkan_enabled=False)
    c.save(c.TARGET/'gate.json',gate);c.save(dest/'validation.json',gate)
    shutil.copy2(runtime_path,dest/'runtime.json')
    print('Signed native Mesa candidate published:',len(entries),'archives; fresh install not claimed',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['rewire','meta','plan','root','elf','probe','media','publish']);a=p.parse_args();globals()[a.action]()
