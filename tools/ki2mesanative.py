#!/usr/bin/env python3
"""Build native Mesa/LLVM in a new candidate without changing the r6 baseline."""
import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request
import ki2sessioncandidate as c
from ki2stage3candidate import read_manifest

OLD_WORK=c.WORK
OLD_TARGET=c.TARGET
c.WORK=Path('/home/tang/kiki-build/mesa-native-20261017')
c.TARGET=c.REPO/'dist/ki2/stage3-6.1.187-mesa-native-candidate-20261017'
c.SDK=c.WORK/'sdk'
c.VENV=c.WORK/'venv'

def fetch(url,path,expected=None):
    if not path.exists():
        temporary=path.with_suffix(path.suffix+'.partial')
        with urllib.request.urlopen(url,timeout=120) as src, temporary.open('wb') as dst:shutil.copyfileobj(src,dst)
        temporary.replace(path)
    digest=c.sha256_file(path)
    if expected and digest!=expected:raise ValueError('Source SHA mismatch: '+str(path))
    return dict(url=url,file=str(path),sha256=digest,bytes=path.stat().st_size)

def setup():
    c.WORK.mkdir(exist_ok=False)
    for n in ['sources','home','cache','host-tools/bin']: (c.WORK/n).mkdir(parents=True,exist_ok=True)
    (c.TARGET/'validation').mkdir(parents=True,exist_ok=False)
    (c.TARGET/'inputs').mkdir()
    subprocess.run(['cp','-a','--reflink=auto',str(OLD_WORK/'sdk'),str(c.SDK)],check=True)
    prior=json.loads((OLD_TARGET/'validation/kiki-mesa-bootstrap-build.json').read_text())
    if c.sha256_file(prior['file'])!=prior['sha256']:raise ValueError('Prior bootstrap SHA mismatch')
    removed=[]
    for f in read_manifest(Path(prior['file']))['files']:
        if f['type']=='dir':continue
        p=c.SDK/f['path'].lstrip('/')
        if p.is_symlink():p.unlink();removed.append(f['path'])
        elif p.is_file():
            if c.sha256_file(p)!=f['sha256']:raise ValueError('SDK bootstrap owner mismatch: '+str(p))
            p.unlink();removed.append(f['path'])
    subprocess.run(['/usr/bin/python3','-m','venv','--without-pip',str(c.VENV)],check=True)
    site=c.VENV/'lib/python3.9/site-packages'
    shutil.copytree(OLD_WORK/'venv/lib/python3.9/site-packages',site,dirs_exist_ok=True,symlinks=True)
    meson=c.VENV/'bin/meson';meson.write_text('#!'+str(c.VENV/'bin/python')+'\nfrom mesonbuild.mesonmain import main\nraise SystemExit(main())\n');meson.chmod(0o755)
    shutil.copy2(OLD_WORK/'host-tools/bin/patchelf',c.WORK/'host-tools/bin/patchelf')
    c.save(c.TARGET/'validation/isolation.json',dict(prior_target=str(OLD_TARGET),work=str(c.WORK),sdk=str(c.SDK),bootstrap_sdk_paths_removed=removed,old_sdk_unchanged=True))
    print('Separate native Mesa SDK and Meson environment prepared',flush=True)

