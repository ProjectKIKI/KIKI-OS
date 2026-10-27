#!/usr/bin/env python3
"""Build session repairs in a dedicated SDK without changing legacy artifacts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
from types import SimpleNamespace

import ki2build as build
from ki2integrity import audit_payload, sha256_file
from ki2stage3candidate import recipe_toml

REPO = Path('/mnt/e/dev/KIKI-OS')
BASE = REPO / 'dist/ki2/stage3-6.1.187-candidate-pngfix-20261017'
TARGET = REPO / 'dist/ki2/stage3-6.1.187-gnome50-candidate-20261017'
WORK = Path('/home/tang/kiki-build/gnome50-session-20261017')
SDK = WORK / 'sdk'
VENV = WORK / 'venv'


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary=path.with_name(path.name+'.tmp-'+str(os.getpid()))
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def environment():
    libraries = ':'.join(str(SDK / p) for p in ['usr/lib', 'usr/lib64', 'lib', 'lib64', 'usr/lib/pulseaudio','usr/lib/mutter-18','usr/lib/gnome-shell'])
    return dict(PATH=str(VENV / 'bin') + ':/usr/bin:/bin:/usr/sbin', HOME=str(WORK / 'home'),
                LC_ALL='C', TZ='UTC', PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1',
                XDG_CACHE_HOME=str(WORK / 'cache'),
                KI2_SYSROOT=str(SDK), KI2_SYSROOT_LIBRARY_PATH=libraries,
                GI_TYPELIB_PATH=':'.join(str(SDK/p) for p in ['usr/lib/girepository-1.0','usr/lib64/girepository-1.0','usr/lib/gjs/girepository-1.0','usr/lib/mutter-18']),
                PKG_CONFIG_SYSROOT_DIR=str(SDK), PKG_CONFIG_LIBDIR=':'.join(str(SDK / p) for p in
                ['usr/lib/pkgconfig', 'usr/lib64/pkgconfig', 'usr/share/pkgconfig', 'lib/pkgconfig', 'lib64/pkgconfig']),
                CC='gcc', CXX='g++', AR='ar', RANLIB='ranlib',
                CPPFLAGS='--sysroot=' + str(SDK),
                CFLAGS='--sysroot=' + str(SDK) + ' -O2 -pipe -fstack-protector-strong -D_FORTIFY_SOURCE=2',
                CXXFLAGS='--sysroot=' + str(SDK) + ' -O2 -pipe -fstack-protector-strong -D_FORTIFY_SOURCE=2',
                LDFLAGS='--sysroot=' + str(SDK) + ' ' + ' '.join('-B'+str(SDK / p)+'/' for p in ['usr/lib64','lib64']) +
                ' ' + ' '.join('-L'+p+' -Wl,-rpath-link,'+p for p in libraries.split(':')) + ' -Wl,-z,relro,-z,now')


def run(command, cwd, log, extra=None):
    env = environment()
    if extra:
        env.update(extra)
    with log.open('ab') as stream:
        stream.write(('\n$ ' + ' '.join(command) + '\n').encode()); stream.flush()
        subprocess.run(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT, check=True)


def source(name):
    catalog = json.loads((BASE / 'recipes/catalog.json').read_text())
    raw = next(r for r in catalog['recipes'] if r['name'] == name)
    entry = raw['source']
    archive = BASE / 'sources' / entry.get('file', entry['url'].rsplit('/', 1)[-1])
    if sha256_file(archive) != entry['sha256']:
        raise ValueError('source SHA mismatch: ' + name)
    cached = WORK / 'sources' / archive.name
    if not cached.exists():
        shutil.copyfile(archive, cached)
    if sha256_file(cached) != entry['sha256']:
        raise ValueError('local source SHA mismatch: ' + name)
    dest = WORK / 'build' / name / 'source'
    dest.mkdir(parents=True, exist_ok=False)
    with tarfile.open(cached) as tar:
        # Inputs are verified official archives; reject paths escaping the source root.
        for m in tar.getmembers():
            if m.name.startswith('/') or '..' in Path(m.name).parts:
                raise ValueError('unsafe source path')
        tar.extractall(dest)
    directories = [p for p in dest.iterdir() if p.is_dir()]
    if len(directories) != 1:
        raise ValueError('expected one source directory')
    return raw, directories[0]


def package(raw, payload, provenance):
    if not raw['version'] or raw['version'].startswith('.'):
        raise ValueError('Invalid candidate package version: '+raw['version'])
    if raw['name'] in raw.get('dependencies', {}).get('runtime', []):
        raise ValueError('Self dependency in candidate package: '+raw['name'])
    for path in payload.rglob('*'):
        if path.relative_to(payload).parts[0] in ['home','tmp','mnt'] and (path.is_file() or path.is_symlink()):
            raise ValueError('Build/user path in candidate payload: '+str(path.relative_to(payload)))
    patcher=WORK/'host-tools/bin/patchelf'
    cleanup=[]
    if patcher.exists():
        for path in payload.rglob('*'):
            if path.is_symlink() or not path.is_file():continue
            with path.open('rb') as stream:
                if stream.read(4)!=b'\x7fELF':continue
            result=subprocess.run([str(patcher),'--print-rpath',str(path)],capture_output=True,text=True)
            if result.returncode:continue
            previous=result.stdout.strip()
            target_paths=[p[len(str(SDK)):] if p.startswith(str(SDK)+'/') else p for p in previous.split(':')]
            remaining=':'.join(p for p in target_paths if p and not any(x in p for x in ['/home/','/mnt/','/tmp/']))
            if previous==remaining:continue
            if raw['name']=='nss':raise ValueError('NSS ELF correction requires regenerating module signatures')
            mode=stat.S_IMODE(path.stat().st_mode);before=sha256_file(path)
            command=['--set-rpath',remaining] if remaining else ['--remove-rpath']
            subprocess.run([str(patcher)]+command+[str(path)],check=True);path.chmod(mode)
            cleanup.append(dict(path='/'+str(path.relative_to(payload)),before_sha256=before,after_sha256=sha256_file(path),rpath_before=previous,rpath_after=remaining))
    if cleanup:
        provenance=dict(provenance,build_rpath_cleanup=cleanup,elf_postprocessor_sha256=sha256_file(patcher))
    recipe_dir = TARGET / 'recipes'
    recipe_dir.mkdir(parents=True, exist_ok=True)
    recipe_path=recipe_dir/(raw['name']+'.toml')
    temporary=recipe_path.with_suffix('.toml.tmp')
    temporary.write_text(recipe_toml([raw]))
    temporary.replace(recipe_path)
    recipe = build.load_recipes(recipe_dir)[raw['name']]
    key = build.stable_hash({'recipe': recipe.digest, 'provenance': provenance})
    output = WORK / 'packages' / build.package_filename(recipe, 'x86_64')
    output.parent.mkdir(exist_ok=True)
    if output.exists():
        raise FileExistsError(output)
    build.create_package(SimpleNamespace(arch='x86_64'), recipe, payload, output, key, {})
    audit = audit_payload(output)
    if audit['errors']:
        raise ValueError(str(audit['errors']))
    record = dict(name=raw['name'], file=str(output), sha256=sha256_file(output),
                  recipe_digest=recipe.digest, provenance=provenance, runtime_validated=False)
    save(TARGET / 'validation' / (raw['name'] + '-build.json'), record)
    print(json.dumps(record, indent=2), flush=True)


def bash():
    raw, src = source('bash')
    log = TARGET / 'validation/bash-build.log'
    manifest = json.loads((TARGET / 'validation/bash-official-patches.json').read_text())
    patches = []
    for n in range(1, 38):
        p = WORK / 'sources' / ('bash52-%03d' % n)
        record = next(x for x in manifest['sources'] if x['file'] == str(p))
        if sha256_file(p) != record['sha256']:
            raise ValueError('patch changed')
        run(['patch', '-p0', '--batch', '-i', str(p)], src, log)
        patches.append(record)
    raw.update(version='5.2.37', release='3')
    raw['dependencies']['build'] = ['linux-headers', 'ncurses']
    raw['build'] = dict(system='gnu', configure_options=['--prefix=/usr', '--without-bash-malloc'],
                        patches=[x['file'] for x in patches], env=environment())
    build_dir = src.parent / 'build'; build_dir.mkdir()
    payload = src.parent / 'dest'; payload.mkdir()
    run([str(src/'configure'), '--prefix=/usr', '--build=x86_64-pc-linux-gnu',
         '--host=x86_64-kiki-linux-gnu', '--without-bash-malloc'], build_dir, log,
        {'bash_cv_strcoll_broken':'no', 'bash_cv_func_sigsetjmp':'present', 'bash_cv_job_control_missing':'present'})
    run(['make', '-j4'], build_dir, log)
    run(['make', 'DESTDIR='+str(payload), 'install'], build_dir, log)
    package(raw, payload, dict(source_sha256=raw['source']['sha256'], patches=patches,
            signature_fingerprint='7C0135FB088AAF6C66C650B9BB5869F064EA74AB',
            sdk=str(SDK), compiler=sha256_file('/usr/bin/gcc')))


def systemd():
    raw, src = source('systemd')
    raw['release'] = '6'
    raw['dependencies']['build'] = ['linux-pam', 'linux-headers']
    raw['dependencies']['runtime'].append('linux-pam')
    log = TARGET / 'validation/systemd-build.log'
    for relative in raw['build'].get('patches', []):
        frozen = TARGET / 'inputs' / relative
        frozen.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / relative, frozen)
        run(['patch', '-p1', '--batch', '-i', str(frozen)], src, log)
    out = src.parent / 'build'; out.mkdir()
    payload = src.parent / 'dest'; payload.mkdir()
    wrapper = out / 'target-run'
    shutil.copy2(REPO / 'distro/scripts/ki2-target-run', wrapper)
    cross = out / 'cross.ini'
    cross.write_text("[binaries]\nc = 'gcc'\ncpp = 'g++'\nar = 'ar'\nstrip = 'strip'\npkg-config = '/usr/bin/pkg-config'\nexe_wrapper = ['" + str(wrapper) + "']\n[host_machine]\nsystem = 'linux'\ncpu_family = 'x86_64'\ncpu = 'x86_64'\nendian = 'little'\n[properties]\nneeds_exe_wrapper = true\n")
    options = ['-Ddefault-dnssec=no', '-Dfirstboot=false', '-Dmachined=true', '-Dman=false',
               '-Dtests=false', '-Ddbus-interfaces-dir=no', '-Ddbuspolicydir=/usr/share/dbus-1/system.d',
               '-Ddbussystemservicedir=/usr/share/dbus-1/system-services',
               '-Ddbussessionservicedir=/usr/share/dbus-1/services', '-Dpam=true', '-Dpamconfdir=/etc/pam.d']
    raw['build']['configure_options'] = options
    raw['build']['env'] = environment()
    run(['meson', 'setup', str(out/'meson'), str(src), '--cross-file', str(cross), '--prefix=/usr',
         '--libdir=lib', '--sysconfdir=/etc', '--localstatedir=/var', '--buildtype=release',
         '--wrap-mode=nofallback'] + options, out, log,
        {'CFLAGS': environment()['CFLAGS'] + ' -Wno-error=shift-overflow'})
    run(['ninja', '-C', str(out/'meson'), '-j4'], out, log)
    run(['meson', 'install', '-C', str(out/'meson'), '--no-rebuild'], out, log, {'DESTDIR': str(payload)})
    if not (payload/'usr/lib/security/pam_systemd.so').exists():
        raise ValueError('PAM module missing after install')
    package(raw, payload, dict(source_sha256=raw['source']['sha256'], sdk=str(SDK), pam_enabled=True))


def shadow():
    raw, src = source('shadow')
    raw['release'] = '2'
    raw['dependencies']['build'] = ['linux-pam', 'linux-headers']
    raw['dependencies']['runtime'] = list(dict.fromkeys(raw['dependencies']['runtime'] + ['linux-pam']))
    log = TARGET / 'validation/shadow-build.log'
    out = src.parent / 'build'; out.mkdir()
    payload = src.parent / 'dest'; payload.mkdir()
    options = ['--prefix=/usr', '--sysconfdir=/etc', '--with-libpam', '--without-selinux',
               '--without-acl', '--without-libbsd', '--without-bcrypt', '--without-libcrack']
    raw['build'] = dict(system='gnu', configure_options=options, env=environment())
    run([str(src/'configure'), '--build=x86_64-pc-linux-gnu', '--host=x86_64-kiki-linux-gnu'] + options, out, log)
    run(['make', '-j4'], out, log)
    run(['make', 'DESTDIR='+str(payload), 'install'], out, log)
    package(raw, payload, dict(source_sha256=raw['source']['sha256'], sdk=str(SDK), pam_enabled=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['bash', 'systemd', 'shadow'])
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError('Linux root required to preserve package ownership')
    globals()[args.command]()
