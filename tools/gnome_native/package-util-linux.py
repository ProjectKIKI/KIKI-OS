"""Preserve the verified util-linux payload and expose systemd's helper paths."""
import importlib.util,json,subprocess
from pathlib import Path
s=importlib.util.spec_from_file_location('context',Path(__file__).with_name('context.py'))
a=importlib.util.module_from_spec(s);s.loader.exec_module(a)
base=a.repo/'dist/ki2/desktop-installer-20261027'
r=next(p for p in json.loads((base/'repo/index.x86_64.json').read_text())['packages'] if p['name']=='util-linux')
p=base/'packages/x86_64'/r['file'];assert a.ki2build.file_sha256(p)==r['sha256']
dest=a.work/'util-linux-paths/dest'
if not dest.exists():a.ki2build.extract_package_rootfs(p,dest)
subprocess.run(['sh',str(a.repo/'distro/scripts/ki2-util-linux-paths')],env=dict(a.os.environ,KI2_DESTDIR=str(dest)),check=True)
a.package('util-linux',r['version'],dest,r['dependencies']['runtime'],dict(parent_sha256=r['sha256'],mount_helper_paths='/usr/bin and /bin'),license=r['license'],release='3')
