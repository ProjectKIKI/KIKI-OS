#!/usr/bin/python3
"""Prove the actual Wayland compositor and GTK app load the native Mesa/LLVM payload."""
import base64
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

media=Path(__file__).resolve().parent
plan=json.loads((media/'overlay.json').read_text())
if os.geteuid()!=0 or Path('/sys/class/dmi/id/product_uuid').read_text().strip().lower()!=plan['guest_uuid']:raise SystemExit('Wrong disposable VM')
if os.uname().release!='6.1.187-kiki-vm':raise SystemExit('Unexpected candidate kernel')
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
subprocess.run(['/usr/bin/python3',str(media/'session-report.py')],env=dict(os.environ,KIKI_FRESH_INSTALL_REPORT='0'),check=True,stdout=subprocess.DEVNULL)
session=json.loads(Path('/var/lib/kiki-session-lab/final-runtime.json').read_text())
files=json.loads((media/'native-files.json').read_text())
expected={f['path']:f for f in files if f['type']=='file'}
native_paths={f['path'] for f in files if f['type']!='dir'}
for f in files:
    if f['type']=='symlink' and (not Path(f['path']).is_symlink() or os.readlink(f['path'])!=f['target']):raise SystemExit('Native symlink changed: '+f['path'])
for path,f in expected.items():
    if digest(Path(path))!=f['sha256']:raise SystemExit('Native payload changed: '+path)
old=json.loads((media/'old-bootstrap-manifest.json').read_text())
for f in old['files']:
    if f['type']!='dir' and f['path'] not in native_paths and (Path(f['path']).exists() or Path(f['path']).is_symlink()):raise SystemExit('Bootstrap path remains without native ownership: '+f['path'])
processes=[]
for p in Path('/proc').iterdir():
    if not p.name.isdigit():continue
    try:
        if p.stat().st_uid!=1000:continue
        command=(p/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
        role='gnome-shell' if (p/'comm').read_text().strip()=='gnome-shell' else 'gtk-extensions' if '/org.gnome.Extensions ' in command else None
        if not role:continue
        paths=sorted(set(line.split(None,5)[-1] for line in (p/'maps').read_text().splitlines() if len(line.split(None,5))==6 and line.split(None,5)[-1].startswith('/')))
        loaded=[]
        for raw in paths:
            q=Path(raw)
            if raw.endswith(' (deleted)') and raw.startswith(('/usr/','/lib/','/lib64/')):raise SystemExit('Stale deleted package mapping')
            if raw in expected:loaded.append(dict(path=raw,sha256=digest(q)))
        if not any('libgallium' in f['path'] for f in loaded):raise SystemExit('Process did not load native Gallium: '+role)
        if not any('libLLVM' in f['path'] for f in loaded):raise SystemExit('Process did not load native LLVM: '+role)
        if role=='gtk-extensions' and not any('libgtk-4.so' in raw for raw in paths):raise SystemExit('GTK4 not loaded')
        if role=='gtk-extensions' and not any('libadwaita-1.so' in raw for raw in paths):raise SystemExit('Libadwaita not loaded')
        processes.append(dict(role=role,pid=int(p.name),command=command,native_libraries=loaded,gtk4_loaded=any('libgtk-4.so' in raw for raw in paths),libadwaita_loaded=any('libadwaita-1.so' in raw for raw in paths)))
    except (FileNotFoundError,ProcessLookupError):continue
if {p['role'] for p in processes}!={'gnome-shell','gtk-extensions'}:raise SystemExit('Both compositor and visible GTK app required')
probe=Path('/var/lib/kiki-mesa-lab/mesa-probe')
if digest(probe)!=plan['probe_sha256']:raise SystemExit('Changed probe')
r=subprocess.run([str(probe)],env=dict(os.environ,EGL_PLATFORM='surfaceless',LIBGL_ALWAYS_SOFTWARE='1',MESA_SHADER_CACHE_DISABLE='true'),capture_output=True,text=True,check=True)
render=json.loads(r.stdout)
if 'LLVM 21.1.8' not in render['renderer'] or 'Mesa 25.2.7' not in render['gl_version']:raise SystemExit('Unexpected renderer version')
if render['gbm_backend']=='no-drm-device':raise SystemExit('No actual guest DRM/GBM device verified')
journal=subprocess.run(['journalctl','-b','--no-pager','-o','cat'],capture_output=True,text=True,check=True).stdout
graphics_lines=[line for line in journal.splitlines() if any(s in line.lower() for s in ['libegl','zink','gallium','llvmpipe','gbm','libllvm','renderer'])]
report=dict(passed=True,scope='Native source Mesa/LLVM over preserved r6 installation in a new differencing VM; no fresh install claim',fresh_install_tested=False,vm_id=plan['vm_id'],session=session,processes=processes,native_files_sha256_checked=len(expected),bootstrap_runtime_files_remaining=0,rendering=render,rendering_stderr=r.stderr,graphics_journal=graphics_lines[-200:],zink_warnings_remaining=sum('zink' in line.lower() for line in graphics_lines),overlay=json.loads(Path('/var/lib/kiki-mesa-lab/overlay-result.json').read_text()))
report['captured_at_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
offline=subprocess.run(['/usr/libexec/kiki-wait-online-needed'],capture_output=True,text=True)
if offline.returncode!=1:raise SystemExit('Offline boot wait regression')
report['offline_wait_gate_exit']=offline.returncode
Path('/var/lib/kiki-mesa-lab/runtime.json').write_text(json.dumps(report,indent=2)+'\n')
print('KIKI_MESA_REPORT_BEGIN',flush=True)
print(base64.b64encode(json.dumps(report).encode()).decode(),flush=True)
print('KIKI_MESA_REPORT_END',flush=True)
