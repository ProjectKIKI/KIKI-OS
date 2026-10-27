#!/usr/bin/env python3
"""Pinned, opt-in launcher around the existing builder; no legacy cache writes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zipfile


class BuildEnvironmentError(RuntimeError):
    pass


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def stable(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def config(path):
    path = Path(path).resolve()
    p = json.loads(path.read_text())
    lock = json.loads((path.parent / p['lock']).read_text())
    if p.get('schema') != 'kiki-build-env-v1' or lock.get('schema') != 'kiki-python-wheel-lock-v1':
        raise BuildEnvironmentError('unsupported environment schema')
    root = Path(p['root'])
    if not root.is_absolute() or root.resolve() != root or root in (Path('/'), Path.home()):
        raise BuildEnvironmentError('environment root must be a dedicated absolute directory')
    return p, lock, root


def clean_environment(root):
    return {'PATH': str(root / 'venv/bin') + ':/usr/bin:/bin', 'LC_ALL': 'C', 'TZ': 'UTC',
            'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONHASHSEED': '0',
            'XDG_CONFIG_HOME': str(root / 'config'), 'XDG_CACHE_HOME': str(root / 'cache/xdg'),
            'TMPDIR': str(root / 'tmp')}


def capture(args, env):
    return subprocess.check_output(args, text=True, env=env, stderr=subprocess.STDOUT).strip()


def base_check(p, env):
    if sys.platform != 'linux':
        raise BuildEnvironmentError('pinned environment requires Linux')
    if sha(p['python']) != p['python_sha256']:
        raise BuildEnvironmentError('base Python SHA-256 changed')
    if capture([p['python'], '-I', '-c', 'import platform;print(platform.python_version())'], env) != p['python_version']:
        raise BuildEnvironmentError('base Python version mismatch')


def file_inventory(directory, exclude=()):
    result = {}
    for current, dirs, files in os.walk(directory):
        dirs[:] = sorted(d for d in dirs if d not in set(exclude) | {'__pycache__'})
        for name in sorted(files):
            path = Path(current) / name
            if path.suffix != '.pyc' and path.is_file():
                result[str(path)] = sha(path)
    return result


def tool_inventory(p, env):
    paths = {Path(x).resolve() for x in p['tools']} | {Path(p['python']).resolve()}
    for compiler in ('/usr/bin/gcc', '/usr/bin/g++'):
        for name in ('cc1', 'cc1plus', 'collect2'):
            path = Path(capture([compiler, '-print-prog-name=' + name], env))
            if path.is_absolute() and path.is_file():
                paths.add(path.resolve())
    for path in list(paths):
        with path.open('rb') as stream:
            elf = stream.read(4) == b'\x7fELF'
        if not elf:
            continue
        listing = subprocess.run(['/usr/bin/ldd', str(path)], env=env, text=True, capture_output=True)
        for line in listing.stdout.splitlines():
            for word in line.split():
                if word.startswith('/') and Path(word).is_file():
                    paths.add(Path(word).resolve())
    return {str(x): sha(x) for x in sorted(paths)}


def snapshot(profile):
    p, lock, root = config(profile)
    env = clean_environment(root)
    base_check(p, env)
    script = ('import json,sys,sysconfig,site,mesonbuild.coredata,tomli,importlib.metadata as m;'
              'print(json.dumps(dict(meson=mesonbuild.coredata.version,meson_file=mesonbuild.coredata.__file__,'
              'tomli_file=tomli.__file__,stdlib=sysconfig.get_path("stdlib"),abi=sysconfig.get_config_var("SOABI"),'
              'user_site=site.ENABLE_USER_SITE,path=sys.path,packages=sorted(set((d.metadata["Name"].lower(),d.version) for d in m.distributions())))))')
    info = json.loads(capture([str(root / 'venv/bin/python'), '-I', '-B', '-c', script], env))
    expected = sorted([x['name'], x['version']] for x in lock['packages'] if x['role'] == 'runtime')
    if info['packages'] != expected or info['meson'] != '1.9.2' or info['user_site']:
        raise BuildEnvironmentError('unexpected package versions or enabled user site')
    for name in ('meson_file', 'tomli_file'):
        if not Path(info[name]).resolve().is_relative_to(root / 'venv'):
            raise BuildEnvironmentError('module outside the venv: ' + name)
    if any('site-packages' in x and not Path(x).resolve().is_relative_to(root / 'venv') for x in info['path']):
        raise BuildEnvironmentError('system site-packages leaked into Python')
    data = {'schema': 'kiki-build-env-fingerprint-v1', 'profile': p, 'lock': lock, 'python': info,
            'venv_files': file_inventory(root / 'venv'),
            'stdlib': file_inventory(info['stdlib'], ('site-packages',)),
            'tools_and_host_libraries': tool_inventory(p, env), 'launcher_sha256': sha(__file__)}
    return {'fingerprint': stable(data), 'data': data}


def check(profile):
    p, lock, root = config(profile)
    path = root / 'manifests/environment.json'
    if not path.is_file():
        raise BuildEnvironmentError('environment not prepared; prepare explicitly')
    saved = json.loads(path.read_text())
    current = snapshot(profile)
    if saved['fingerprint'] != current['fingerprint']:
        raise BuildEnvironmentError('environment fingerprint changed')
    return current


def prepare(profile):
    p, lock, root = config(profile)
    env = clean_environment(root)
    base_check(p, env)
    if (root / 'venv').exists():
        return check(profile)
    for name in ('cache/python', 'tmp', 'config', 'manifests'):
        (root / name).mkdir(parents=True, exist_ok=True)
    wheels = {}
    for item in lock['packages']:
        path = root / 'cache/python' / item['filename']
        if not path.exists():
            partial = path.with_suffix('.partial')
            with urllib.request.urlopen(item['url'], timeout=60) as response, partial.open('xb') as stream:
                shutil.copyfileobj(response, stream)
            if sha(partial) != item['sha256']:
                raise BuildEnvironmentError('download SHA mismatch: ' + item['name'])
            partial.rename(path)
        if sha(path) != item['sha256']:
            raise BuildEnvironmentError('cached wheel SHA mismatch: ' + item['name'])
        wheels[item['name']] = path
    bootstrap = root / 'bootstrap/installer-0.7.0'
    bootstrap.mkdir(parents=True)
    with zipfile.ZipFile(wheels['installer']) as archive:
        for item in archive.infolist():
            if not (bootstrap / item.filename).resolve().is_relative_to(bootstrap.resolve()):
                raise BuildEnvironmentError('unsafe bootstrap wheel path')
            archive.extract(item, bootstrap)
    subprocess.run([p['python'], '-I', '-m', 'venv', '--without-pip', str(root / 'venv')], env=env, check=True)
    script = 'import sys,runpy;sys.path.insert(0,sys.argv.pop(1));runpy.run_module("installer",run_name="__main__")'
    for item in lock['packages']:
        if item['role'] == 'runtime':
            subprocess.run([str(root / 'venv/bin/python'), '-I', '-B', '-c', script, str(bootstrap),
                            '--no-compile-bytecode', str(wheels[item['name']])], env=env, check=True)
    state = snapshot(profile)
    with (root / 'manifests/environment.json').open('x') as stream:
        json.dump(state, stream, indent=2, sort_keys=True)
    return state


def refresh(profile):
    """Explicit metadata revision; installed packages and host tools must match."""
    p, lock, root = config(profile)
    path = root / 'manifests/environment.json'
    saved = json.loads(path.read_text())
    current = snapshot(profile)
    for key in ('python', 'venv_files', 'stdlib', 'tools_and_host_libraries', 'lock'):
        if saved['data'][key] != current['data'][key]:
            raise BuildEnvironmentError('cannot refresh changed runtime content: ' + key)
    backup = path.with_name('environment-' + saved['fingerprint'] + '.json')
    if backup.exists():
        raise BuildEnvironmentError('attestation revision already archived')
    path.rename(backup)
    with path.open('x') as stream:
        json.dump(current, stream, indent=2, sort_keys=True)
    return current


def run_build(profile, repo_root, jobs):
    p, lock, root = config(profile)
    state = check(profile)
    candidate = Path(p['candidate'])
    gate = json.loads((candidate / 'gate.json').read_text())
    if gate['status'] != 'pass' or gate['kernel'] != '6.1.187':
        raise BuildEnvironmentError('candidate SHA gate did not pass')
    for name, key in [('snapshot.json', 'snapshot_sha256'), ('repo/index.x86_64.json', 'index_sha256')]:
        if sha(candidate / name) != gate[key]:
            raise BuildEnvironmentError('candidate changed after SHA verification: ' + name)
    records = json.loads((candidate / 'snapshot.json').read_text())
    recipe_dir = Path(p['recipe_dir'])
    if sha(recipe_dir / 'catalog.json') != p['recipe_catalog_sha256']:
        raise BuildEnvironmentError('frozen recipe catalog changed')
    if sha(recipe_dir / 'catalog.toml') != p['recipe_toml_sha256']:
        raise BuildEnvironmentError('frozen TOML recipes changed')
    result_root = candidate / p['result_dir']
    if not result_root.resolve().is_relative_to(candidate.resolve()):
        raise BuildEnvironmentError('result directory escapes the candidate')
    packages = result_root / 'packages/x86_64'
    packages.mkdir(parents=True, exist_ok=True)
    by_name = {x['name']: x for x in records['packages']}
    seed = {}
    for name in p['seed_packages']:
        item = by_name[name]
        source, dest = candidate / 'packages/x86_64' / item['file'], packages / item['file']
        if sha(source) != item['sha256']:
            raise BuildEnvironmentError('baseline package changed: ' + name)
        if not dest.exists():
            shutil.copy2(source, dest)
            if sha(dest) != item['sha256']:
                raise BuildEnvironmentError('seed copy SHA mismatch: ' + name)
        elif name not in p['build_packages'] and sha(dest) != item['sha256']:
            raise BuildEnvironmentError('seed dependency changed: ' + name)
        seed[name] = item['sha256']
    builder = Path(p['builder'])
    if sha(builder) != p['builder_sha256']:
        raise BuildEnvironmentError('frozen builder changed')
    build_identity = stable({'environment': state['fingerprint'], 'builder': sha(builder), 'recipes': p['recipe_catalog_sha256'], 'baseline': gate, 'seed': seed})
    env = clean_environment(root)
    command = [str(root / 'venv/bin/python'), '-B', str(builder), '--repo-root', str(repo_root),
               '--recipe-dir', str(recipe_dir), '--jobs', str(jobs), '--toolchain-id', p['id'] + ':' + build_identity, 'build',
               '--profile', str(repo_root / p['package_profile']), '--only'] + p['build_packages'] + [
               '--build-dir', str(root / 'work'), '--packages-dir', str(result_root / 'packages'),
               '--repo-dir', str(result_root / 'repo'), '--source-cache', str(candidate / 'sources')]
    result_root.mkdir(exist_ok=True)
    number = len(list(result_root.glob('build-*.log'))) + 1
    log = result_root / ('build-%02d.log' % number)
    with log.open('x') as stream:
        stream.write(json.dumps({'environment_fingerprint': state['fingerprint'], 'build_identity': build_identity,
                                 'command': command, 'environment': env}, sort_keys=True) + '\n')
        stream.flush()
        process = subprocess.run(command, env=env, stdout=stream, stderr=subprocess.STDOUT)
    print(log.read_text(), flush=True)
    if process.returncode:
        raise BuildEnvironmentError('first build failed; see ' + str(log))
    return {'status': 'pass', 'fingerprint': state['fingerprint'], 'build_identity': build_identity, 'log': str(log)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'check', 'refresh', 'run'])
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    try:
        result = prepare(args.profile) if args.command == 'prepare' else check(args.profile) if args.command == 'check' else refresh(args.profile) if args.command == 'refresh' else run_build(args.profile, args.repo_root, args.jobs)
        print(json.dumps({k: v for k, v in result.items() if k != 'data'}, indent=2))
    except (BuildEnvironmentError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print('error: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
