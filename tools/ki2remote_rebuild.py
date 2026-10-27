#!/usr/bin/env python3
"""Rebuild the locked native Mesa candidate inside the isolated build container."""
import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

import ki2sessioncandidate as c
from ki2stage3candidate import read_manifest

REPO = Path('/work')
WORK = Path('/candidate-work')
BASE = Path('/inputs/baseline')
TARGET = REPO / 'build/mesa-native-20261023'
VENV = Path('/opt/kiki-host/venv')
c.REPO, c.WORK, c.SDK, c.TARGET, c.VENV, c.BASE = REPO, WORK, WORK/'sdk', TARGET, VENV, BASE


def load(path):
    return json.loads(Path(path).read_text())


def save(name, value):
    c.save(TARGET/'validation'/name, value)


def env():
    return dict(c.environment(), TMPDIR=str(WORK/'tmp'),
                PATH=str(WORK/'host-tools/bin')+':'+str(VENV/'bin')+':/usr/bin:/bin:/usr/sbin')


def run(command, log, extra=None):
    print('RUN', ' '.join(map(str, command)), flush=True)
    with (TARGET/'validation'/log).open('ab') as stream:
        stream.write(('\n$ '+' '.join(map(str, command))+'\n').encode()); stream.flush()
        process=subprocess.Popen(list(map(str, command)),env=dict(env(), **(extra or {})),
                                 stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace')
        for line in process.stdout:
            stream.write(line.encode());stream.flush();print(line,end='',flush=True)
        if process.wait():raise subprocess.CalledProcessError(process.returncode,command)


def records():
    index=load(BASE/'validated-candidate/repo/index.x86_64.json')
    return {r['name']:dict(r, file=str(BASE/'validated-candidate/packages/x86_64'/r['file'])) for r in index['packages']}


def verify():
    TARGET.mkdir(parents=True, exist_ok=True)
    (TARGET/'validation').mkdir(exist_ok=True)
    assert WORK.is_dir() and c.SDK.is_dir()
    checked=[]
    for name,r in records().items():
        assert c.sha256_file(r['file'])==r['sha256'], name
        m=read_manifest(Path(r['file'])); assert m['name']==name
        checked.append(dict(name=name,sha256=r['sha256']))
    sources=[]
    for r in load(BASE/'source-lock.json')['sources']:
        p=WORK/'sources'/Path(r['file']).name
        assert c.sha256_file(p)==r['sha256'], str(p)
        sources.append(dict(name=r['name'],file=str(p),sha256=r['sha256']))
    gpg=WORK/'gpg';gpg.mkdir(mode=0o700,exist_ok=True)
    signatures=[]
    for name,archive,key,fpr in [
        ('mesa','mesa-25.2.7.tar.xz','mesa-release-maintainers-keys.asc','57551DE15B968F6341C248F68D8E31AFC32428A6'),
        ('llvm','llvm-project-21.1.8.src.tar.xz','llvm-release-keys.asc','FFB3368980F3E6BB5737145A316C56D064CACBA5')]:
        subprocess.run(['gpg','--homedir',str(gpg),'--batch','--import',str(WORK/'sources'/key)],check=True,capture_output=True)
        result=subprocess.run(['gpg','--homedir',str(gpg),'--batch','--status-fd','1','--verify',str(WORK/'sources'/(archive+'.sig')),str(WORK/'sources'/archive)],capture_output=True,text=True,check=True)
        assert '[GNUPG:] VALIDSIG '+fpr in result.stdout, result.stdout
        signatures.append(dict(name=name,signer=fpr,status=result.stdout))
    result=dict(passed=True,packages=checked,sources=sources,signatures=signatures,
                driver_sha256=c.sha256_file(Path(__file__)),
                container_environment=load('/opt/kiki-host/manifests/environment.json')['fingerprint'])
    save('input-verification.json',result)
    print('LOCKED_INPUTS_VERIFIED',len(checked),'packages; official source SHA and signatures passed',flush=True)
    return result


def prepare():
    verified=verify()
    for name in ['tmp','home','cache','build','packages','payload','host-tools/bin','source']:
        (WORK/name).mkdir(parents=True,exist_ok=True)
    identity=c.build.stable_hash(verified)
    marker=TARGET/'validation/sdk-prepared.json'
    if marker.exists():
        assert load(marker)['identity']==identity,'Input identity changed; select a new candidate directory'
        return
    for name,path in [('llvm-tblgen','/usr/bin/llvm-tblgen'),('ld.lld','/usr/bin/ld.lld'),('patchelf','/opt/kiki-host/bin/patchelf')]:
        p=WORK/'host-tools/bin'/name
        if not p.exists():p.symlink_to(path)
    removed=[]
    for name in ['mesa','llvm']:
        for f in read_manifest(Path(records()[name]['file']))['files']:
            if f['type']=='dir':continue
            p=c.SDK/f['path'].lstrip('/')
            if p.is_symlink():
                assert os.readlink(p)==f['target'], 'SDK symlink owner mismatch: '+str(p)
                p.unlink();removed.append(f['path'])
            elif p.is_file():
                assert c.sha256_file(p)==f['sha256'], 'SDK owner mismatch: '+str(p)
                p.unlink();removed.append(f['path'])
    changes=[]
    mappings=[('/home/tang/kiki-build/mesa-native-20261017',str(WORK)),
              ('/home/tang/kiki-build/gnome50-session-20261017',str(WORK)),
              ('/mnt/e/dev/KIKI-OS/dist/ki2/stage3-6.1.187-mesa-native-candidate-20261017',str(BASE)),
              ('/mnt/e/dev/KIKI-OS/dist/ki2/stage3-6.1.187-gnome50-candidate-20261017',str(BASE)),
              ('/mnt/e/dev/KIKI-OS',str(REPO))]
    for directory in [c.SDK/'usr/bin',c.SDK/'usr/libexec']:
        for p in directory.rglob('*'):
            if p.is_symlink() or not p.is_file() or p.stat().st_size>65536:continue
            data=p.read_bytes()
            if not data.startswith(b'#!'):continue
            updated=data
            for a,b in mappings:updated=updated.replace(a.encode(),b.encode())
            if updated!=data:
                p.write_bytes(updated);changes.append(str(p.relative_to(c.SDK)))
    for name,archive in [('mesa','mesa-25.2.7.tar.xz'),('llvm','llvm-project-21.1.8.src.tar.xz')]:
        destination=WORK/'source'/name;destination.mkdir()
        with tarfile.open(WORK/'sources'/archive) as t:
            for member in t:
                parts=Path(member.name).parts
                if name=='llvm' and len(parts)>1 and parts[1] not in ['llvm','cmake','third-party']:continue
                t.extract(member,destination,filter='data')
    save('sdk-prepared.json',dict(identity=identity,removed_previous_native_runtime=removed,
                                 relocated_sdk_launchers=changes,original_sdk_modified=False))
    print('SDK_PREPARED; original SDK and package archives retained',flush=True)


def package(name,payload,options):
    raw=c.build.read_toml(BASE/'recipes'/(name+'.toml'))['recipe'][0]
    raw['release']='3' if name=='llvm' else '2'
    raw['build']['configure_options']=options
    for p in payload.rglob('*'):
        if p.is_symlink() or not p.is_file():continue
        with p.open('rb') as f:
            if f.read(4)!=b'\x7fELF':continue
        r=subprocess.run([str(WORK/'host-tools/bin/patchelf'),'--print-rpath',str(p)],capture_output=True,text=True)
        if r.returncode==0 and any(s in r.stdout for s in ['/candidate-work','/work/','/opt/kiki-host','/home/','/mnt/','/tmp/']):
            subprocess.run([str(WORK/'host-tools/bin/patchelf'),'--remove-rpath',str(p)],check=True)
    with contextlib.redirect_stdout(io.StringIO()):
        c.package(raw,payload,dict(native_source_build=True,host_runtime_copied=False,
            build_driver_sha256=c.sha256_file(Path(__file__)),
            container_environment=load('/opt/kiki-host/manifests/environment.json')['fingerprint'],
            baseline_package_sha256=records()[name]['sha256'],source_sha256=raw['source']['sha256'],options=options))


def llvm():
    verify();assert (TARGET/'validation/sdk-prepared.json').exists()
    if (TARGET/'validation/llvm-build.json').exists():
        r=load(TARGET/'validation/llvm-build.json');assert c.sha256_file(r['file'])==r['sha256'];return
    source=next((WORK/'source/llvm').iterdir())/'llvm';out=WORK/'build/llvm'
    options=load(BASE/'validation/llvm-native-config.json')['options']
    mapped=[]
    for option in options:
        option=option.replace('/home/tang/kiki-build/mesa-native-20261017/venv',str(VENV))
        option=option.replace('/home/tang/kiki-build/mesa-native-20261017',str(WORK))
        mapped.append(option)
    mapped+=['-DCMAKE_SKIP_RPATH=ON']
    run(['cmake','-S',source,'-B',out]+mapped,'llvm-native-build.log')
    save('llvm-native-config.json',dict(options=mapped,host_tablegen='/usr/bin/llvm-tblgen',target_sysroot=str(c.SDK)))
    run(['ninja','-C',out,'-j2','LLVM','llvm-config','LLVMTableGen'],'llvm-native-build.log')
    compat=out/'lib/libLLVM-21.so'
    if not compat.exists():compat.symlink_to('libLLVM.so.21.1')
    payload=WORK/'payload/llvm';(payload/'usr/lib').mkdir(parents=True)
    for p in (out/'lib').glob('libLLVM*.so*'):
        target=payload/'usr/lib'/p.name
        if p.is_symlink():target.symlink_to(os.readlink(p))
        else:shutil.copy2(p,target)
    license_dir=payload/'usr/share/licenses/llvm';license_dir.mkdir(parents=True);shutil.copy2(source/'LICENSE.TXT',license_dir/'LICENSE.TXT')
    package('llvm',payload,mapped);subprocess.run(['cp','-a',str(payload)+'/.',str(c.SDK)],check=True)
    print('LLVM_NATIVE_PACKAGE_READY',flush=True)


def mesa():
    verify();r=load(TARGET/'validation/llvm-build.json');assert c.sha256_file(r['file'])==r['sha256']
    if (TARGET/'validation/mesa-build.json').exists():
        r=load(TARGET/'validation/mesa-build.json');assert c.sha256_file(r['file'])==r['sha256'];return
    out=WORK/'build/mesa';out.mkdir(exist_ok=True);tools=out/'tools';tools.mkdir(exist_ok=True)
    frozen=TARGET/'inputs/distro/scripts';shutil.copytree(REPO/'distro/scripts',frozen,dirs_exist_ok=True)
    for p in frozen.iterdir():
        if p.is_file() and p.read_bytes().startswith(b'#!'):p.chmod(0o755)
    binary=WORK/'build/llvm/bin/llvm-config'
    loader=next(c.SDK/p/'ld-linux-x86-64.so.2' for p in ['usr/lib64','lib64','usr/lib','lib'] if (c.SDK/p/'ld-linux-x86-64.so.2').is_file() and not (c.SDK/p/'ld-linux-x86-64.so.2').is_symlink())
    subprocess.run([str(WORK/'host-tools/bin/patchelf'),'--set-interpreter',str(loader),'--force-rpath','--set-rpath',env()['KI2_SYSROOT_LIBRARY_PATH'],str(binary)],check=True)
    config=tools/'llvm-config';config.write_text('#!/bin/sh\nexec '+str(binary)+' "$@"\n');config.chmod(0o755)
    cross=out/'cross.ini';cross.write_text("[binaries]\nc = '/usr/bin/gcc'\ncpp = '/usr/bin/g++'\nar = '/usr/bin/ar'\nstrip = '/usr/bin/strip'\npkg-config = '"+str(frozen/'ki2-target-pkg-config')+"'\nllvm-config = '"+str(config)+"'\nexe_wrapper = ['/bin/sh', '"+str(frozen/'ki2-target-run')+"']\n[host_machine]\nsystem = 'linux'\ncpu_family = 'x86_64'\ncpu = 'x86_64'\nendian = 'little'\n[properties]\nneeds_exe_wrapper = true\n")
    options=c.build.read_toml(BASE/'recipes/mesa.toml')['recipe'][0]['build']['configure_options']
    extra=dict(KI2_USE_TARGET_LOADER='1',KI2_REPO_ROOT=str(REPO),KI2_BUILD_DIR=str(out),
               PATH=str(tools)+':'+str(VENV/'bin')+':'+str(c.SDK/'usr/bin')+':/usr/bin:/bin')
    if not (out/'meson/build.ninja').exists():run(['meson','setup',out/'meson',WORK/'source/mesa/mesa-25.2.7','--cross-file',cross]+options,'mesa-native-build.log',extra)
    run(['ninja','-C',out/'meson','-j2'],'mesa-native-build.log',extra)
    payload=WORK/'payload/mesa';payload.mkdir(parents=True)
    run(['meson','install','-C',out/'meson','--no-rebuild'],'mesa-native-build.log',dict(extra,DESTDIR=str(payload)))
    license_dir=payload/'usr/share/licenses/mesa';license_dir.mkdir(parents=True,exist_ok=True)
    shutil.copy2(WORK/'source/mesa/mesa-25.2.7/docs/license.rst',license_dir/'license.rst')
    package('mesa',payload,options);subprocess.run(['cp','-a',str(payload)+'/.',str(c.SDK)],check=True)
    print('MESA_NATIVE_PACKAGE_READY',flush=True)


def validate(job_dir=None):
    verify();all_records=records();built={}
    for name in ['llvm','mesa']:
        r=load(TARGET/'validation'/(name+'-build.json'));assert c.sha256_file(r['file'])==r['sha256'];all_records[name]=r;built[name]=r
    manifests={n:read_manifest(Path(r['file'])) for n,r in all_records.items()};suppliers={}
    for n,m in manifests.items():
        for f in m['files']:
            if '.so' in Path(f['path']).name:suppliers.setdefault(Path(f['path']).name,set()).add(n)
    errors=[];elf=[]
    for name in built:
        needed=set();paths=[]
        for p in (WORK/'payload'/name).rglob('*'):
            if p.is_symlink() or not p.is_file():continue
            with p.open('rb') as f:
                if f.read(4)!=b'\x7fELF':continue
            text=subprocess.check_output(['readelf','-d',str(p)],text=True)
            needed.update(re.findall(r'\(NEEDED\).*?\[(.*?)\]',text))
            for value in re.findall(r'\((?:RPATH|RUNPATH)\).*?\[(.*?)\]',text):
                paths.append(value)
                if any(s in value for s in ['/candidate-work','/work/','/opt/kiki-host','/home/','/mnt/','/tmp/']):errors.append([name,'build rpath',value])
        allowed=set(manifests[name]['dependencies']['runtime'])|{name}
        for soname in needed:
            if not suppliers.get(soname,set()) & allowed:errors.append([name,'missing direct ELF supplier',soname,sorted(suppliers.get(soname,set()))])
        elf.append(dict(name=name,needed=sorted(needed),runtime_paths=paths))
    save('elf-validation.json',dict(passed=not errors,errors=errors,packages=elf));assert not errors,errors
    clean=WORK/'native-root';clean.mkdir(exist_ok=True)
    plan=load(BASE/'validation/desktop-root-plan.json')
    for name in plan['order']:c.build.extract_package_rootfs(Path(all_records[name]['file']),clean)
    run(['chroot',clean,'/sbin/ldconfig'],'runtime-validation.log')
    checked=0
    for name in plan['order']:
        for f in manifests[name]['files']:
            if f['type']!='file' or f['path']=='/etc/ld.so.cache':continue
            p=clean/f['path'].lstrip('/')
            assert p.is_file() and c.sha256_file(p)==f['sha256'], 'Clean-root payload mismatch: '+f['path']
            checked+=1
    save('native-root-payload.json',dict(passed=True,regular_files_checked=checked,packages=len(plan['order'])))
    probe=WORK/'mesa-probe';flags=env()
    run(['gcc','--sysroot='+str(c.SDK),'-O2',REPO/'tools/kiki_mesa_probe.c','-o',probe]+flags['LDFLAGS'].split()+['-lEGL','-lGLESv2','-lgbm','-lm'],'runtime-validation.log')
    (clean/'tmp').mkdir(exist_ok=True);shutil.copy2(probe,clean/'tmp/mesa-probe')
    r=subprocess.run(['chroot',str(clean),'/usr/bin/env','EGL_PLATFORM=surfaceless','LIBGL_ALWAYS_SOFTWARE=1','MESA_SHADER_CACHE_DISABLE=true','/tmp/mesa-probe'],capture_output=True,text=True)
    save('native-root-rendering.json',dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr,passed=r.returncode==0,scope='Surfaceless CPU rendering in build container; no GDM/Wayland login validation'))
    print(r.stdout,r.stderr,flush=True);r.check_returncode()
    rendered=json.loads(r.stdout)
    assert rendered['passed'] and 'LLVM 21.1.8' in rendered['renderer'] and 'Mesa 25.2.7' in rendered['gl_version']
    for name,record in built.items():
        record.update(runtime_validated=True,runtime_validation_scope='Clean native root, surfaceless llvmpipe shader/pixel test; VM login not tested')
        save(name+'-build.json',record)
    if job_dir:
        assert job_dir.resolve().is_relative_to(REPO/'build/ki2ci/jobs')
        dest=job_dir/'packages/x86_64';dest.mkdir(parents=True,exist_ok=True)
        for r in built.values():
            p=Path(r['file']);shutil.copy2(p,dest/p.name);assert c.sha256_file(dest/p.name)==r['sha256']
    save('rebuild-result.json',dict(passed=True,packages=built,root_packages=len(plan['order']),vm_login_tested=False,repository_promoted=False))
    print('NATIVE_REBUILD_AND_VALIDATION_PASSED',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['verify','prepare','llvm','mesa','validate']);parser.add_argument('--job-dir',type=Path);args=parser.parse_args()
    if args.action=='validate':validate(args.job_dir)
    else:globals()[args.action]()