def sources():
    out=c.WORK/'sources';records=[]
    records.append(dict(name='mesa',version='25.2.7',**fetch('https://archive.mesa3d.org/mesa-25.2.7.tar.xz',out/'mesa-25.2.7.tar.xz','b40232a642011820211aab5a9cdf754e106b0bce15044bc4496b0ac9615892ad')))
    records.append(dict(name='mesa-signature',**fetch('https://archive.mesa3d.org/mesa-25.2.7.tar.xz.sig',out/'mesa-25.2.7.tar.xz.sig')))
    release=json.loads(urllib.request.urlopen('https://api.github.com/repos/llvm/llvm-project/releases/tags/llvmorg-21.1.8',timeout=60).read())
    c.save(c.TARGET/'inputs/llvm-release.json',release)
    for filename in ['llvm-project-21.1.8.src.tar.xz','llvm-project-21.1.8.src.tar.xz.sig']:
        asset=next(a for a in release['assets'] if a['name']==filename)
        expected=asset['digest'].removeprefix('sha256:')
        records.append(dict(name='llvm' if filename.endswith('.xz') else 'llvm-signature',version='21.1.8',**fetch(asset['browser_download_url'],out/filename,expected)))
    records.append(dict(name='llvm-release-keys',**fetch('https://releases.llvm.org/release-keys.asc',out/'llvm-release-keys.asc')))
    # Mako is a build-host dependency only; wheel digest comes from official PyPI metadata.
    data=json.loads(urllib.request.urlopen('https://pypi.org/pypi/Mako/1.3.10/json',timeout=60).read())
    c.save(c.TARGET/'inputs/mako-pypi.json',data)
    asset=next(a for a in data['urls'] if a['filename'].endswith('py3-none-any.whl'))
    wheel=out/asset['filename'];records.append(dict(name='host-mako',version='1.3.10',**fetch(asset['url'],wheel,asset['digests']['sha256'])))
    import zipfile
    with zipfile.ZipFile(wheel) as z:z.extractall(c.VENV/'lib/python3.9/site-packages')
    c.save(c.TARGET/'source-lock.json',dict(sources=records,mesa_sha256_authority='https://docs.mesa3d.org/relnotes/25.2.7.html',llvm_sha256_authority='Official LLVM GitHub release asset digest'))
    for name,archive in [('mesa','mesa-25.2.7.tar.xz'),('llvm','llvm-project-21.1.8.src.tar.xz')]:
        dest=c.WORK/'source'/name;dest.mkdir(parents=True,exist_ok=False)
        with tarfile.open(out/archive) as t:
            for member in t:
                parts=Path(member.name).parts
                if member.name.startswith('/') or '..' in parts:raise ValueError('Unsafe source member')
                if name=='llvm' and len(parts)>1 and parts[1] not in ['llvm','cmake','third-party']:continue
                t.extract(member,dest)
    print('Mesa and LLVM official source SHA checks passed; sources extracted',flush=True)

def signatures():
    records=[]
    for name,filename,key_url,fingerprint in [
        ('mesa','mesa-25.2.7.tar.xz','https://docs.mesa3d.org/release-maintainers-keys.asc','57551DE15B968F6341C248F68D8E31AFC32428A6'),
        ('llvm','llvm-project-21.1.8.src.tar.xz','https://releases.llvm.org/release-keys.asc','FFB3368980F3E6BB5737145A316C56D064CACBA5')]:
        p=c.WORK/'sources'/filename
        locked=next(r for r in json.loads((c.TARGET/'source-lock.json').read_text())['sources'] if r['name']==name)
        if c.sha256_file(p)!=locked['sha256']:raise ValueError('Locked source SHA mismatch: '+name)
        result=subprocess.run(['gpg','--homedir',str(c.WORK/'gpg'),'--batch','--status-fd','1','--verify',str(p)+'.sig',str(p)],capture_output=True,text=True,check=True)
        if '[GNUPG:] VALIDSIG '+fingerprint not in result.stdout:raise ValueError('Unexpected signer')
        records.append(dict(name=name,sha256=c.sha256_file(p),signer_fingerprint=fingerprint,key_url=key_url,status=result.stdout))
    c.save(c.TARGET/'validation/source-signatures.json',dict(passed=True,sources=records))
    print('Mesa and LLVM official release signatures verified',flush=True)

def host_python():
    import zipfile
    records=[]
    for name,version in [('packaging','25.0'),('PyYAML','6.0.3')]:
        data=json.loads(urllib.request.urlopen('https://pypi.org/pypi/'+name+'/'+version+'/json',timeout=60).read())
        c.save(c.TARGET/'inputs'/(name+'-pypi.json'),data)
        choices=[a for a in data['urls'] if a['filename'].endswith('.whl')]
        if name=='packaging':asset=next(a for a in choices if a['filename'].endswith('py3-none-any.whl'))
        else:asset=next(a for a in choices if 'cp39-cp39-manylinux' in a['filename'] and a['filename'].endswith('x86_64.whl'))
        wheel=c.WORK/'sources'/asset['filename']
        records.append(dict(name=name,version=version,**fetch(asset['url'],wheel,asset['digests']['sha256'])))
        with zipfile.ZipFile(wheel) as z:z.extractall(c.VENV/'lib/python3.9/site-packages')
    c.save(c.TARGET/'validation/host-python-additions.json',dict(host_only=True,packages=records))
    print('Locked host-only Python dependencies staged',flush=True)

