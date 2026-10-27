#!/usr/bin/env python3
"""Build locked SpiderMonkey with host tools isolated from the target sysroot."""
import argparse
import contextlib
import difflib
import io
import json
import subprocess

import ki2sessioncandidate as c

ROOT = c.WORK/'desktop-build/mozjs'
SOURCE = ROOT/'firefox-140.1.0'
OUT = ROOT/'build'


def environment():
    env = c.environment()
    env.update(PATH=str(c.WORK/'host-tools/bin')+':'+str(c.VENV/'bin')+':'+str(c.WORK/'rust-1.94.0/bin')+':/usr/bin:/bin',
               CC=str(c.WORK/'host-tools/bin/clang'), CXX=str(c.WORK/'host-tools/bin/clang++'),
               HOST_CC=str(c.WORK/'host-tools/bin/clang'), HOST_CXX=str(c.WORK/'host-tools/bin/clang++'),
               HOST_CFLAGS='-O2', HOST_CXXFLAGS='-O2', HOST_LDFLAGS='',
               PYTHON3=str(c.VENV/'bin/python'), MOZBUILD_STATE_PATH=str(c.WORK/'mozbuild-state'),
               MOZ_NOSPAM='1', AUTOCONF='/usr/bin/autoconf', MACH_BUILD_PYTHON_NATIVE_PACKAGE_SOURCE='none',
               LD_LIBRARY_PATH=str(c.WORK/'host-clang/usr/lib64'),
               CARGO_HOME=str(c.WORK/'mozjs-cargo-home'))
    return env


def configure():
    OUT.mkdir(exist_ok=True)
    env = environment()
    command = [str(SOURCE/'js/src/configure'), '--prefix=/usr', '--libdir=/usr/lib',
               '--host=x86_64-pc-linux-gnu', '--target=x86_64-kiki-linux-gnu',
               '--disable-debug', '--disable-debug-symbols', '--disable-tests', '--disable-jemalloc',
               '--disable-readline', '--with-system-zlib', '--enable-shared-js', '--with-intl-api',
               '--enable-optimize=-O2', '--disable-warnings-as-errors',
               '--with-libclang-path='+str(c.WORK/'host-clang/usr/lib64')]
    c.save(c.TARGET/'validation/mozjs-environment.json', dict(environment=env, configure_command=command,
                source_sha256='d15c65d790e0c371b5c95332141b1bdeb29fefc27f852d22a5f542b6d1bc1922'))
    with (c.TARGET/'validation/mozjs-configure.log').open('w') as stream:
        subprocess.run(command, cwd=OUT, env=env, stdout=stream, stderr=subprocess.STDOUT, check=True)
    print('SpiderMonkey configure passed', flush=True)


def build():
    linker = SOURCE/'build/cargo-linker'
    before = linker.read_text()
    marker = '# KIKI same-architecture host/target linker separation'
    if marker not in before:
        insertion = """# KIKI same-architecture host/target linker separation
link_output = sys.argv[sys.argv.index('-o') + 1] if '-o' in sys.argv else ''
if '/x86_64-unknown-linux-gnu/' not in link_output:
    for key in ('LD', 'LD_CXX', 'LDFLAGS'):
        host_key = 'MOZ_CARGO_WRAP_HOST_' + key
        if host_key in os.environ:
            os.environ['MOZ_CARGO_WRAP_' + key] = os.environ[host_key]

"""
        after = before.replace('SANITIZERS = {', insertion+'SANITIZERS = {')
        linker.write_text(after)
        patch = c.TARGET/'inputs/patches/mozjs-cargo-host-link.patch'
        patch.parent.mkdir(parents=True, exist_ok=True)
        patch.write_text(''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                         fromfile='a/build/cargo-linker', tofile='b/build/cargo-linker')))
        cache = OUT/'release'
        if cache.exists():
            cache.rename(OUT/'release-before-host-link-fix')
    with (c.TARGET/'validation/mozjs-build.log').open('ab') as stream:
        subprocess.run(['make', '-j2'], cwd=OUT, env=environment(), stdout=stream, stderr=subprocess.STDOUT, check=True)
    print('SpiderMonkey build passed', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['configure', 'build'])
    args = parser.parse_args()
    globals()[args.command]()
