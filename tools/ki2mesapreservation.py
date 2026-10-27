#!/usr/bin/env python3
"""Check original artifacts and the preserved GNOME r6 candidate around Mesa work."""
import hashlib
import datetime
import json
from pathlib import Path

repo=Path(__file__).resolve().parents[1]
old=repo/'dist/ki2/stage3-6.1.187-gnome50-candidate-20261017'
target=repo/'dist/ki2/stage3-6.1.187-mesa-native-candidate-20261017/validation'
target.mkdir(parents=True,exist_ok=True)
baseline=target/'preservation-baseline.json'
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(16*1024*1024),b''):h.update(b)
    return h.hexdigest()
if not baseline.exists():
    original=json.loads((old/'validation/original-preservation-current.json').read_text())
    if not original['passed']:raise ValueError('Original preservation was not passed')
    records=[dict(path=r['path'].replace('\\','/'),sha256=r['expected_sha256'],kind='original') for r in original['files']]
    pub=old/'validated-candidate'
    index=json.loads((pub/'repo/index.x86_64.json').read_text())
    for r in index['packages']:records.append(dict(path=(pub/'packages/x86_64'/r['file']).relative_to(repo).as_posix(),sha256=r['sha256'],kind='preserved-r6-package'))
    metadata=json.loads((pub/'repo/metadata.x86_64.json').read_text())
    for r in metadata['artifacts']['iso']:records.append(dict(path=(pub/'iso'/r['file']).relative_to(repo).as_posix(),sha256=r['sha256'],kind='preserved-r6-iso'))
    for relative in ['repo/index.x86_64.json','repo/metadata.x86_64.json','gnome50-candidate.ed25519.pub','fresh-install-runtime.json','validation.json','README.ko.md']:
        p=pub/relative;records.append(dict(path=p.relative_to(repo).as_posix(),sha256=sha(p),kind='preserved-r6-metadata'))
    p=repo/'artifacts/gnome50-install-vm-20261017/install-test.vhdx'
    records.append(dict(path=p.relative_to(repo).as_posix(),sha256=sha(p),kind='preserved-r6-vm-parent'))
    baseline.write_text(json.dumps(dict(files=records),indent=2)+'\n')
records=json.loads(baseline.read_text())['files']
failures=[]
for r in records:
    if sha(repo/r['path'])!=r['sha256']:failures.append(r['path'])
result=dict(passed=not failures,original_files=sum(r['kind']=='original' for r in records),preserved_r6_files=sum(r['kind']!='original' for r in records),failures=failures,checked=len(records),checked_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
(target/'preservation-current.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result),flush=True)
raise SystemExit(bool(failures))
