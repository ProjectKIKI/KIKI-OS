#!/usr/bin/env python3
"""Install SHA-pinned pure Python build tools only into the candidate venv."""
import configparser
import hashlib
import io
import json
from pathlib import Path
import shutil
import sysconfig
import urllib.request
import zipfile
import ki2sessioncandidate as c

records=[]
for name,version in [('docutils','0.21.2'),('argcomplete','3.6.2')]:
    j=json.load(urllib.request.urlopen('https://pypi.org/pypi/'+name+'/'+version+'/json',timeout=30))
    wheel=next(x for x in j['urls'] if x['filename'].endswith('py3-none-any.whl'))
    f=c.WORK/'sources'/wheel['filename']
    if not f.exists():f.write_bytes(urllib.request.urlopen(wheel['url'],timeout=60).read())
    if c.sha256_file(f)!=wheel['digests']['sha256']:raise ValueError('PyPI SHA mismatch')
    site=Path(sysconfig.get_path('purelib'))
    if not site.is_relative_to(c.VENV):raise ValueError('Refuse to install outside candidate venv')
    with zipfile.ZipFile(f) as z:
        for n in z.namelist():
            if n.endswith('/') or '.data/' in n:continue
            if '..' in Path(n).parts or n.startswith('/'):raise ValueError('Unsafe wheel')
            target=site/n;target.parent.mkdir(exist_ok=True,parents=True);target.write_bytes(z.read(n))
        for n in z.namelist():
            if '.data/scripts/' in n and not n.endswith('/'):
                content=z.read(n).decode();content='#!'+str(c.VENV/'bin/python')+'\n'+content.split('\n',1)[1]
                for base in {Path(n).name,Path(n).name.removesuffix('.py')}:
                    out=c.VENV/'bin'/base;out.write_text(content);out.chmod(0o755)
            if n.endswith('.dist-info/entry_points.txt'):
                ini=configparser.ConfigParser();ini.read_string(z.read(n).decode())
                for command,entry in ini.items('console_scripts'):
                    module,function=entry.split(':')
                    out=c.VENV/'bin'/command
                    out.write_text('#!'+str(c.VENV/'bin/python')+'\nfrom '+module+' import '+function+'\nimport sys\nsys.exit('+function+'())\n');out.chmod(0o755)
    records.append(dict(name=name,version=version,url=wheel['url'],sha256=wheel['digests']['sha256'],file=str(f),scope='candidate host venv'))
c.save(c.TARGET/'validation/host-extra-python-lock.json',dict(packages=records))
print('Installed isolated Python tools:',', '.join(r['name'] for r in records))
