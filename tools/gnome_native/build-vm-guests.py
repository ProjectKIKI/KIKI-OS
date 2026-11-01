"""Build VM agents from pinned upstream sources against the existing KIKI SDK."""
import context as c
import hashlib
from pathlib import Path
import shutil
import subprocess
import json

root=Path('/tmp/kiki-build-v1-guests-20261031');source=root/'qemu-11.1.3';archive=root/'qemu-11.1.3.tar.xz'
qemu_sha='5a8289c7940dc77d3873c81a6c29ba3afe1446fc9d36e77fa1658cdbecb84b22'
assert c.ki2build.file_sha256(archive)==qemu_sha
env=dict(c.env);build=root/'qemu-build';build.mkdir(exist_ok=True)
subprocess.run(['/usr/bin/python3',str(Path(__file__).with_name('vm-build-tools.py'))],check=True)
command=[source/'configure','--target-list=','--without-default-features','--enable-guest-agent','--disable-tools','--disable-docs','--disable-rust','--disable-download','--cross-prefix=',
         '--cc=/usr/bin/gcc','--host-cc=/usr/bin/gcc','--python='+str(root/'host-python/bin/python3'),'--prefix=/usr',
         '--extra-cflags='+env['CFLAGS'],'--extra-ldflags='+env['LDFLAGS']]
if not (build/'build.ninja').exists():subprocess.run(list(map(str,command)),cwd=build,env=env,check=True)
subprocess.run(['ninja','-C',str(build),'-j','4','qga/qemu-ga'],env=env,check=True)
stage=root/'qga-stage';(stage/'usr/bin').mkdir(parents=True,exist_ok=True);shutil.copy2(build/'qga/qemu-ga',stage/'usr/bin/qemu-ga')
for rel in ['usr/lib/systemd/system/qemu-guest-agent.service','etc/qemu/qemu-ga.conf']:
 p=stage/rel;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(c.repo/'distro/sources/qemu-guest-agent'/rel,p)
qga=c.package('qemu-guest-agent','11.1.3',stage,['glibc','glib'],source=dict(url='https://download.qemu.org/qemu-11.1.3.tar.xz',sha256=qemu_sha),license='GPL-2.0-or-later')
linux=Path('/tmp/kiki-gnome-native-apps-20261028/kernel/source/linux-6.1.187');hvstage=root/'hyperv-stage';(hvstage/'usr/sbin').mkdir(parents=True,exist_ok=True)
for name in ['hv_kvp_daemon','hv_vss_daemon','hv_fcopy_daemon']:
 subprocess.run(['/usr/bin/gcc',*env['CFLAGS'].split(),'-D_GNU_SOURCE',str(linux/'tools/hv'/name)+'.c','-o',str(hvstage/'usr/sbin'/name),*env['LDFLAGS'].split()],env=env,check=True)
for name in ['hv-kvp-daemon','hv-vss-daemon','hv-fcopy-daemon']:
 p=hvstage/'usr/lib/systemd/system'/(name+'.service');p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(c.repo/'distro/sources/hyperv-daemons/usr/lib/systemd/system'/(name+'.service'),p)
for name in ['hv_get_dhcp_info','hv_get_dns_info','hv_set_ifconfig']:
 p=hvstage/'usr/libexec/hypervkvpd'/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(c.repo/'distro/sources/hyperv-daemons/usr/libexec/hypervkvpd'/name,p);p.chmod(0o755)
for p in (hvstage/'usr/libexec/hypervkvpd').glob('*.sh'):p.unlink()
linux_recipe=c.ki2build.load_recipes(c.repo/'distro/recipes')['linux']
hyperv=c.package('hyperv-daemons','6.1.187',hvstage,['glibc','iproute2','busybox'],source=linux_recipe.source,license='GPL-2.0-only',release='2')
print(json.dumps({'qemu_guest_agent':str(qga),'hyperv_daemons':str(hyperv)},indent=2))
