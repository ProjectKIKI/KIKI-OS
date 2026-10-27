#!/usr/bin/env python3
"""Correct verified legacy suppliers in new candidate releases only."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import ki2sessioncandidate as c


def repair(name):
    if (c.TARGET/'validation'/(name+'-build.json')).exists():
        print('Already repaired',name);return
    snapshot=json.loads((c.BASE/'snapshot.json').read_text())
    record=next(x for x in snapshot['packages'] if x['name']==name)
    archive=c.BASE/'packages/x86_64'/record['file']
    if c.sha256_file(archive)!=record['sha256']:raise ValueError('Original supplier changed')
    with tarfile.open(archive) as t:m=json.load(t.extractfile('manifest.json'))
    dest=c.WORK/('supplier-fix-'+name)
    if not dest.exists():c.build.extract_package_rootfs(archive,dest)
    raw=next(x for x in json.loads((c.BASE/'recipes/catalog.json').read_text())['recipes'] if x['name']==name)
    raw['release']=str(int(raw['release'])+1)
    changes=[]
    if name=='zstd':
        if not (dest/'usr/include/zstd.h').exists():raise ValueError('Unexpected header supplier layout')
        pc=dest/'usr/lib/pkgconfig/libzstd.pc'
        before=pc.read_text();after=before.replace('prefix=/usr/local\n','prefix=/usr\n')
        if before!=after:pc.write_text(after)
        changes.append(dict(path='/usr/lib/pkgconfig/libzstd.pc',before=before,after=after))
    elif name=='gobject-introspection':
        r=json.loads((c.TARGET/'validation/glib-build.json').read_text())
        if c.sha256_file(r['file'])!=r['sha256']:raise ValueError('New GLib changed')
        with tarfile.open(r['file']) as t:g=json.load(t.extractfile('manifest.json'))
        owned={x['path'] for x in g['files'] if x['type']!='dir'}
        for x in m['files']:
            if x['type']!='dir' and x['path'] in owned:
                p=dest/x['path'].lstrip('/')
                if p.exists() or p.is_symlink():p.unlink()
                changes.append(dict(path=x['path'],supplier='glib-2.88.3'))
    else:raise ValueError(name)
    if not changes:raise ValueError('No documented supplier correction')
    with contextlib.redirect_stdout(io.StringIO()):c.package(raw,dest,dict(parent_package=record,corrections=changes,elf_bytes_unchanged=True))
    subprocess.run(['cp','-a',str(dest)+'/.',str(c.SDK)],check=True)
    print('Repaired and staged',name,len(changes),'metadata/ownership entries',flush=True)


if __name__=='__main__':
    for name in sys.argv[1:]:repair(name)
