#!/usr/bin/env python3
"""Restore legitimate installed private-library paths without build-directory leakage."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tomli
import ki2sessioncandidate as c
from ki2stage3candidate import read_manifest

patcher=c.WORK/'host-tools/bin/patchelf'
tool=json.loads((c.TARGET/'validation/patchelf-host-lock.json').read_text())
if c.sha256_file(patcher)!=tool['sha256']:raise ValueError('ELF tool changed')
for name in ['gnome-shell','mutter']:
    r=json.loads((c.TARGET/'validation'/(name+'-build.json')).read_text())
    if c.sha256_file(r['file'])!=r['sha256']:raise ValueError('Changed candidate')
    m=read_manifest(r['file']);raw=tomli.loads((c.TARGET/'recipes'/(name+'.toml')).read_text())['recipe'][0]
    raw['release']=str(int(m['release'])+1)
    dest=c.WORK/'private-rpath-repaired'/(name+'-'+raw['release'])
    c.build.extract_package_rootfs(Path(r['file']),dest)
    changes=[]
    for p in dest.rglob('*'):
        if not p.is_file() or p.is_symlink():continue
        with p.open('rb') as f:
            if f.read(4)!=b'\x7fELF':continue
        dynamic=subprocess.run(['readelf','-d',str(p)],capture_output=True,text=True,check=True).stdout
        if '(NEEDED)' not in dynamic:continue
        private='/usr/lib/mutter-18'
        if 'Shared library: [libmutter-' not in dynamic:continue
        old=subprocess.check_output([str(patcher),'--print-rpath',str(p)],text=True).strip()
        after=':'.join(dict.fromkeys([v for v in old.split(':') if v]+[private]))
        if after==old:continue
        mode=p.stat().st_mode & 0o7777;before=c.sha256_file(p)
        subprocess.run([str(patcher),'--set-rpath',after,str(p)],check=True);p.chmod(mode)
        changes.append(dict(path=str(p.relative_to(dest)),before_sha256=before,after_sha256=c.sha256_file(p),rpath_before=old,rpath_after=after))
    if not changes:print('Private library paths already valid',name,flush=True);continue
    c.save(c.TARGET/'validation/repacked-predecessors'/(Path(r['file']).name+'.json'),r)
    with contextlib.redirect_stdout(io.StringIO()):c.package(raw,dest,dict(r['provenance'],parent_package_sha256=r['sha256'],target_private_library_paths=changes,elf_postprocessor=tool))
    print('Restored private library lookup',name,len(changes),flush=True)
