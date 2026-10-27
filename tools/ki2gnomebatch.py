#!/usr/bin/env python3
"""Build and stage an explicit dependency sequence in the candidate SDK."""
import json
import subprocess
import sys
from pathlib import Path
import ki2sessioncandidate as c
import ki2gnomedesktopbuild as desktop
import ki2desktopgnu as gnu

names=sys.argv[1:]
refresh='--refresh-dependencies' in names
names=[n for n in names if n!='--refresh-dependencies']
for requested in names:
    name=requested.removeprefix('gnu:')
    report=c.TARGET/'validation'/(name+'-build.json')
    if report.exists():
        r=json.loads(report.read_text())
        if c.sha256_file(r['file'])!=r['sha256']:raise ValueError('Changed package '+name)
        print('Reuse verified package',name,flush=True)
    else:
        if requested.startswith('gnu:'):gnu.build(name)
        else:desktop.build(name,refresh_dependencies=refresh)
    subprocess.run(['cp','-a',str(c.WORK/'desktop-build'/name/'dest')+'/.',str(c.SDK)],check=True)
    print('Staged',name,flush=True)
