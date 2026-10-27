#!/usr/bin/env python3
"""Repair explicitly identified install-directory mistakes in staged packages."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import sys
import tomli
import ki2sessioncandidate as c
from ki2stage3candidate import read_manifest

for name in sys.argv[1:]:
    report=c.TARGET/'validation'/(name+'-build.json')
    r=json.loads(report.read_text()) if report.exists() else next(dict(x,file=str(c.BASE/'packages/x86_64'/x['file'])) for x in json.loads((c.BASE/'snapshot.json').read_text())['packages'] if x['name']==name)
    if c.sha256_file(r['file'])!=r['sha256']:raise ValueError('Changed archive')
    m=read_manifest(r['file'])
    prefixes=[str(c.SDK),'/tmp/kiki-gnome-native/x86_64/sysroot','/tmp/kiki-p11-kit-jo5oodZv/x86_64/sysroot']
    bad=[f for f in m['files'] if f['type']!='dir' and any(f['path'].startswith(prefix+'/') for prefix in prefixes)]
    if not bad:print('Layout already standard',name,flush=True);continue
    recipe=c.TARGET/'recipes'/(name+'.toml')
    raw=tomli.loads(recipe.read_text())['recipe'][0] if recipe.exists() else next(x for x in json.loads((c.BASE/'recipes/catalog.json').read_text())['recipes'] if x['name']==name)
    raw['release']=str(int(m['release'])+1)
    dest=c.WORK/'layout-repaired'/(name+'-'+raw['release'])
    if dest.exists():raise FileExistsError(dest)
    c.build.extract_package_rootfs(Path(r['file']),dest)
    changes=[]
    for f in bad:
        old=f['path'];new=old
        while any(new.startswith(prefix+'/') for prefix in prefixes):
            prefix=next(prefix for prefix in prefixes if new.startswith(prefix+'/'));new=new[len(prefix):]
        if not new.startswith('/usr/'):raise ValueError('Unexpected destination')
        source=dest/old.lstrip('/');target=dest/new.lstrip('/')
        if name=='colord' or '__pycache__' in new:
            source.unlink();operation='remove unbuilt colord daemon integration' if name=='colord' else 'omit generated Python cache'
        else:
            if target.exists() or target.is_symlink():raise ValueError('Relocation collision')
            target.parent.mkdir(exist_ok=True,parents=True);source.rename(target);operation='target installation directory'
        changes.append(dict(before=old,after=new,operation=operation))
    for p in sorted(dest.rglob('*'),key=lambda p:len(p.parts),reverse=True):
        if p.is_dir() and not p.is_symlink() and not any(p.iterdir()):p.rmdir()
    c.save(c.TARGET/'validation/repacked-predecessors'/(Path(r['file']).name+'.json'),r)
    with contextlib.redirect_stdout(io.StringIO()):c.package(raw,dest,dict(r.get('provenance',{}),parent_package_sha256=r['sha256'],target_layout_corrections=changes,elf_bytes_unchanged=True))
    print('Corrected target layout',name,len(changes),flush=True)
