import hashlib,importlib.util,json,os,shutil,sys,tarfile
from pathlib import Path
spec=importlib.util.spec_from_file_location('context',Path(__file__).with_name('context.py'))
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
baseline=a.repo/'dist/ki2/desktop-installer-20261027'
index=json.loads((baseline/'repo/index.x86_64.json').read_text())['packages']
for name in sys.argv[1:]:
    recipe=a.ki2build.load_recipes(a.repo/'distro/recipes')[name if name=='libxcrypt' else 'libgcc' if name=='libatomic' else 'e2fsprogs']
    archive=a.repo/'dist/sources'/Path(recipe.source['url']).name
    assert a.ki2build.file_sha256(archive)==recipe.source['sha256']
    root=a.work/(name+'-runtime');tree=root/'source';dest=root/'dest'
    if not tree.exists():
        tree.mkdir(parents=True)
        with tarfile.open(archive) as t:t.extractall(tree)
    src=next(tree.iterdir())
    if name=='libxcrypt':
        old=next(v for v in index if v['name']==name);package=baseline/'packages/x86_64'/old['file']
        assert a.ki2build.file_sha256(package)==old['sha256']
        if not dest.exists():a.ki2build.extract_package_rootfs(package,dest)
        if not (dest/'usr/lib/libcrypt.so.2.0.0').exists():
            a.run(['sh',a.repo/'distro/scripts/ki2-libxcrypt-abi2'],dict(KI2_BUILD_DIR=str(root),KI2_SOURCE_DIR=str(src),KI2_DESTDIR=str(dest),KI2_JOBS='4',CC='gcc --sysroot='+str(a.sdk)))
        a.package(name,recipe.version,dest,['glibc'],dict(recipe.source,parent_sha256=old['sha256']),license=recipe.license,release='5')
    elif name=='libatomic':
        build=root/'build';build.mkdir(exist_ok=True);os.chdir(build)
        if not (build/'Makefile').exists():a.run([src/'libatomic/configure','--prefix=/usr','--libdir=/usr/lib','--build=x86_64-pc-linux-gnu','--host=x86_64-kiki-linux-gnu','--disable-multilib','--enable-shared','--disable-static'],dict(CC='gcc --sysroot='+str(a.sdk)))
        a.run(['make','-j4']);a.run(['make','DESTDIR='+str(dest),'install'])
        for folder in ['usr/lib','usr/lib64']:
            for path in (dest/folder).glob('*.la'):path.unlink()
        license_dir=dest/'usr/share/licenses/libatomic';license_dir.mkdir(parents=True,exist_ok=True)
        for filename in ['COPYING3','COPYING.RUNTIME']:shutil.copy2(src/filename,license_dir/filename)
        a.package(name,recipe.version,dest,['glibc'],recipe.source,license='GPL-3.0-or-later WITH GCC-exception-3.1',release='2')
        os.chdir(a.repo)
    elif name=='libcom-err':
        build=root/'build';build.mkdir(exist_ok=True);os.chdir(build)
        if not (build/'Makefile').exists():a.run([src/'configure','--prefix=/usr','--libdir=/usr/lib','--build=x86_64-pc-linux-gnu','--host=x86_64-kiki-linux-gnu','--enable-elf-shlibs','--disable-libblkid','--disable-libuuid','--disable-uuidd','--disable-fsck'],dict(CC='gcc --sysroot='+str(a.sdk)))
        a.run(['make','-C',build/'lib/et','-j4'])
        lib=dest/'usr/lib';lib.mkdir(parents=True,exist_ok=True)
        shared=next((build/'lib').rglob('libcom_err.so.2.1'));shutil.copy2(shared,lib/shared.name)
        for alias in ['libcom_err.so.2','libcom_err.so']:
            if not (lib/alias).exists():(lib/alias).symlink_to(shared.name)
        license=dest/'usr/share/licenses/libcom-err';license.mkdir(parents=True,exist_ok=True);shutil.copy2(src/'lib/et/com_err.texinfo',license/'com_err.texinfo')
        a.package(name,recipe.version,dest,['glibc'],recipe.source,license='MIT',release='1')
        os.chdir(a.repo)
    else:raise ValueError(name)
