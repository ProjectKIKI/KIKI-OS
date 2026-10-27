#!/usr/bin/env python3
"""Make installed GNOME Shell application launchers invoke target GJS."""
import contextlib
import io
import json
from pathlib import Path
import tomli
import ki2sessioncandidate as c
from ki2stage3candidate import read_manifest

r=json.loads((c.TARGET/'validation/gnome-shell-build.json').read_text())
if c.sha256_file(r['file'])!=r['sha256']:raise ValueError('Changed Shell archive')
m=read_manifest(r['file']);raw=tomli.loads((c.TARGET/'recipes/gnome-shell.toml').read_text())['recipe'][0]
raw['release']=str(int(m['release'])+1)
dest=c.WORK/'shell-application-launchers';c.build.extract_package_rootfs(Path(r['file']),dest)
changes=[]
for name in ['gnome-extensions-app','gnome-shell-extension-tool','gnome-shell-test-tool']:
    p=dest/'usr/bin'/name;before=p.read_text()
    old=str(c.WORK/'desktop-build/gnome-shell/build/tools/gjs')
    after=before.replace(old,'/usr/bin/gjs').replace('#!'+str(c.VENV/'bin/python3'),'#!/usr/bin/python3')
    if after==before:raise ValueError('Unexpected launcher: '+name)
    p.write_text(after);p.chmod(0o755)
    changes.append(dict(path='/usr/bin/'+name,before=before,after=after))
c.save(c.TARGET/'validation/repacked-predecessors'/(Path(r['file']).name+'.json'),r)
with contextlib.redirect_stdout(io.StringIO()):c.package(raw,dest,dict(r['provenance'],parent_package_sha256=r['sha256'],application_launchers=changes,elf_bytes_unchanged=True))
print('Corrected three installed GNOME application launchers',flush=True)
