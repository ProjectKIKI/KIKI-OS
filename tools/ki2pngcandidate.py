#!/usr/bin/env python3
"""Fix missing MIME data in a new candidate; preserve all previous payloads."""
import argparse
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import ki2build
from ki2integrity import audit_payload, sha256_file
from ki2stage3candidate import recipe_toml, read_manifest, verified_copy, finalize

BASE = 'dist/ki2/stage3-6.1.187-candidate-20261017'
TARGET = 'dist/ki2/stage3-6.1.187-candidate-pngfix-20261017'
WORK = Path('/home/tang/kiki-build/png-logo-20261017')


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


def prepare(repo):
    if os.geteuid() != 0:
        raise ValueError('run on Linux as root for preserved Unix payload modes')
    base, target = repo / BASE, repo / TARGET
    target.mkdir(exist_ok=False)
    validation = target / 'validation'
    validation.mkdir()
    snapshot = json.loads((base / 'snapshot.json').read_text())
    old = next(p for p in snapshot['packages'] if p['name'] == 'kiki-installer-gtk')
    package = base / 'packages/x86_64' / old['file']
    if sha256_file(package) != old['sha256']:
        raise ValueError('parent installer changed')
    payload = WORK / 'fixed-payload'
    local = WORK / package.name
    if sha256_file(local) != old['sha256']:
        raise ValueError('cached parent installer changed')
    ki2build.extract_package_rootfs(local, payload)
    before = {x['path']: x for x in ki2build.package_file_manifest(payload)}
    verification = subprocess.run(['/usr/bin/rpm', '-V', 'shared-mime-info'], capture_output=True, text=True, check=True)
    version = subprocess.check_output(['/usr/bin/rpm', '-q', '--qf', '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}', 'shared-mime-info'], text=True)
    sources = WORK / 'mime-source'
    (sources / 'packages').mkdir(parents=True)
    xml = Path('/usr/share/mime/packages/freedesktop.org.xml')
    shutil.copy2(xml, sources / 'packages/freedesktop.org.xml')
    command = ['/usr/bin/update-mime-database', str(sources)]
    subprocess.run(command, check=True, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'TZ': 'UTC'})
    inputs = {'source_rpm': version, 'rpm_verify_output': verification.stdout,
              'xml_sha256': sha256_file(xml), 'cache_generator_sha256': sha256_file('/usr/bin/update-mime-database'),
              'command': command, 'mime_cache_sha256': sha256_file(sources / 'mime.cache'),
              'bootstrap_boundary': 'Generated from the existing, RPM-verified shared-mime-info XML; no host runtime library changes.'}
    for source, relative in [(sources / 'mime.cache', 'usr/share/mime/mime.cache'),
                             (xml, 'usr/share/mime/packages/freedesktop.org.xml'),
                             (Path('/usr/share/licenses/shared-mime-info/COPYING'), 'usr/share/licenses/shared-mime-info/COPYING')]:
        destination = payload / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        destination.chmod(0o644)
    path = payload / 'usr/share/kiki-installer-gtk/runtime-manifest.json'
    runtime = json.loads(path.read_text())
    runtime['mime_cache'] = inputs
    runtime['host_runtime_packages'] = sorted(set(runtime['host_runtime_packages']) | {'shared-mime-info'})
    files = [p for p in payload.rglob('*') if p.is_file() and not p.is_symlink()]
    runtime['files'] = len(files)
    runtime['bytes'] = sum(p.stat().st_size for p in files)
    path.write_text(json.dumps(runtime, indent=2, sort_keys=True) + '\n')
    after = {x['path']: x for x in ki2build.package_file_manifest(payload)}
    changed = [name for name in sorted(set(before) | set(after)) if before.get(name) != after.get(name)]
    allowed = {'/usr/share/mime', '/usr/share/mime/packages', '/usr/share/mime/mime.cache',
               '/usr/share/mime/packages/freedesktop.org.xml', '/usr/share/licenses/shared-mime-info',
               '/usr/share/licenses/shared-mime-info/COPYING', '/usr/share/kiki-installer-gtk/runtime-manifest.json'}
    if set(changed) - allowed:
        raise ValueError('unexpected payload changes: ' + str(changed))
    if before['/usr/bin/kiki-installer-gtk'] != after['/usr/bin/kiki-installer-gtk']:
        raise ValueError('frontend changed unexpectedly')
    recipes = target / 'recipes'
    recipes.mkdir()
    catalog = json.loads((base / 'recipes/catalog.json').read_text())
    for raw in catalog['recipes']:
        if raw['name'] == 'kiki-installer-gtk':
            raw['release'] = '19'
            raw['license'] += ' AND GPL-2.0-or-later'
            raw['source'] = {'type': 'local', 'path': str(payload),
                             'inputs': [str(validation / 'mime-inputs.json')]}
    dump(validation / 'mime-inputs.json', inputs)
    dump(recipes / 'catalog.json', catalog)
    (recipes / 'catalog.toml').write_text(recipe_toml(catalog['recipes']))
    recipe = ki2build.load_recipes(recipes)['kiki-installer-gtk']
    output = WORK / ki2build.package_filename(recipe, 'x86_64')
    if output.exists():
        raise FileExistsError(output)
    manifest = read_manifest(package)
    key = ki2build.stable_hash({'parent_sha256': old['sha256'], 'mime_inputs': inputs,
                               'recipe': recipe.digest, 'files': list(after.values())})
    ki2build.create_package(SimpleNamespace(arch='x86_64'), recipe, payload, output, key, manifest.get('dependency_keys', {}))
    audit = audit_payload(output)
    if audit['errors']:
        raise ValueError(str(audit['errors']))
    dump(validation / 'installer-preservation.json', {'parent_sha256': old['sha256'],
         'changed_payload_files': changed, 'unchanged_frontend_sha256': after['/usr/bin/kiki-installer-gtk']['sha256'],
         'unchanged_payload_entries': len(before) - 1, 'package_sha256': sha256_file(output), 'mime_inputs': inputs})
    # Package copies and full candidate verification happen on the Windows
    # filesystem with larger buffered reads, keeping WSL metadata I/O bounded.
    dump(validation / 'prepared.json', {'package': str(output), 'package_sha256': sha256_file(output), 'release': '19'})
    print(json.dumps({'status': 'prepared', 'package': str(output), 'sha256': sha256_file(output)}, indent=2))


