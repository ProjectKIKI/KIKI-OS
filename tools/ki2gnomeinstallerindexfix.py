#!/usr/bin/env python3
"""Restore the preserved static installer's file-before-name index wire format."""
import json
import re
import ki2sessioncandidate as c
import ki2repo

old=c.TARGET/'install-repo-r2'
dest=c.TARGET/'install-repo-r3';dest.mkdir(exist_ok=False)
index=json.loads((old/'index.x86_64.json').read_text())
# Use the repository tool's canonical on-disk field order, not insertion order.
ki2repo.write_json(dest/'index.x86_64.json',index)
text=(dest/'index.x86_64.json').read_text()
checked=[]
for entry in index['packages']:
    matches=list(re.finditer(r'"name"\s*:\s*"'+re.escape(entry['name'])+r'"',text))
    if len(matches)!=1:raise ValueError('Ambiguous static index record: '+entry['name'])
    offset=matches[0].start()
    preceding=list(re.finditer(r'"file"\s*:\s*"([^"]+)"',text[max(0,offset-1024):offset]))
    if not preceding or preceding[-1].group(1)!=entry['file']:raise ValueError('Static installer filename lookup differs: '+entry['name'])
    p=c.TARGET/'install-packages-r2/x86_64'/entry['file']
    if not p.is_file() or c.sha256_file(p)!=entry['sha256']:raise ValueError('Package supplier mismatch: '+entry['name'])
    checked.append(entry['name'])
metadata=json.loads((old/'metadata.x86_64.json').read_text())
metadata['index']['sha256']=c.sha256_file(dest/'index.x86_64.json')
metadata['index']['size']=(dest/'index.x86_64.json').stat().st_size
metadata['artifacts']['iso']=[]
ki2repo.write_json(dest/'metadata.x86_64.json',metadata)
ki2repo.sign_metadata_file(dest/'metadata.x86_64.json',c.WORK/'candidate-keys/gnome50-candidate.ed25519')
if not ki2repo.verify_metadata_file(dest/'metadata.x86_64.json',c.TARGET/'build-tools/gnome50-candidate.ed25519.pub'):raise ValueError('Signature failed')
c.save(c.TARGET/'validation/installer-static-index-compatibility.json',dict(passed=True,checked_packages=len(checked),all_package_sha256_verified=True,all_static_filename_lookups_match=True,field_order='ki2repo canonical sorted keys: file before name',index_sha256=c.sha256_file(dest/'index.x86_64.json'),packages=checked))
print('Static installer index lookup and archive SHA verified for all',len(checked),'packages',flush=True)
