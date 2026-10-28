import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tarfile

spec=importlib.util.spec_from_file_location('context',Path(__file__).with_name('context.py'))
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
source=next(r for r in json.loads((a.repo/'dist/ki2/stage3-6.1.187-gnome50-candidate-20261017/gnome50-source-lock.json').read_text())['sources'] if '/glycin/' in r['url'])
archive=Path(source['file']);assert hashlib.sha256(archive.read_bytes()).hexdigest()==source['sha256']
root=a.work/'glycin-gtk4';tree=root/'source'
if not tree.exists():
    tree.mkdir(parents=True)
    with tarfile.open(archive) as t:t.extractall(tree)
src=next(tree.iterdir())
(src/'.cargo').mkdir(exist_ok=True)
(src/'.cargo/config.toml').write_text('[source.crates-io]\nreplace-with="vendored-sources"\n[source.vendored-sources]\ndirectory="'+str(a.original/'cargo-vendor/glycin')+'"\n[net]\noffline=true\n')
linker=root/'target-linker'
linker.write_text('#!/bin/sh\nprevious=\noutput=\nfor argument do\nif [ "$previous" = -o ]; then output=$argument; break; fi\nprevious=$argument\ndone\ncase "$output" in\n*/x86_64-unknown-linux-gnu/*) exec gcc '+a.env['LDFLAGS']+' "$@" ;;\n*) exec gcc "$@" ;;\nesac\n')
linker.chmod(0o755)
target=root/'target'
extra=dict(PATH=str(a.original/'rust-1.94.0/bin')+':'+a.env['PATH'],CARGO_TARGET_DIR=str(target),
           LD_LIBRARY_PATH=str(a.original/'rust-1.94.0/lib'),
           CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER=str(linker),CARGO_BUILD_JOBS='4',CARGO_NET_OFFLINE='true',
           PKG_CONFIG_ALLOW_CROSS='1',RUSTFLAGS='')
import os
os.chdir(src)
a.run(['cargo','build','--locked','--offline','--release','--target','x86_64-unknown-linux-gnu','-p','libglycin-gtk4'],extra)
dest=root/'dest';lib=dest/'usr/lib';lib.mkdir(parents=True,exist_ok=True)
binary=lib/'libglycin-gtk4-2.so.0'
shutil.copy2(target/'x86_64-unknown-linux-gnu/release/libglycin_gtk4.so',binary)
a.run([a.tools/'patchelf','--set-soname',binary.name,binary])
link=lib/'libglycin-gtk4-2.so'
if not link.exists():link.symlink_to(binary.name)
headers=dest/'usr/include/glycin-gtk4-2';headers.mkdir(parents=True,exist_ok=True)
shutil.copy2(src/'libglycin/include/glycin-gtk4.h',headers/'glycin-gtk4.h')
pc=lib/'pkgconfig';pc.mkdir(exist_ok=True)
(pc/'glycin-gtk4-2.pc').write_text('prefix=/usr\nlibdir=${prefix}/lib\nincludedir=${prefix}/include\nName: glycin-gtk4\nDescription: GNOME Glycin GTK4 integration\nVersion: 2.1.5\nRequires: glycin-2 gtk4\nLibs: -L${libdir} -lglycin-gtk4-2\nCflags: -I${includedir}/glycin-gtk4-2\n')
a.package('glycin-gtk4','2.1.5',dest,['glycin','gtk','glib','libgcc'],source)
