#!/usr/bin/env python3
"""Use the target GJS executable in GNOME Shell's installed D-Bus activation files."""
import contextlib
import io
import json
from pathlib import Path
import tomli
import ki2sessioncandidate as c
from ki2stage3candidate import read_manifest

name='gnome-shell';r=json.loads((c.TARGET/'validation/gnome-shell-build.json').read_text())
if c.sha256_file(r['file'])!=r['sha256']:raise ValueError('Changed shell package')
m=read_manifest(r['file']);raw=tomli.loads((c.TARGET/'recipes/gnome-shell.toml').read_text())['recipe'][0]
raw['release']=str(int(m['release'])+1)
dest=c.WORK/'activation-repaired'/('gnome-shell-'+raw['release'])
c.build.extract_package_rootfs(Path(r['file']),dest)
changes=[]
for p in (dest/'usr/share/dbus-1/services').glob('*.service'):
    before=p.read_text()
    old=str(c.WORK/'desktop-build/gnome-shell/build/tools/gjs')
    after=before.replace('Exec='+old+' ','Exec=/usr/bin/gjs ')
    if before!=after:p.write_text(after);changes.append(dict(path=str(p.relative_to(dest)),before=before,after=after))
if len(changes)!=4:raise ValueError('Unexpected Shell D-Bus activation set')
c.save(c.TARGET/'validation/repacked-predecessors'/(Path(r['file']).name+'.json'),r)
with contextlib.redirect_stdout(io.StringIO()):c.package(raw,dest,dict(r['provenance'],parent_package_sha256=r['sha256'],dbus_activation_corrections=changes,elf_bytes_unchanged=True))
print('Corrected four GNOME Shell D-Bus activation commands',flush=True)
