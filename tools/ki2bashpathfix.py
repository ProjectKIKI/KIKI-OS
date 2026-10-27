#!/usr/bin/env python3
"""Supply the conventional Bash path while preserving the native /usr/bin executable."""
import contextlib
import io
import json
from pathlib import Path
import tomli
import ki2sessioncandidate as c
from ki2stage3candidate import read_manifest

r=json.loads((c.TARGET/'validation/bash-build.json').read_text())
if c.sha256_file(r['file'])!=r['sha256']:raise ValueError('Changed Bash archive')
m=read_manifest(r['file']);raw=tomli.loads((c.TARGET/'recipes/bash.toml').read_text())['recipe'][0]
raw['release']=str(int(m['release'])+1)
dest=c.WORK/'bash-conventional-path'
c.build.extract_package_rootfs(Path(r['file']),dest)
if not (dest/'usr/bin/bash').is_file():raise ValueError('Native Bash executable missing')
(dest/'bin').mkdir(exist_ok=True)
(dest/'bin/bash').symlink_to('../usr/bin/bash')
c.save(c.TARGET/'validation/repacked-predecessors'/(Path(r['file']).name+'.json'),r)
with contextlib.redirect_stdout(io.StringIO()):c.package(raw,dest,dict(r['provenance'],parent_package_sha256=r['sha256'],conventional_shell_path='/bin/bash',bash_elf_unchanged=True))
print('Packaged conventional Bash path',flush=True)
