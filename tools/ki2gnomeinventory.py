#!/usr/bin/env python3
"""Record runtime imports and session requirements from locked upstream source."""
import json
from pathlib import Path
import re
import tarfile
import ki2sessioncandidate as c

lock=json.loads((c.TARGET/'gnome50-source-lock.json').read_text())
imports={}
for name in ['gnome-shell','gnome-session','gnome-settings-daemon']:
 s=next(x for x in lock['sources'] if x.get('name')==name or Path(x['file']).name.startswith(name+'-'))
 if c.sha256_file(s['file'])!=s['sha256']:raise ValueError('Source changed')
 with tarfile.open(s['file']) as t:
  for m in t.getmembers():
   if not m.isfile():continue
   if name=='gnome-shell' and m.name.endswith('.js'):
    text=t.extractfile(m).read().decode('utf-8')
    for n in re.findall(r'''from ['"]gi://([^'"?]+)''',text):imports.setdefault(n,[]).append(m.name)
   if name!='gnome-shell' and (m.name.endswith(('.target.in','.session.desktop.in.in','.session.in','.target','.service.in','.gschema.xml.in','.gschema.xml')) or m.name.count('/')==1 and m.name.endswith('meson.build')):
    out=c.TARGET/'inputs/runtime-inspect'/name/Path(m.name).relative_to(Path(m.name).parts[0])
    out.parent.mkdir(exist_ok=True,parents=True);out.write_bytes(t.extractfile(m).read())
c.save(c.TARGET/'validation/shell-gi-imports.json',imports)
print('Shell namespaces:',', '.join(sorted(imports)))
