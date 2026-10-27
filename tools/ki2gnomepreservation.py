#!/usr/bin/env python3
"""Recheck all original package/ISO boundaries against their saved SHA records."""
import hashlib
import json
from pathlib import Path

repo=Path(__file__).resolve().parents[1]
base=repo/'dist/ki2/stage3-6.1.187-candidate-20261016'
frozen=base/'rebuild-frozen-20261017'
out=repo/'dist/ki2/stage3-6.1.187-gnome50-candidate-20261017/validation/original-preservation-current.json'
def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(16*1024*1024),b''):h.update(block)
    return h.hexdigest()
records=json.loads((frozen/'preservation.json').read_text())
items=[]
for relative,expected in records['baseline_metadata'].items():items.append((base/relative,expected,'original metadata'))
for r in records['packages']:items.append((repo/r['path'].replace('\\','/'),r['sha256'],'original package'))
for relative,expected in records['source_inputs'].items():items.append((frozen/'inputs'/relative.replace('\\','/'),expected,'frozen input'))
iso=json.loads((frozen/'original-iso-preservation.json').read_text())
for r in iso['images']:items.append((repo/r['path'].replace('\\','/'),r['sha256'],'original ISO'))
items.append((repo/'dist/ki2/stage3-6.1.187-candidate-pngfix-20261017/iso/kiki-6.1.187-pngfix-r19-validated.iso','e0cf1a00bfc233e67a5c7e7587315dcac6038a13025ce1dc7ac2162b4738fc3c','preserved PNG installer ISO'))
results=[]
for p,expected,kind in items:
    actual=digest(p)
    results.append(dict(path=str(p.relative_to(repo)),kind=kind,sha256=actual,expected_sha256=expected,preserved=actual==expected))
failures=[r for r in results if not r['preserved']]
out.write_text(json.dumps(dict(passed=not failures,checked=len(results),failures=failures,files=results),indent=2)+'\n')
print('Original preservation:',len(results),'files;',len(failures),'changes',flush=True)
raise SystemExit(1 if failures else 0)
