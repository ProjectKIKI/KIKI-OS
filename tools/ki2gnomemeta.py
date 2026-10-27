#!/usr/bin/env python3
"""Package the explicit minimal GNOME 50 Wayland desktop selection."""
import contextlib
import io
import json
import ki2sessioncandidate as c
from ki2gnomeroot import DESKTOP

dest=c.WORK/'gnome-desktop-meta';dest.mkdir(exist_ok=False)
p=dest/'usr/share/kiki/gnome50-candidate.json';p.parent.mkdir(parents=True)
p.write_text(json.dumps(dict(session='GNOME 50 Wayland',display_manager='GDM',roots=DESKTOP,scope='Minimum login candidate; GSD schemas only, bootstrap Mesa, no Xwayland/PipeWire desktop support claim'),indent=2)+'\n')
raw=dict(name='kiki-gnome-desktop',version='0.1.0',release='1',summary='Minimal KIKI GNOME 50 GDM Wayland session',license='GPL-3.0-or-later',tier='desktop',architectures=['x86_64'],source=dict(type='local',path=str(dest)),dependencies=dict(build=[],runtime=DESKTOP),build=dict(system='copy'))
with contextlib.redirect_stdout(io.StringIO()):c.package(raw,dest,dict(explicit_roots=DESKTOP,minimal_login_candidate=True,full_gsd_daemons=False,mesa_native_source_build=False))
print('Packaged explicit minimal desktop selection',flush=True)