def stage(repo):
    base, target = repo / BASE, repo / TARGET
    run = target / 'validation'
    prepared = json.loads((run / 'prepared.json').read_text())
    # Copy the freshly built package through WSL once, before this step.
    fixed = run / 'kiki-installer-gtk-0.1.0-19.x86_64.ki2'
    if sha256_file(fixed) != prepared['package_sha256']:
        raise ValueError('new installer copy changed')
    snapshot = json.loads((base / 'snapshot.json').read_text(encoding='utf-8'))
    snapshot['parent_snapshot_sha256'] = sha256_file(base / 'snapshot.json')
    snapshot['note'] = 'PNG MIME-cache fix; frontend and all bootstrap libraries preserved. New validation-only candidate.'
    before = {'snapshot.json': sha256_file(base / 'snapshot.json'), 'repo/index.x86_64.json': sha256_file(base / 'repo/index.x86_64.json')}
    for item in snapshot['packages']:
        if item['name'] == 'kiki-installer-gtk':
            source, digest = fixed, prepared['package_sha256']
            manifest = read_manifest(fixed)
            item.update(file=fixed.name, sha256=digest, source=str(fixed.relative_to(repo)).replace('\\', '/'),
                        policy='png-mime-fix-runtime-validation-pending',
                        artifact_recipe_digest=manifest['recipe_digest'], current_recipe_digest=manifest['recipe_digest'])
        else:
            source, digest = base / 'packages/x86_64' / item['file'], item['sha256']
        verified_copy(source, target / 'packages/x86_64' / item['file'], digest)
    for item in snapshot['sources']:
        destination = target / 'sources' / item['file']
        if not destination.exists():
            verified_copy(base / 'sources' / item['file'], destination, item['sha256'])
    dump(target / 'snapshot.json', snapshot)
    shutil.copytree(base / 'build-tools', target / 'build-tools')
    dump(run / 'parent-metadata.json', before)
    print('Staged 124 verified package copies; no candidate index promoted yet.')


def runtime(repo):
    target = repo / TARGET
    run = target / 'validation'
    source = repo / 'dist/ki2/stage3-6.1.187-candidate-20261016/rebuild-frozen-20261017'
    # Reuse only already validated native tests whose package SHA still matches;
    # the new installer always gets a fresh target-only GUI test.
    for name in ['profile.json', 'native-runtime-check.json']:
        shutil.copy2(source / name, run / name)
    (run / 'recipes').symlink_to(target / 'recipes', target_is_directory=True)
    (run / 'build').mkdir()
    (run / 'build/packages').symlink_to(target / 'packages', target_is_directory=True)
    import ki2frozenruntime as verify
    verify.BASE, verify.RUN, verify.build = TARGET, 'validation', ki2build
    verify.verify_runtime(repo)
    logs = sorted(run.glob('installer-gui-*.log'))
    if not logs or any('Installer logo unavailable' in p.read_text() for p in logs):
        raise ValueError('PNG warning persisted')
    report = json.loads((run / 'runtime-check.json').read_text())
    report['png_logo_warning'] = 'absent'
    report['native_test_reuse'] = 'Unchanged native package SHA matched previous target-only tests; installer GUI freshly executed.'
    (run / 'runtime-check.json').write_text(json.dumps(report, indent=2) + '\n')
    print('PASS: target-only GUI; no PNG loader warning')


def promote(repo):
    target = repo / TARGET
    runtime = json.loads((target / 'validation/runtime-check.json').read_text(encoding='utf-8'))
    if runtime.get('status') != 'pass' or runtime.get('png_logo_warning') != 'absent':
        raise ValueError('PNG runtime gate failed')
    snapshot = json.loads((target / 'snapshot.json').read_text(encoding='utf-8'))
    for item in snapshot['packages']:
        if item['name'] == 'kiki-installer-gtk':
            if item['sha256'] != runtime['package_sha256'][item['name']]:
                raise ValueError('installer changed after runtime validation')
            item['policy'] = 'png-mime-fix-runtime-validated'
    (target / 'snapshot.json').write_text(json.dumps(snapshot, indent=2) + '\n')
    gate = finalize(target)
    gate.update(png_logo_warning='absent', runtime_report_sha256=sha256_file(target / 'validation/runtime-check.json'), release_ready=False)
    dump(target / 'gate.json', gate)
    print(json.dumps(gate, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'stage', 'runtime', 'promote'])
    parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    globals()[args.command](args.repo_root)
