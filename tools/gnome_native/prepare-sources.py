import hashlib
import json
from pathlib import Path
import re
import sys
import tarfile
import urllib.request

out=Path(__file__).resolve().parent
repo=out.parents[1]
metadata=repo/'dist/sources/gnome-build-meta-50.4.tar.xz'
metadata_sha='4a934d828a075e8cc394a68e6a55e59d53979bd8a9394490dd0f23419b5c904e'
assert hashlib.sha256(metadata.read_bytes()).hexdigest()==metadata_sha
work=Path('/tmp/kiki-gnome-native-apps-20261028')
(work/'sources').mkdir(parents=True,exist_ok=True)
record_path=out/'sources.json'
records=json.loads(record_path.read_text()) if record_path.exists() else []
for name in sys.argv[1:]:
    text=(out/'metadata'/(name+'.bst')).read_text()
    url=re.search(r'  url:\s+(\S+)',text)[1].replace('gnome_downloads:','https://download.gnome.org/sources/').replace('github_files:','https://github.com/').replace('kerberos:','https://kerberos.org/')
    checksum=re.search(r'  ref: ([a-f0-9]{64})',text)
    expected=checksum[1] if checksum else None
    if expected is None:
        commit=re.search(r'  ref: .*?-g([a-f0-9]{40})',text)[1]
        project=url.replace('gitlab:','').replace('github:','').removesuffix('.git')
        url='https://codeload.github.com/'+project+'/tar.gz/'+commit
    pinned=next((r for r in records if r['name']==name and r['url']==url),None)
    if pinned:expected=pinned['sha256']
    if not url.startswith('https://'):raise RuntimeError('Unsupported upstream URL '+url)
    path=work/'sources'/url.rsplit('/',1)[1]
    if not path.exists():
        print('Downloading',name,url,flush=True)
        with urllib.request.urlopen(url,timeout=90) as response:path.write_bytes(response.read())
    actual=hashlib.sha256(path.read_bytes()).hexdigest()
    if expected:assert actual==expected,name
    expected=actual
    dest=work/name/'source'
    if not dest.exists():
        dest.mkdir(parents=True)
        with tarfile.open(path) as archive:
            for member in archive:
                if member.name.startswith('/') or '..' in Path(member.name).parts:raise RuntimeError('Unsafe source path')
            archive.extractall(dest)
    records=[r for r in records if r['name']!=name]
    records.append(dict(name=name,url=url,sha256=expected,file=str(path),metadata_sha256=metadata_sha))
    record_path.write_text(json.dumps(records,indent=2)+'\n')
    print('Verified',name,flush=True)
