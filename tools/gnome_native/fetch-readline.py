import hashlib,json,tarfile,urllib.request
from pathlib import Path
out=Path(__file__).resolve().parent;work=Path('/tmp/kiki-gnome-native-apps-20261028')
url='https://ftp.gnu.org/gnu/readline/readline-8.3.tar.gz'
path=work/'sources/readline-8.3.tar.gz'
if not path.exists():path.write_bytes(urllib.request.urlopen(url,timeout=90).read())
records=json.loads((out/'sources.json').read_text())
expected=next(r['sha256'] for r in records if r['name']=='readline')
assert hashlib.sha256(path.read_bytes()).hexdigest()==expected
root=work/'readline/source'
if not root.exists():
    root.mkdir(parents=True)
    with tarfile.open(path) as t:t.extractall(root)
records=json.loads((out/'sources.json').read_text())
records=[r for r in records if r['name']!='readline']
records.append(dict(name='readline',url=url,file=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),verification='Official GNU HTTPS release; locally pinned SHA-256'))
(out/'sources.json').write_text(json.dumps(records,indent=2)+'\n')