def sdk_tools():
    frozen=c.TARGET/'inputs/distro/scripts'
    shutil.copytree(OLD_TARGET/'inputs/distro/scripts',frozen,dirs_exist_ok=True)
    changed=[]
    for directory in [c.SDK/'usr/bin',c.SDK/'usr/libexec']:
        for p in directory.rglob('*'):
            if p.is_symlink() or not p.is_file() or p.stat().st_size>65536:continue
            data=p.read_bytes()
            if not data.startswith(b'#!'):continue
            updated=data.replace(str(OLD_WORK).encode(),str(c.WORK).encode()).replace(str(OLD_TARGET).encode(),str(c.TARGET).encode())
            if updated!=data:
                before=c.sha256_file(p);p.write_bytes(updated)
                changed.append(dict(path=str(p.relative_to(c.SDK)),before_sha256=before,after_sha256=c.sha256_file(p)))
    pc=c.SDK/'usr/lib/pkgconfig/wayland-scanner.pc'
    data=pc.read_text();updated=data.replace('wayland_scanner=${bindir}/wayland-scanner','wayland_scanner=${pc_sysrootdir}${bindir}/wayland-scanner')
    if updated!=data:
        before=c.sha256_file(pc);pc.write_text(updated)
        changed.append(dict(path=str(pc.relative_to(c.SDK)),before_sha256=before,after_sha256=c.sha256_file(pc)))
    report=c.TARGET/'validation/sdk-build-tool-isolation.json'
    previous=json.loads(report.read_text())['changes'] if report.exists() else []
    env=dict(os.environ,**environment_for_sdk_tools())
    version=subprocess.run([str(c.SDK/'usr/bin/wayland-scanner'),'--version'],env=env,capture_output=True,text=True,check=True)
    located=subprocess.run(['/usr/bin/pkg-config','--variable=wayland_scanner','wayland-scanner'],env=env,capture_output=True,text=True,check=True).stdout.strip()
    if located!=str(c.SDK/'usr/bin/wayland-scanner'):raise ValueError('Wayland scanner pkg-config path escaped SDK')
    index=json.loads((OLD_TARGET/'validated-candidate/repo/index.x86_64.json').read_text())
    record=next(r for r in index['packages'] if r['name']=='wayland')
    archive=OLD_TARGET/'validated-candidate/packages/x86_64'/record['file']
    if c.sha256_file(archive)!=record['sha256']:raise ValueError('Preserved native Wayland archive changed')
    binary=next(f for f in read_manifest(archive)['files'] if f['path']=='/usr/bin/wayland-scanner')
    actual=c.sha256_file(c.SDK/'usr/bin/wayland-scanner.kiki-real')
    if actual!=binary['sha256']:raise ValueError('SDK scanner differs from canonical native package')
    for r in previous+changed:
        if c.sha256_file(OLD_WORK/'sdk'/r['path'])!=r['before_sha256']:raise ValueError('Preserved SDK tool changed: '+r['path'])
    c.save(report,dict(passed=True,changes=previous+changed,old_sdk_unchanged=True,old_sdk_tool_sha256_checked=len(previous+changed),wayland_scanner=dict(version=(version.stdout+version.stderr).strip(),pkg_config_path=located,binary_sha256=actual,canonical_package_sha256=record['sha256']),scope='Generated launchers and pkg-config build variables in the new SDK only'))
    print('New SDK build launchers and Wayland scanner paths isolated',flush=True)

def environment_for_sdk_tools():
    return dict(c.environment(),PATH=str(c.VENV/'bin')+':'+str(c.SDK/'usr/bin')+':/usr/bin:/bin')

