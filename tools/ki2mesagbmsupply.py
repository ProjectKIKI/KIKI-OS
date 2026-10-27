#!/usr/bin/env python3
"""Add Mesa's matching dlopen GBM backend to the explicit bootstrap provider."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tomli
import ki2sessioncandidate as c
from ki2stage3candidate import read_manifest

name='kiki-mesa-bootstrap'
r=json.loads((c.TARGET/'validation'/(name+'-build.json')).read_text())
if c.sha256_file(r['file'])!=r['sha256']:raise ValueError('Changed bootstrap archive')
verified=subprocess.run(['rpm','-V','mesa-libgbm','mesa-dri-drivers'],capture_output=True,text=True)
if verified.returncode or verified.stdout:raise ValueError('Mesa RPM verification failed')
rpm=subprocess.check_output(['rpm','-q','mesa-libgbm','mesa-dri-drivers'],text=True)
if '25.2.7-4.el9' not in rpm:raise ValueError('Unexpected Mesa provider version')
raw=tomli.loads((c.TARGET/'recipes'/(name+'.toml')).read_text())['recipe'][0]
m=read_manifest(r['file']);raw['release']=str(int(m['release'])+1)
dest=c.WORK/'gbm-backend-repaired'
c.build.extract_package_rootfs(Path(r['file']),dest)
if c.sha256_file('/usr/lib64/libgbm.so.1.0.0')!=c.sha256_file(dest/'usr/lib64/libgbm.so.1.0.0'):raise ValueError('GBM/backend binary provider mismatch')
module=Path('/usr/lib64/gbm/dri_gbm.so');out=dest/str(module).lstrip('/')
out.parent.mkdir(exist_ok=True,parents=True);shutil.copy2(module,out)
c.save(c.TARGET/'validation/repacked-predecessors'/(Path(r['file']).name+'.json'),r)
with contextlib.redirect_stdout(io.StringIO()):c.package(raw,dest,dict(r['provenance'],parent_package_sha256=r['sha256'],gbm_dlopen_backend=dict(path=str(module),sha256=c.sha256_file(module),rpm=rpm,rpm_verify_output=verified.stdout),native_source_build=False))
print('Packaged exact-version verified GBM dlopen backend',flush=True)
