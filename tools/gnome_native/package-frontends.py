import importlib.util
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

repo=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(repo/'tools'))
import ki2build
import ki2graphics
import ki2bootiso

spec=importlib.util.spec_from_file_location('apps',Path(__file__).with_name('context.py'))
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
artifacts=Path(__file__).resolve().parent
recipes=ki2build.load_recipes(repo/'distro/recipes')
gtkroot=a.work/'installer-runtime'
if not gtkroot.exists():
    baseline=repo/'dist/ki2/desktop-installer-20261027'
    record=next(r for r in json.loads((baseline/'repo/index.x86_64.json').read_text())['packages'] if r['name']=='kiki-installer-gtk')
    package=baseline/'packages/x86_64'/record['file']
    assert ki2build.file_sha256(package)==record['sha256']
    ki2build.extract_package_rootfs(package,gtkroot)
binary=gtkroot/'usr/bin/kiki-installer-gtk'
ki2graphics.build_installer(repo,binary,'c')
css=gtkroot/'usr/share/kiki-installer-gtk/style.css'
shutil.copyfile(repo/'cmd/kiki-installer-gtk/style.css',css);css.chmod(0o644)
runtime_path=gtkroot/'usr/share/kiki-installer-gtk/runtime-manifest.json'
runtime=json.loads(runtime_path.read_text())
runtime.update(installer_binary_sha256=ki2build.file_sha256(binary),catalog_sha256=ki2build.file_sha256(repo/'distro/sources/ki2ctl/usr/share/ki2/package-groups.json'))
runtime_path.write_text(json.dumps(runtime,indent=2)+'\n')
roots={'kiki-installer-gtk':gtkroot}
for name in ['kiki-installer-tui','ki2ctl']:
    dest=a.work/('payload-'+name)
    if name=='ki2ctl':shutil.copytree(repo/'distro/sources/ki2ctl',dest,symlinks=True,dirs_exist_ok=True)
    else:
        (dest/'usr/bin').mkdir(parents=True,exist_ok=True)
        subprocess.run(['go','build','-buildvcs=false','-trimpath','-o',str(dest/'usr/bin/kiki-installer-tui'),'./cmd/kiki-installer-tui'],cwd=repo,env=dict(a.os.environ,CGO_ENABLED='0'),check=True)
    roots[name]=dest
records={}
for name,dest in roots.items():
    recipe=recipes[name];output=a.packages/ki2build.package_filename(recipe,'x86_64')
    if not output.exists():
        ki2build.create_package(SimpleNamespace(arch='x86_64'),recipe,dest,output,ki2build.stable_hash(ki2build.package_file_manifest(dest)),{})
    records[name]=dict(file=str(output),sha256=ki2build.file_sha256(output),release=recipe.release)
    if name=='kiki-installer-gtk':ki2bootiso.verify_installer_display_name(output)
dest=a.work/'desktop-defaults-dest'
shutil.copytree(repo/'distro/sources/kiki-desktop-defaults',dest,symlinks=True,dirs_exist_ok=True)
wants=dest/'usr/lib/systemd/user/graphical-session-pre.target.wants';wants.mkdir(parents=True,exist_ok=True)
link=wants/'xdg-user-dirs.service'
if not link.is_symlink():link.symlink_to('../xdg-user-dirs.service')
assert a.os.readlink(link)=='../xdg-user-dirs.service'
a.package('kiki-desktop-defaults','0.1.0',dest,['gnome-settings-daemon','gnome-control-center','nautilus','gnome-console','gnome-backgrounds','xdg-desktop-portal-gnome','xdg-user-dirs','ibus-hangul','gsettings-desktop-schemas'],license='GPL-3.0-or-later',release='4')
# Use the native GNOME keyboard panel for the engine's setup action.
baseline=repo/'dist/ki2/desktop-installer-20261027'
record=next(r for r in json.loads((baseline/'repo/index.x86_64.json').read_text())['packages'] if r['name']=='ibus-hangul')
package=baseline/'packages/x86_64'/record['file'];assert ki2build.file_sha256(package)==record['sha256']
dest=a.work/'ibus-hangul-integration'
if not dest.exists():ki2build.extract_package_rootfs(package,dest)
for path in (dest/'usr/share/ibus/component').glob('*.xml'):
    text=path.read_text().replace('/usr/bin/kiki-desktop-tools --settings','/usr/bin/gnome-control-center keyboard')
    path.write_text(text)
a.package('ibus-hangul',record['version'],dest,record['dependencies']['runtime'],dict(parent_sha256=record['sha256'],setup='gnome-control-center keyboard'),license='GPL-2.0-or-later',release='2')
(artifacts/'frontend-packages.json').write_text(json.dumps(records,indent=2)+'\n')
print('Packaged rebuilt frontends and native GNOME defaults',flush=True)