def toolchain():
    records=[]
    for path,args in [('/usr/bin/gcc',['--version']),('/usr/bin/g++',['--version']),('/usr/bin/cmake',['--version']),('/usr/bin/ninja',['--version']),(str(c.VENV/'bin/python'),['--version']),(str(c.VENV/'bin/meson'),['--version']),(str(c.WORK/'host-tools/bin/llvm-tblgen'),['--version']),(str(c.WORK/'host-tools/bin/ld.lld'),['--version'])]:
        result=subprocess.run([path]+args,capture_output=True,text=True,check=True)
        records.append(dict(path=path,sha256=c.sha256_file(Path(path).resolve()),version=(result.stdout+result.stderr).strip()))
    sources=[]
    for r in json.loads((c.TARGET/'source-lock.json').read_text())['sources']+json.loads((c.TARGET/'validation/host-python-additions.json').read_text())['packages']:
        if c.sha256_file(r['file'])!=r['sha256']:raise ValueError('Locked source changed: '+r['file'])
        sources.append(r)
    keys=[]
    for filename,url in [('mesa-release-maintainers-keys.asc','https://docs.mesa3d.org/release-maintainers-keys.asc'),('llvm-release-keys.asc','https://releases.llvm.org/release-keys.asc')]:
        p=c.WORK/'sources'/filename;keys.append(dict(url=url,sha256=c.sha256_file(p)))
    defaults=subprocess.run(['gcc','-Q','--help=target'],capture_output=True,text=True,check=True).stdout
    isa=[line.strip() for line in defaults.splitlines() if line.strip().startswith(('-march=','-mtune='))]
    cache=c.WORK/'build/llvm/CMakeCache.txt';discovery={}
    if cache.exists():
        for line in cache.read_text().splitlines():
            if line.startswith(('CMAKE_FIND_ROOT_PATH','ZLIB_INCLUDE_DIR:','ZLIB_LIBRARY_RELEASE:')):
                key,value=line.split('=',1);discovery[key.split(':',1)[0]]=value
        if discovery.get('ZLIB_LIBRARY_RELEASE')!=str(c.SDK/'usr/lib/libz.so'):raise ValueError('Non-native target zlib discovered')
        if discovery.get('CMAKE_FIND_ROOT_PATH_MODE_LIBRARY')!='ONLY':raise ValueError('Target library discovery not isolated')
    c.save(c.TARGET/'validation/build-inputs.json',dict(passed=True,tools=records,source_sha256_rechecked=sources,release_keys=keys,host_tools_only=True,target_runtime_from_source=True,host_cpu_count=os.cpu_count(),target_sysroot=str(c.SDK),target_architecture='x86_64',compiler_default_isa=isa,target_library_discovery=discovery,llvm_backends=['X86']))
    print('Build tool fingerprints and source SHA locks recorded',flush=True)

