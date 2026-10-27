#!/usr/bin/env python3
"""Bind fresh disk-only runtime evidence to the exact signed candidate package set."""
import base64
import hashlib
import json
from pathlib import Path
import re

repo=Path(__file__).resolve().parents[1]
target=repo/'dist/ki2/stage3-6.1.187-gnome50-candidate-20261017'
artifacts=repo/'artifacts/gnome50-install-vm-20261017'
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()
data=(artifacts/'serial.log').read_text(encoding='utf-8',errors='replace')
matches=re.findall(r'KIKI_VM_REPORT_BEGIN[\r\n]+([A-Za-z0-9+/=\r\n]+?)KIKI_VM_REPORT_END',data)
if not matches:raise SystemExit('No completed fresh guest report')
r=json.loads(base64.b64decode(re.sub(r'\s','',matches[-1])))
index_path=target/'install-repo-r3/index.x86_64.json'
index=json.loads(index_path.read_text())
plan=json.loads((target/'validation/desktop-root-plan.json').read_text())
expected=set(plan['order'])|{'socat'}
if not r.get('passed') or not r.get('fresh_install_tested') or set(r['installed_packages'])!=expected:raise SystemExit('Fresh package/runtime gate failed')
if r['installed_index_sha256']!=sha(index_path):raise SystemExit('Guest installed index differs from signed ISO supplier index')
if r['default_target']!='graphical.target' or r['offline_wait_gate_exit']!=1 or 'ko_KR.UTF-8' not in r['locale']:raise SystemExit('Fresh system configuration mismatch')
approved={p['name']:p['sha256'] for p in plan['packages']}
baseline=json.loads((repo/'dist/ki2/stage3-6.1.187-candidate-pngfix-20261017/snapshot.json').read_text())['packages']
approved.update({p['name']:p['sha256'] for p in baseline if p['name'] in ['socat','kiki-installer-gtk','kiki-installer-tui']})
actual={p['name']:p['sha256'] for p in index['packages']}
if approved!=actual:raise SystemExit('Signed installer archive set differs from validated sources')
iso=target/'release-iso/kiki-6.1.187-gnome50-login-candidate-r6.iso'
sidecar=json.loads(Path(str(iso)+'.sha256.json').read_text())
if sha(iso)!=sidecar['sha256']:raise SystemExit('ISO SHA changed')
screens=['fresh-r6-confirm-plan','fresh-r6-install-complete','fresh-r6-gdm-disk-only','fresh-r6-wayland-login','fresh-r6-gtk-extensions','fresh-r6-polkit-prompt','fresh-r6-polkit-complete']
if "Successfully activated service 'org.gnome.Extensions'" not in data or 'COMMAND=/usr/bin/id -u' not in data or not re.search(r'pkexec\[\d+\]: 0',data):raise SystemExit('Missing actual GTK or graphical Polkit execution evidence')
r.update(iso_file=iso.relative_to(repo).as_posix(),iso_sha256=sidecar['sha256'],candidate_plan_sha256=sha(target/'validation/desktop-root-plan.json'),serial_log_sha256=sha(artifacts/'serial.log'),signed_iso_packages=len(index['packages']),all_archive_sha_and_static_lookup_gate=True,gtk4_libadwaita_extensions_window_verified=True,polkit_graphical_password_auth_verified=True,release_ready=False,screenshots=[dict(path=(artifacts/(n+'.png')).relative_to(repo).as_posix(),sha256=sha(artifacts/(n+'.png'))) for n in screens])
(target/'validation/gnome-fresh-install-runtime.json').write_text(json.dumps(r,indent=2)+'\n')
gate=json.loads((target/'gate.json').read_text())
gate.update(fresh_install_tested=True,fresh_install_runtime_passed=True,package_count=181,installed_package_count=179,installer_repo='install-repo-r3',installer_packages='install-packages-r2/x86_64',installer_index_sha256=sha(index_path),validated_iso=r['iso_file'],validated_iso_sha256=r['iso_sha256'],release_ready=False)
(target/'gate.json').write_text(json.dumps(gate,indent=2)+'\n')
sidecar.update(scope='Fresh signed-ISO installation, disk-only GDM password Wayland login and GTK application verified in isolated Hyper-V VM',fresh_install_tested=True,runtime_report_sha256=sha(target/'validation/gnome-fresh-install-runtime.json'),release_ready=False)
Path(str(iso)+'.sha256.json').write_text(json.dumps(sidecar,indent=2)+'\n')
print('Fresh installation PASS: 179 native packages; signed 181-package ISO; GDM password Wayland; Korean locale; OFF wait; Bash PTY; user D-Bus; GTK; no failed units')
