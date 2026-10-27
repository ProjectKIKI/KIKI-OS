#!/usr/bin/env python3
"""Reuse audited original source archives in the isolated desktop source lock."""
import json
from pathlib import Path
import shutil
import sys
import tarfile
import ki2sessioncandidate as c

lock=json.loads((c.TARGET/'gnome50-source-lock.json').read_text())
catalog=json.loads((c.BASE/'recipes/catalog.json').read_text())['recipes']
for name in sys.argv[1:]:
    raw=next(x for x in catalog if x['name']==name);s=raw['source']
    old=c.BASE/'sources'/s.get('file',s['url'].rsplit('/',1)[-1])
    if c.sha256_file(old)!=s['sha256']:raise ValueError('Preserved source changed')
    dest=c.WORK/'sources'/old.name
    if not dest.exists():shutil.copy2(old,dest)
    if c.sha256_file(dest)!=s['sha256']:raise ValueError('Source copy changed')
    record=dict(name=name,version=raw['version'],url=s['url'],sha256=s['sha256'],file=str(dest),verification='Previously audited original upstream source archive')
    if not any(x.get('name')==name for x in lock['sources']):lock['sources'].append(record)
    with tarfile.open(dest) as t:
        for member in t.getmembers():
            if member.name.endswith(('meson.options','meson_options.txt')) and member.name.count('/')==1:
                p=c.TARGET/'inputs/meson-inspect'/(name+'-options.txt');p.parent.mkdir(exist_ok=True,parents=True);p.write_bytes(t.extractfile(member).read())
c.save(c.TARGET/'gnome50-source-lock.json',lock)
print('Locked preserved desktop sources:',', '.join(sys.argv[1:]),flush=True)
