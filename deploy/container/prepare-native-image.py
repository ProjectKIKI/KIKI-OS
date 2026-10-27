"""Install hash-locked build-host dependencies; no KIKI runtime libraries."""
from pathlib import Path
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile

prep=Path('/opt/kiki-prep')
root=Path('/opt/kiki-host')
rust=json.loads((prep/'rust-sources.json').read_text())
for record in rust['components']:
    archive=Path('/opt/kiki-rust-dist')/record['url'].rsplit('/',1)[1]
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==record['sha256']
    with tempfile.TemporaryDirectory(prefix='kiki-rust-') as temporary:
        with tarfile.open(archive,'r:xz') as t:
            top=Path(t.getmembers()[0].name).parts[0]
            t.extractall(temporary,filter='data')
        subprocess.run(['/bin/sh',str(Path(temporary)/top/'install.sh'),
                        '--prefix=/opt/kiki-host/rust-1.94.0','--disable-ldconfig'],check=True)
python=Path('/usr/bin/python3.9')
tools=['/usr/bin/'+s for s in ['gcc','g++','as','ld','ar','strip','ninja','pkg-config','cmake','llvm-tblgen','llvm-config','ld.lld']]
tools+=['/opt/kiki-host/rust-1.94.0/bin/rustc','/opt/kiki-host/rust-1.94.0/bin/cargo','/opt/kiki-host/bin/patchelf']
profile={'schema':'kiki-build-env-v1','id':'container-native-20261023','root':str(root),
         'python':str(python),'python_version':platform.python_version(),
         'python_sha256':hashlib.sha256(python.read_bytes()).hexdigest(),
         'lock':'host-python.lock','tools':tools,
         'policy':{'system_site_packages':False,'user_site_packages':False,'wheel_only':True}}
(prep/'profile.json').write_text(json.dumps(profile,indent=2))
subprocess.run([str(python),'-I','-B',str(prep/'ki2buildenv.py'),'prepare','--profile',str(prep/'profile.json')],check=True)
