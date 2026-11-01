import hashlib,importlib.util,json,os,shutil,subprocess,tarfile
from pathlib import Path
s=importlib.util.spec_from_file_location('context',Path(__file__).with_name('context.py'));a=importlib.util.module_from_spec(s);s.loader.exec_module(a)
root=a.work/'kernel';tree=root/'source';build=root/'build';dest=root/'dest'
recipe=a.ki2build.load_recipes(a.repo/'distro/recipes')['linux'];archive=a.repo/'dist/sources/linux-6.1.187.tar.xz';assert a.ki2build.file_sha256(archive)==recipe.source['sha256']
if not tree.exists():
 tree.mkdir(parents=True)
 with tarfile.open(archive) as t:t.extractall(tree)
src=next(tree.iterdir());build.mkdir(exist_ok=True)
config=Path(__file__).with_name('installed-kernel.config');original=config.read_text();updated=original.replace('# CONFIG_FUSE_FS is not set','CONFIG_FUSE_FS=y');assert updated!=original
if not (build/'.config').exists():(build/'.config').write_text(updated)
subprocess.run([str(src/'scripts/config'),'--file',str(build/'.config'),'--enable','FUSE_FS','--enable','NF_TABLES_INET','--enable','NF_TABLES_IPV4','--enable','NF_TABLES_IPV6'],check=True)
env=dict(os.environ,PATH='/usr/bin:/bin:/usr/sbin:/sbin',LC_ALL='C')
def run(*args):print('$',*map(str,args),flush=True);subprocess.run(list(map(str,args)),env=env,check=True)
run('make','-C',src,'O='+str(build),'olddefconfig')
assert all('CONFIG_'+name+'=y' in (build/'.config').read_text().splitlines() for name in ['NF_TABLES_INET','NF_TABLES_IPV4','NF_TABLES_IPV6'])
run('make','-C',src,'O='+str(build),'-j8','bzImage','modules')
baseline=a.repo/'dist/ki2/desktop-installer-20261027';record=next(v for v in json.loads((baseline/'repo/index.x86_64.json').read_text())['packages'] if v['name']=='linux');package=baseline/'packages/x86_64'/record['file'];assert a.ki2build.file_sha256(package)==record['sha256']
if not dest.exists():a.ki2build.extract_package_rootfs(package,dest)
shutil.copy2(build/'arch/x86/boot/bzImage',dest/'boot/vmlinuz-kiki');shutil.copy2(build/'.config',dest/'boot/config-6.1.187-kiki-vm');shutil.copy2(build/'System.map',dest/'boot/System.map-6.1.187-kiki-vm')
run('make','-C',src,'O='+str(build),'INSTALL_MOD_PATH='+str(dest),'INSTALL_MOD_STRIP=1','modules_install')
for p in (dest/'lib/modules').glob('*/build'):
 if p.is_symlink():p.unlink()
for p in (dest/'lib/modules').glob('*/source'):
 if p.is_symlink():p.unlink()
a.package('linux',recipe.version,dest,[],dict(recipe.source,parent_sha256=record['sha256'],base_config_sha256=a.ki2build.file_sha256(config),fuse='built-in',nftables_inet='built-in'),license=recipe.license,release=recipe.release)