def llvm():
    signatures()
    src=next((c.WORK/'source/llvm').iterdir())/'llvm'
    out=c.WORK/'build/llvm';out.mkdir(parents=True,exist_ok=True)
    host=c.WORK/'host-tools/bin/llvm-tblgen'
    host.write_text('#!/bin/sh\nexec env LD_LIBRARY_PATH='+str(OLD_WORK/'host-clang/usr/lib64')+' '+str(OLD_WORK/'host-clang/usr/bin/llvm-tblgen')+' "$@"\n');host.chmod(0o755)
    linker=c.WORK/'host-tools/bin/ld.lld'
    if not linker.exists():linker.symlink_to(OLD_WORK/'host-tools/bin/ld.lld')
    subprocess.run([str(host),'--version'],check=True,capture_output=True)
    flags=c.environment()
    options=['-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_INSTALL_PREFIX=/usr','-DCMAKE_INSTALL_LIBDIR=lib',
             '-DCMAKE_SYSTEM_NAME=Linux','-DCMAKE_SYSTEM_PROCESSOR=x86_64','-DCMAKE_C_COMPILER=/usr/bin/gcc','-DCMAKE_CXX_COMPILER=/usr/bin/g++',
             '-DCMAKE_FIND_ROOT_PATH='+str(c.SDK),'-DCMAKE_FIND_ROOT_PATH_MODE_PROGRAM=NEVER','-DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY','-DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY','-DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=ONLY',
             '-DZLIB_INCLUDE_DIR='+str(c.SDK/'usr/include'),'-DZLIB_LIBRARY_RELEASE='+str(c.SDK/'usr/lib/libz.so'),
             '-DCMAKE_C_FLAGS=--sysroot='+str(c.SDK),'-DCMAKE_CXX_FLAGS=--sysroot='+str(c.SDK),
             '-DCMAKE_C_FLAGS_RELEASE=-O2 -DNDEBUG','-DCMAKE_CXX_FLAGS_RELEASE=-O2 -DNDEBUG',
             '-DCMAKE_EXE_LINKER_FLAGS=-B'+str(c.WORK/'host-tools/bin')+'/ '+flags['LDFLAGS'],'-DCMAKE_SHARED_LINKER_FLAGS=-B'+str(c.WORK/'host-tools/bin')+'/ '+flags['LDFLAGS'],
             '-U','CXX_SUPPORTS_CUSTOM_LINKER','-DLLVM_USE_LINKER=lld','-DPython3_EXECUTABLE='+str(c.VENV/'bin/python'),
             '-DLLVM_TABLEGEN='+str(host),'-DLLVM_DEFAULT_TARGET_TRIPLE=x86_64-unknown-linux-gnu','-DLLVM_TARGETS_TO_BUILD=X86',
             '-DLLVM_BUILD_LLVM_DYLIB=ON','-DLLVM_LINK_LLVM_DYLIB=ON','-DLLVM_DYLIB_COMPONENTS=all',
             '-DLLVM_INCLUDE_TESTS=OFF','-DLLVM_INCLUDE_BENCHMARKS=OFF','-DLLVM_INCLUDE_EXAMPLES=OFF','-DLLVM_INCLUDE_DOCS=OFF',
             '-DLLVM_BUILD_TOOLS=OFF','-DLLVM_BUILD_UTILS=OFF','-DLLVM_ENABLE_PROJECTS=','-DLLVM_ENABLE_RUNTIMES=',
             '-DLLVM_ENABLE_TERMINFO=OFF','-DLLVM_ENABLE_LIBEDIT=OFF','-DLLVM_ENABLE_LIBXML2=OFF','-DLLVM_ENABLE_ZSTD=OFF',
             '-DLLVM_ENABLE_ZLIB=FORCE_ON','-DLLVM_ENABLE_FFI=OFF','-DLLVM_ENABLE_RTTI=ON','-DLLVM_ENABLE_ASSERTIONS=OFF',
             '-DLLVM_ENABLE_BACKTRACES=OFF','-DLLVM_ENABLE_DUMP=OFF','-DLLVM_PARALLEL_LINK_JOBS=1']
    log=c.TARGET/'validation/llvm-native-build.log'
    env=dict(PATH=str(c.WORK/'host-tools/bin')+':'+str(c.VENV/'bin')+':/usr/bin:/bin',HOME=str(c.WORK/'home'),LC_ALL='C',PKG_CONFIG_SYSROOT_DIR=str(c.SDK),PKG_CONFIG_LIBDIR=flags['PKG_CONFIG_LIBDIR'])
    def run(args):
        with log.open('ab') as f:
            f.write(('\n$ '+' '.join(args)+'\n').encode());f.flush()
            subprocess.run(args,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
    cache=out/'CMakeCache.txt'
    if not (out/'build.ninja').exists() or not cache.exists() or 'ZLIB_LIBRARY_RELEASE:FILEPATH='+str(c.SDK/'usr/lib/libz.so') not in cache.read_text():
        run(['cmake','-S',str(src),'-B',str(out)]+options)
    c.save(c.TARGET/'validation/llvm-native-config.json',dict(source_sha256=c.sha256_file(c.WORK/'sources/llvm-project-21.1.8.src.tar.xz'),options=options,host_tablegen_sha256=c.sha256_file((OLD_WORK/'host-clang/usr/bin/llvm-tblgen').resolve()),target_sysroot=str(c.SDK),build_only_host_tablegen=True))
    run(['ninja','-C',str(out),'-j2','LLVM','llvm-config','LLVMTableGen'])
    compat=out/'lib/libLLVM-21.so'
    if not compat.exists():compat.symlink_to('libLLVM.so.21.1')
    payload=c.WORK/'payload/llvm';(payload/'usr/lib').mkdir(parents=True,exist_ok=False)
    libraries=list((out/'lib').glob('libLLVM*.so*'))
    for p in libraries:
        if p.is_symlink(): (payload/'usr/lib'/p.name).symlink_to(os.readlink(p))
        elif p.is_file():shutil.copy2(p,payload/'usr/lib'/p.name)
    license_dir=payload/'usr/share/licenses/llvm';license_dir.mkdir(parents=True);shutil.copy2(src/'LICENSE.TXT',license_dir/'LICENSE.TXT')
    source=next(r for r in json.loads((c.TARGET/'source-lock.json').read_text())['sources'] if r['name']=='llvm')
    raw=dict(name='llvm',version='21.1.8',release='1',summary='Native LLVM X86 runtime for Mesa llvmpipe',license='Apache-2.0 WITH LLVM-exception',tier='desktop',architectures=['x86_64'],source=dict(type='url',url=source['url'],sha256=source['sha256']),dependencies=dict(build=['linux-headers'],runtime=['glibc','libstdcxx','libgcc','zlib']),build=dict(system='cmake',configure_options=options))
    with contextlib.redirect_stdout(io.StringIO()):c.package(raw,payload,dict(native_source_build=True,host_libraries_copied=False,source_sha256=source['sha256'],options=options))
    subprocess.run(['cp','-a',str(payload)+'/.',str(c.SDK)],check=True)
    print('Native LLVM runtime built, packaged and staged',flush=True)

def llvm_links():
    previous=json.loads((c.TARGET/'validation/llvm-build.json').read_text())
    payload=c.WORK/'payload/llvm'
    unchanged=[]
    for f in read_manifest(Path(previous['file']))['files']:
        if f['type']=='file':
            if c.sha256_file(payload/f['path'].lstrip('/'))!=f['sha256']:raise ValueError('Unexpected LLVM payload change')
            unchanged.append(dict(path=f['path'],sha256=f['sha256']))
    for root in [c.WORK/'build/llvm/lib',payload/'usr/lib',c.SDK/'usr/lib']:
        link=root/'libLLVM-21.so'
        if link.is_symlink():
            if os.readlink(link)!='libLLVM.so.21.1':raise ValueError('Unexpected LLVM compatibility link')
        elif link.exists():raise ValueError('Unexpected LLVM compatibility file')
        else:link.symlink_to('libLLVM.so.21.1')
    raw=c.build.read_toml(c.TARGET/'recipes/llvm.toml')['recipe'][0];raw['release']=str(int(raw['release'])+1)
    provenance=dict(previous['provenance'],previous_candidate_sha256=previous['sha256'],upstream_install_compatibility_symlink='libLLVM-21.so -> libLLVM.so.21.1',regular_payload_unchanged=True)
    with contextlib.redirect_stdout(io.StringIO()):c.package(raw,payload,provenance)
    c.save(c.TARGET/'validation/llvm-compatibility-layout.json',dict(previous_package_sha256=previous['sha256'],new_release=raw['release'],regular_files_unchanged=unchanged,source_rule='llvm/tools/llvm-shlib/CMakeLists.txt: llvm_install_library_symlink(LLVM-${LLVM_VERSION_MAJOR} ...)',runtime_code_rebuilt=False))
    print('Upstream LLVM compatibility symlink packaged; native runtime code unchanged',flush=True)

def mesa():
    signatures()
    sdk_tools()
    llvm_record=json.loads((c.TARGET/'validation/llvm-build.json').read_text())
    if c.sha256_file(llvm_record['file'])!=llvm_record['sha256']:raise ValueError('Native LLVM changed')
    src=c.WORK/'source/mesa/mesa-25.2.7'
    out=c.WORK/'build/mesa';out.mkdir(parents=True,exist_ok=True)
    tools=out/'tools';tools.mkdir(exist_ok=True)
    frozen=c.TARGET/'inputs/tools';frozen.mkdir(exist_ok=True,parents=True)
    for name in ['ki2-target-run','ki2-target-pkg-config']:
        shutil.copy2(c.REPO/'distro/scripts'/name,frozen/name)
    binary=c.WORK/'build/llvm/bin/llvm-config'
    before=c.sha256_file(binary)
    loader=next(c.SDK/p/'ld-linux-x86-64.so.2' for p in ['usr/lib64','lib64','usr/lib','lib'] if (c.SDK/p/'ld-linux-x86-64.so.2').is_file() and not (c.SDK/p/'ld-linux-x86-64.so.2').is_symlink())
    subprocess.run([str(c.WORK/'host-tools/bin/patchelf'),'--set-interpreter',str(loader),'--force-rpath','--set-rpath',c.environment()['KI2_SYSROOT_LIBRARY_PATH'],str(binary)],check=True)
    c.save(c.TARGET/'validation/llvm-config-host-launcher.json',dict(before_sha256=before,after_sha256=c.sha256_file(binary),interpreter=str(loader),runtime_path=c.environment()['KI2_SYSROOT_LIBRARY_PATH'],scope='Build-only llvm-config; direct exec preserves /proc/self/exe build-tree detection; not part of target runtime package'))
    config=tools/'llvm-config'
    config.write_text('#!/bin/sh\nexec '+str(binary)+' "$@"\n');config.chmod(0o755)
    cross=out/'cross.ini'
    cross.write_text("[binaries]\nc = '/usr/bin/gcc'\ncpp = '/usr/bin/g++'\nar = '/usr/bin/ar'\nstrip = '/usr/bin/strip'\npkg-config = '"+str(frozen/'ki2-target-pkg-config')+"'\nllvm-config = '"+str(config)+"'\nexe_wrapper = ['/bin/sh', '"+str(frozen/'ki2-target-run')+"']\n[host_machine]\nsystem = 'linux'\ncpu_family = 'x86_64'\ncpu = 'x86_64'\nendian = 'little'\n[properties]\nneeds_exe_wrapper = true\n")
    options=['--prefix=/usr','--libdir=lib','--sysconfdir=/etc','--buildtype=release','--wrap-mode=nodownload',
             '-Dplatforms=wayland','-Degl-native-platform=wayland','-Dgallium-drivers=llvmpipe,softpipe,svga,virgl','-Dvulkan-drivers=[]',
             '-Dglx=disabled','-Degl=enabled','-Dgbm=enabled','-Dglvnd=enabled','-Dgles1=disabled','-Dgles2=enabled','-Dopengl=true',
             '-Dllvm=enabled','-Dshared-llvm=enabled','-Dgallium-va=disabled','-Dgallium-vdpau=disabled','-Dvalgrind=disabled',
             '-Dbuild-tests=false','-Dmicrosoft-clc=disabled','-Dxmlconfig=enabled','-Dlibunwind=disabled']
    log=c.TARGET/'validation/mesa-native-build.log'
    env=dict(PATH=str(tools)+':'+str(c.VENV/'bin')+':'+str(c.SDK/'usr/bin')+':/usr/bin:/bin',
             KI2_USE_TARGET_LOADER='1',PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1',
             KI2_REPO_ROOT=str(c.REPO),KI2_BUILD_DIR=str(out))
    if not (out/'meson/build.ninja').exists():c.run(['meson','setup',str(out/'meson'),str(src),'--cross-file',str(cross)]+options,out,log,env)
    c.run(['ninja','-C',str(out/'meson'),'-j2'],out,log,env)
    payload=c.WORK/'payload/mesa';payload.mkdir(exist_ok=False,parents=True)
    c.run(['meson','install','-C',str(out/'meson'),'--no-rebuild'],out,log,dict(env,DESTDIR=str(payload)))
    license_dir=payload/'usr/share/licenses/mesa';license_dir.mkdir(parents=True,exist_ok=True)
    for relative in ['docs/license.rst','docs/license.html','COPYING']:
        if (src/relative).is_file():shutil.copy2(src/relative,license_dir/Path(relative).name)
    source=next(r for r in json.loads((c.TARGET/'source-lock.json').read_text())['sources'] if r['name']=='mesa')
    raw=dict(name='mesa',version='25.2.7',release='1',summary='Native Mesa EGL GBM Wayland llvmpipe and softpipe',license='MIT',tier='desktop',architectures=['x86_64'],source=dict(type='url',url=source['url'],sha256=source['sha256']),dependencies=dict(build=['linux-headers','llvm','libglvnd','libdrm','wayland','wayland-protocols'],runtime=['glibc','libstdcxx','libgcc','zlib','zstd','expat','libdrm','libglvnd','wayland','systemd','llvm']),build=dict(system='meson',configure_options=options))
    with contextlib.redirect_stdout(io.StringIO()):c.package(raw,payload,dict(native_source_build=True,host_libraries_copied=False,source_sha256=source['sha256'],options=options,llvm_package_sha256=llvm_record['sha256'],target_driver_dir='/usr/lib/dri',target_gbm_backend_dir='/usr/lib/gbm'))
    subprocess.run(['cp','-a',str(payload)+'/.',str(c.SDK)],check=True)
    print('Native Mesa built, packaged and staged',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['setup','sources','signatures','host_python','sdk_tools','toolchain','llvm','llvm_links','mesa']);a=p.parse_args();globals()[a.action]()
