import hashlib
import json
from pathlib import Path
import re
import tarfile
import urllib.request

out=Path(__file__).resolve().parent
work=Path('/tmp/kiki-gnome-native-apps-20261028')
record_path=out/'sources.json'
records=json.loads(record_path.read_text())
def fetch(name,url,expected=None,origin=None):
    pinned=next((r for r in records if r['name']==name and r['url']==url),None)
    if pinned:expected=pinned['sha256']
    path=work/'sources'/(name+'-'+url.rsplit('/',1)[1].replace('?','_'))
    if not path.exists():
        print('Downloading',name,url,flush=True)
        with urllib.request.urlopen(url,timeout=90) as response:path.write_bytes(response.read())
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if expected:assert digest==expected,name
    root=work/name/'source'
    if not root.exists():
        root.mkdir(parents=True)
        with tarfile.open(path) as archive:archive.extractall(root)
    records[:]=[r for r in records if r['name']!=name]
    records.append(dict(name=name,url=url,sha256=digest,file=str(path),upstream=origin,
                        verification='Pinned upstream commit/archive; HTTPS SHA-256 recorded'))
    record_path.write_text(json.dumps(records,indent=2)+'\n')
    return root

for name,project in [('NetworkManager','NetworkManager/NetworkManager'),('ModemManager','linux-mobile-broadband/ModemManager')]:
    text=(out/'metadata'/(name+'.bst')).read_text()
    commit=re.search(r'  ref: .*?-g([a-f0-9]{40})',text)[1]
    fetch(name,'https://codeload.github.com/'+project+'/tar.gz/'+commit,origin=dict(gnome_metadata_sha256='4a934d828a075e8cc394a68e6a55e59d53979bd8a9394490dd0f23419b5c904e',commit=commit))

commit='da39a00d43df80bcf17898c2ebf7035df59a6a39'
root=fetch('freedesktop-sdk-metadata','https://gitlab.com/freedesktop-sdk/freedesktop-sdk/-/archive/'+commit+'/freedesktop-sdk-'+commit+'.tar.gz',origin=dict(commit=commit))
root=next(root.iterdir())
for name in ['cups-base','cracklib','libwacom','pwquality','libndp']:
    text=(root/'elements/components'/(name+'.bst')).read_text()
    (out/'metadata'/(name+'.bst')).write_text(text)
    print(name,text,flush=True)
    if 'github:' in text:
        project=re.search(r'  url: github:(.*)\.git',text)[1]
        source_commit=re.search(r'  ref: .*?-g([a-f0-9]{40})',text)[1]
        fetch(name,'https://codeload.github.com/'+project+'/tar.gz/'+source_commit,origin=dict(freedesktop_sdk_commit=commit,source_commit=source_commit))
