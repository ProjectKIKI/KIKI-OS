#!/usr/bin/env python3
"""Remove candidate-only build search paths and fix the SQLite SONAME supplier."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tomli
import ki2sessioncandidate as c

patcher=c.WORK/'host-tools/bin/patchelf'
tool=json.loads((c.TARGET/'validation/patchelf-host-lock.json').read_text())
if c.sha256_file(patcher)!=tool['sha256']:raise ValueError('Host ELF tool changed')


def atomic_stage(payload):
    for p in sorted(payload.rglob('*'),key=lambda x:(x.is_symlink(),str(x))):
        relative=p.relative_to(payload);out=c.SDK/relative
        if p.is_dir() and not p.is_symlink():out.mkdir(exist_ok=True,parents=True);continue
        out.parent.mkdir(exist_ok=True,parents=True)
        if not out.parent.resolve().is_relative_to(c.SDK.resolve()):raise ValueError('SDK path escaped')
        temp=out.with_name(out.name+'.kiki-stage-new')
        if temp.exists() or temp.is_symlink():raise ValueError('Stale SDK staging temporary')
        if p.is_symlink():temp.symlink_to(os.readlink(p))
        else:shutil.copy2(p,temp)
        temp.replace(out)


def repair(name):
    report=c.TARGET/'validation'/(name+'-build.json');r=json.loads(report.read_text())
    if r['provenance'].get('elf_install_repair') and (name!='nss' or r['provenance'].get('nss_integrity_resigned')):
        print('Already repaired',name,flush=True);return
    if c.sha256_file(r['file'])!=r['sha256']:raise ValueError('Candidate changed')
    raw=tomli.loads((c.TARGET/'recipes'/(name+'.toml')).read_text())['recipe'][0]
    raw['release']=str(int(raw['release'])+1)
    dest=c.WORK/'elf-repairs'/(name+'-'+raw['release'])
    if dest.exists():raise FileExistsError(dest)
    c.build.extract_package_rootfs(Path(r['file']),dest)
    changes=[]
    if name=='kiki-mesa-bootstrap':
        for p in dest.rglob('*'):
            if p.name.startswith(('libgcc_s','libz.so')) and (p.is_file() or p.is_symlink()):
                changes.append(dict(path=str(p.relative_to(dest)),operation='use native libgcc/zlib supplier'))
                p.unlink()
        raw['dependencies']['runtime']=sorted(set(raw['dependencies']['runtime'])|{'libgcc','zlib'})
    if name=='sqlite':
        old=dest/'usr/lib/libsqlite3.so';real=old.resolve()
        if not real.is_file() or not real.is_relative_to(dest.resolve()):raise ValueError('Unexpected SQLite library layout')
        runtime_link=dest/'usr/lib/libsqlite3.so.0'
        if not runtime_link.exists():runtime_link.symlink_to(real.name)
        subprocess.run([str(patcher),'--set-soname','libsqlite3.so.0',str(real)],check=True)
        changes.append(dict(path='/usr/lib/libsqlite3.so.0',operation='set stable SQLite ABI SONAME; development symlink retained'))
    for p in dest.rglob('*'):
        if not p.is_file() or p.is_symlink():continue
        with p.open('rb') as f:
            if f.read(4)!=b'\x7fELF':continue
        dynamic=subprocess.run(['readelf','-d',str(p)],capture_output=True,text=True,check=True).stdout
        if 'Dynamic section' not in dynamic:continue
        mode=stat.S_IMODE(p.stat().st_mode);before=c.sha256_file(p)
        old=subprocess.check_output([str(patcher),'--print-rpath',str(p)],text=True).strip()
        keep=':'.join(x for x in old.split(':') if x and not any(v in x for v in ['/home/','/mnt/','/tmp/']))
        if old!=keep:
            args=['--set-rpath',keep] if keep else ['--remove-rpath']
            subprocess.run([str(patcher)]+args+[str(p)],check=True)
        needed=subprocess.check_output([str(patcher),'--print-needed',str(p)],text=True).splitlines()
        for dep in needed:
            if dep=='libsqlite3.so' or dep.startswith(str(c.SDK)+'/') and Path(dep).name.startswith('libsqlite3.so'):
                subprocess.run([str(patcher),'--replace-needed',dep,'libsqlite3.so.0',str(p)],check=True)
        p.chmod(mode)
        after=c.sha256_file(p)
        if before!=after:changes.append(dict(path='/'+str(p.relative_to(dest)),before_sha256=before,after_sha256=after,rpath_before=old,rpath_after=keep,mode=oct(mode)))
    if name=='nss':
        signer=next((c.WORK/'desktop-build/nss/source/nss/cmd/shlibsign').glob('Linux*/shlibsign'))
        env=dict(KI2_USE_TARGET_LOADER='1',KI2_SYSROOT_LIBRARY_PATH=str(dest/'usr/lib')+':'+c.environment()['KI2_SYSROOT_LIBRARY_PATH'])
        signed=[]
        for basename in ['libsoftokn3','libfreebl3','libfreeblpriv3','libnssdbm3']:
            library=dest/'usr/lib'/(basename+'.so')
            if not library.exists():continue
            c.run(['/bin/sh',str(c.TARGET/'inputs/distro/scripts/ki2-target-run'),str(signer),'-v','-i',str(library)],dest,c.TARGET/'validation/nss-postinstall-sign.log',env)
            signed.append(dict(path='/usr/lib/'+basename+'.chk',sha256=c.sha256_file(library.with_suffix('.chk'))))
        changes.append(dict(operation='regenerate NSS module integrity signatures after ELF changes',signatures=signed,signer_sha256=c.sha256_file(signer)))
    if not changes:raise ValueError('No ELF correction needed: '+name)
    olddir=c.TARGET/'validation/repacked-predecessors';olddir.mkdir(exist_ok=True)
    c.save(olddir/(Path(r['file']).name+'.json'),r)
    provenance=dict(r['provenance'],elf_install_repair=True,parent_package_sha256=r['sha256'],elf_tool=tool,changes=changes)
    if name=='nss':
        provenance['nss_integrity_resigned']=True
        patch=c.TARGET/'inputs/patches/nss-shlibsign-target-loader.patch'
        provenance['source_patches']=[dict(path=str(patch),sha256=c.sha256_file(patch))]
    with contextlib.redirect_stdout(io.StringIO()):c.package(raw,dest,provenance)
    if name!='shadow':atomic_stage(dest)
    print('Repaired candidate ELF installation:',name,len(changes),'changes',flush=True)


if __name__=='__main__':
    for name in sys.argv[1:]:repair(name)
