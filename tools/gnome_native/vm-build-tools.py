"""Prepare isolated, hash-verified host Python tools for the pinned QEMU build."""
import hashlib,json,subprocess,sys,urllib.request,zipfile
from pathlib import Path
root=Path('/tmp/kiki-build-v1-guests-20261031');venv=root/'host-python'
if not (venv/'bin/python3').exists():subprocess.run([sys.executable,'-m','venv','--system-site-packages','--without-pip',str(venv)],check=True)
site=next((venv/'lib').glob('python*/site-packages'));lock=[]
pins=json.loads(Path(__file__).with_name('vm-host-tools.lock.json').read_text())
for name,version in [('wheel','0.45.1'),('setuptools','75.8.2'),('packaging','24.2'),('pip','24.3.1')]:
 pin=next(r for r in pins if r.get('name')==name and r.get('version')==version)
 row=dict(filename=pin['url'].rsplit('/',1)[-1],url=pin['url'],digests={'sha256':pin['sha256']})
 target=root/row['filename']
 if not target.exists():
  with urllib.request.urlopen(row['url'],timeout=60) as stream,target.open('wb') as out:
   import shutil;shutil.copyfileobj(stream,out)
 if hashlib.sha256(target.read_bytes()).hexdigest()!=row['digests']['sha256']:raise ValueError('host tool wheel SHA mismatch')
 lock.append(dict(name=name,version=version,url=row['url'],sha256=row['digests']['sha256']))
 with zipfile.ZipFile(target) as archive:
  if any(Path(n).is_absolute() or '..' in Path(n).parts for n in archive.namelist()):raise ValueError('invalid wheel path')
  archive.extractall(site)
for wheel in sorted((root/'qemu-11.1.3/python/wheels').glob('*.whl')):
 if hashlib.sha256(wheel.read_bytes()).hexdigest()!=next(r['sha256'] for r in pins if r.get('file')==wheel.name):raise ValueError('bundled QEMU host tool SHA mismatch')
 with zipfile.ZipFile(wheel) as archive:archive.extractall(site)
 lock.append(dict(file=wheel.name,sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),source='pinned QEMU source distribution'))
(root/'host-tools-lock.json').write_text(json.dumps(lock,indent=2)+'\n');print('ISOLATED_HOST_TOOLS_READY',venv)
