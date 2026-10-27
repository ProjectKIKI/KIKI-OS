#!/usr/bin/env python3
"""Verify the first isolated Xau build in a disposable target-only chroot."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

import ki2build
from ki2integrity import audit_payload, sha256_file
from test_xau_runtime import PROBE


def verify(repo, packages, recipe_dir=None):
    if os.geteuid() != 0:
        raise ValueError('disposable target chroot verification requires root')
    recipes = ki2build.load_recipes(recipe_dir or repo / 'distro/recipes')
    records = []
    with tempfile.TemporaryDirectory(prefix='kiki-firstbuild-runtime-') as directory:
        work = Path(directory)
        root = work / 'root'
        for name in ('glibc', 'linux-headers', 'xorgproto', 'libxau'):
            package = packages / ki2build.package_filename(recipes[name], 'x86_64')
            payload = audit_payload(package)
            if payload['errors']:
                raise ValueError(str(payload['errors']))
            ki2build.extract_package_rootfs(package, root)
            records.append({'name': name, 'file': package.name, 'sha256': sha256_file(package)})
        (root / 'tmp').mkdir(exist_ok=True)
        env = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}
        def run(command):
            return subprocess.check_output(command, env=env, stderr=subprocess.STDOUT, text=True, timeout=60)
        source = work / 'probe.c'
        source.write_text(PROBE)
        flags = ['/usr/bin/gcc', '--sysroot=' + str(root)]
        for sub in ('usr/lib', 'usr/lib64', 'lib', 'lib64'):
            path = str(root / sub)
            flags += ['-B' + path + '/', '-L' + path, '-Wl,-rpath-link,' + path]
        run(flags + [str(source), '-lXau', '-o', str(root / 'probe')])
        loaders = [p for p in root.rglob('ld-linux-x86-64.so.2') if p.is_file() and not p.is_symlink()]
        if len(loaders) != 1:
            raise ValueError('expected one packaged target loader')
        command = ['/usr/sbin/chroot', str(root), '/' + str(loaders[0].relative_to(root)),
                   '--inhibit-cache', '--library-path', '/usr/lib:/usr/lib64:/lib:/lib64']
        listing = run(command + ['--list', '/probe'])
        if not re.search(r'libXau\.so\.6 => /(?:usr/)?lib(?:64)?/', listing):
            raise ValueError('target Xau library not resolved')
        dynamic = run(['/usr/bin/readelf', '-d', str(root / 'usr/lib/libXau.so.6')])
        if re.search(r'\((RPATH|RUNPATH)\)', dynamic):
            raise ValueError('unexpected Xau RPATH/RUNPATH')
        run(command + ['/probe'])
        return {'status': 'pass', 'packages': records, 'target_loader_listing': listing,
                'rpath_runpath': 'absent',
                'operations': ['authority roundtrip', 'lookup', 'lock/unlock', 'truncated record rejection'],
                'scope': 'Disposable chroot using packaged KIKI glibc and new libXau. No VM boot or login claim.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--packages', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--recipe-dir', type=Path)
    args = parser.parse_args()
    result = verify(args.repo_root, args.packages, args.recipe_dir)
    with args.report.open('x') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(result, indent=2))
