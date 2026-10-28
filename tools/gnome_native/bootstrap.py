"""Stage the dated native-GNOME build helpers without overwriting local work."""
import hashlib
from pathlib import Path
import shutil
import tarfile

source = Path(__file__).resolve().parent
repo = source.parents[1]
output = repo / 'artifacts/gnome-native-apps-20261028'
output.mkdir(parents=True, exist_ok=True)
archive = repo / 'dist/sources/gnome-build-meta-50.4.tar.xz'
expected = '4a934d828a075e8cc394a68e6a55e59d53979bd8a9394490dd0f23419b5c904e'
assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected
for path in source.iterdir():
    if path.suffix not in {'.py', '.json', '.ps1', '.config'} or path.name == 'bootstrap.py':
        continue
    target = output / path.name
    if target.exists():
        if target.read_bytes() != path.read_bytes():
            raise FileExistsError('Preserving changed local helper: ' + str(target))
    else:
        shutil.copy2(path, target)
metadata = output / 'metadata'
metadata.mkdir(exist_ok=True)
with tarfile.open(archive) as stream:
    for member in stream:
        if not member.isfile() or not member.name.endswith('.bst'):
            continue
        target = metadata / Path(member.name).name
        # GNOME metadata is an input, never an executable archive extraction.
        if not target.exists():
            target.write_bytes(stream.extractfile(member).read())
print(output)
