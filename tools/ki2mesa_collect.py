#!/usr/bin/env python3
"""Bind actual guest evidence to the exact native candidate and screenshots."""
import base64
import hashlib
import json
from pathlib import Path
import re

repo=Path(__file__).resolve().parents[1]
target=repo/'dist/ki2/stage3-6.1.187-mesa-native-candidate-20261017'
lab=repo/'artifacts/mesa-native-vm-20261017'
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()
text=(lab/'serial.log').read_text(errors='replace')
matches=list(re.finditer(r'KIKI_MESA_REPORT_BEGIN\s+([A-Za-z0-9+/=\r\n]+)\s+KIKI_MESA_REPORT_END',text))
if not matches:raise SystemExit('No actual Mesa runtime report in new VM serial log')
report=json.loads(base64.b64decode(re.sub(r'\s','',matches[-1].group(1)),validate=True))
vm=json.loads((lab/'vm.json').read_text(encoding='utf-8-sig'))
if report.get('vm_id')!=vm['id'] or vm['scope']!='disposable-mesa-native' or not report.get('passed'):raise ValueError('VM evidence identity mismatch')
status=json.loads((lab/'vm-status.json').read_text(encoding='utf-8-sig'))
if status['id']!=vm['id'] or status['state']!='Off' or any(x['connected'] for x in status['adapters']) or any(status['dvd_paths']):raise ValueError('Final VM must be stopped with network disconnected and DVD ejected')
if status['disk']!=vm['disk'] or status['parent_disk']!=vm['parent_disk']:raise ValueError('Differencing disk identity changed')
preserved=json.loads((target/'validation/preservation-current.json').read_text())
if not preserved.get('passed'):raise ValueError('Original/r6 preservation gate failed')
plan_path=target/'validation/desktop-root-plan.json'
plan=json.loads(plan_path.read_text())
for r in report['overlay']['packages']:
    expected=next(x for x in plan['packages'] if x['name']==r['name'])
    if expected['sha256']!=r['sha256']:raise ValueError('Runtime does not match candidate archive')
images=[]
for name in ['mesa-native-gdm','mesa-native-gtk']:
    p=lab/(name+'.png')
    if not p.is_file():raise ValueError('Missing visually inspected screenshot: '+name)
    images.append(dict(file=p.relative_to(repo).as_posix(),sha256=sha(p)))
report.update(candidate_plan_sha256=sha(plan_path),serial_log=dict(file=(lab/'serial.log').relative_to(repo).as_posix(),sha256=sha(lab/'serial.log')),screenshots=images,offline=True,media_ejected=True,parent_disk_preserved=True,preservation_checked_at=preserved.get('checked_at'),vm_status=status)
out=target/'validation/mesa-vm-runtime.json'
out.write_text(json.dumps(report,indent=2)+'\n')
print('Actual native Mesa VM runtime evidence collected; fresh_install_tested=false',flush=True)
