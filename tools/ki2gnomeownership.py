#!/usr/bin/env python3
"""Resolve explicit native file suppliers for a fresh candidate installation."""
import contextlib
import io
import json
from pathlib import Path
import tomli
import ki2sessioncandidate as c

plan=json.loads((c.TARGET/'validation/desktop-root-plan.json').read_text())
records={r['name']:r for r in plan['packages']}
catalog={r['name']:r for r in json.loads((c.BASE/'recipes/catalog.json').read_text())['recipes']}
removals={}
for conflict in plan['conflicts']:
    path=conflict['path'];owners=set(conflict['owners'])
    if path=='/usr/share/info/dir':losers=owners
    elif 'busybox' in owners:losers={'busybox'}
    elif path in ['/etc/systemd/logind.conf','/etc/systemd/resolved.conf','/etc/systemd/system.conf']:losers={'systemd'}
    elif path=='/etc/login.defs':losers={'shadow'}
    elif path=='/sbin/nologin':losers={'shadow'}
    elif path=='/usr/share/man/man1/kill.1':losers={'coreutils'}
    elif path=='/etc/gdm/custom.conf':losers={'gdm'}
    else:raise ValueError('Undecided supplier: '+str(conflict))
    for name in losers:removals.setdefault(name,set()).add(path)
for name,paths in sorted(removals.items()):
    r=records[name]
    if c.sha256_file(r['file'])!=r['sha256']:raise ValueError('Changed package')
    recipe=c.TARGET/'recipes'/(name+'.toml')
    raw=tomli.loads(recipe.read_text())['recipe'][0] if recipe.exists() else catalog[name]
    raw['release']=str(int(raw['release'])+1)
    dest=c.WORK/'ownership-finalized'/(name+'-'+raw['release'])
    if dest.exists():raise FileExistsError(dest)
    c.build.extract_package_rootfs(Path(r['file']),dest)
    for path in paths:
        p=dest/path.lstrip('/')
        if not p.is_file() and not p.is_symlink():raise ValueError('Unexpected collision payload: '+str(p))
        p.unlink()
    olddir=c.TARGET/'validation/repacked-predecessors';olddir.mkdir(exist_ok=True)
    c.save(olddir/(Path(r['file']).name+'.json'),r)
    provenance=dict(r.get('provenance',{}),parent_package_sha256=r['sha256'],removed_duplicate_paths=sorted(paths),purpose='Fresh-install unique file suppliers; original archives retained')
    with contextlib.redirect_stdout(io.StringIO()):c.package(raw,dest,provenance)
    print('Resolved native ownership',name,len(paths),flush=True)
