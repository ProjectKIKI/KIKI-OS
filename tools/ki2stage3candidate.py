#!/usr/bin/env python3
"""Create and verify a separate kernel-pinned, unsigned candidate repository."""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
import shutil
import tarfile
from types import SimpleNamespace

import ki2build
from ki2integrity import audit_payload, sha256_file


FROZEN = {'gsettings-desktop-schemas', 'json-glib', 'libgudev', 'kiki-installer-gtk'}


def recipe_toml(raws):
    """Serialize normalized recipe data without adding a bootstrap dependency."""
    lines = []
    def table(data, path):
        children = []
        for key, value in data.items():
            part = path + '.' + json.dumps(key)
            if isinstance(value, dict) or (isinstance(value, list) and value and isinstance(value[0], dict)):
                children.append((part, value))
            else:
                if value is None:
                    raise ValueError('null is not a supported TOML value')
                lines.append(json.dumps(key) + ' = ' + json.dumps(value, ensure_ascii=False))
        for part, value in children:
            if isinstance(value, dict):
                lines.append('[' + part + ']')
                table(value, part)
            else:
                for item in value:
                    lines.append('[[' + part + ']]')
                    table(item, part)
    for raw in raws:
        lines.append('[[recipe]]')
        table(raw, 'recipe')
        lines.append('')
    return '\n'.join(lines)


def read_manifest(path):
    # Packages put manifest.json first. getmember() scans the entire compressed
    # payload, which needlessly decompresses multi-gigabyte model packages.
    with tarfile.open(path, 'r|gz') as archive:
        for member in archive:
            if member.name == 'manifest.json':
                return json.load(archive.extractfile(member))
    raise ValueError('package manifest missing: ' + str(path))


def verified_copy(source, target, expected):
    if target.exists():
        raise FileExistsError(target)
    if sha256_file(source) != expected:
        raise ValueError('audited source changed: ' + str(source))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    if sha256_file(target) != expected:
        raise ValueError('copy SHA-256 mismatch: ' + str(target))


def create(root, target, audit_path):
    recipes = ki2build.load_recipes(root / 'distro/recipes')
    audit = json.loads(audit_path.read_text(encoding='utf-8'))
    directory = target / 'packages/x86_64'
    directory.mkdir(parents=True, exist_ok=False)
    selected, excluded = [], []
    for name, recipe in sorted(recipes.items()):
        if name == 'ki2ctl':
            continue
        choices = [p for p in audit['packages'] if p['payload'].get('name') == name
                   and str(p['payload'].get('version')) == recipe.version
                   and str(p['payload'].get('release')) == recipe.release
                   and not p['payload']['errors']]
        exact = [p for p in choices if p['payload'].get('recipe_digest') == recipe.digest]
        if exact:
            choices = exact
            policy = 'current-recipe'
        elif choices and name in FROZEN:
            policy = 'frozen-existing-artifact-rebuild-pending'
        else:
            excluded.append({'name': name, 'version': recipe.version, 'release': recipe.release,
                             'reason': 'no audited current recipe artifact'})
            continue
        if name in ('linux', 'linux-headers') and recipe.version != '6.1.187':
            raise ValueError('candidate kernel boundary must be 6.1.187')
        choices.sort(key=lambda p: (not p['path'].replace('\\', '/').startswith('dist/ki2/packages/'), p['path']))
        item = choices[0]
        source = root / item['path'].replace('\\', '/')
        output = directory / ki2build.package_filename(recipe, 'x86_64')
        verified_copy(source, output, item['sha256'])
        selected.append({'name': name, 'file': output.name, 'sha256': item['sha256'],
                         'source': str(source.relative_to(root)), 'policy': policy,
                         'artifact_recipe_digest': item['payload'].get('recipe_digest'),
                         'current_recipe_digest': recipe.digest})
        print('COPY', name, policy, flush=True)
    # ki2ctl is a local copy-only package, not a native compiler build.
    recipe = recipes['ki2ctl']
    payload = target / 'local-copy/ki2ctl'
    ki2build.copy_source_to_dest(root / recipe.source['path'], payload)
    key = ki2build.stable_hash({'schema': 'candidate-local-copy-v1', 'recipe': recipe.digest,
                               'files': ki2build.package_file_manifest(payload)})
    output = directory / ki2build.package_filename(recipe, 'x86_64')
    ki2build.create_package(SimpleNamespace(arch='x86_64'), recipe, payload, output, key, {})
    selected.append({'name': 'ki2ctl', 'file': output.name, 'sha256': sha256_file(output),
                     'source': recipe.source['path'], 'policy': 'local-copy-current-recipe',
                     'artifact_recipe_digest': recipe.digest, 'current_recipe_digest': recipe.digest})
    source_records = []
    for recipe in recipes.values():
        inputs = [recipe.source] if recipe.source.get('type') == 'url' else []
        inputs += ki2build.source_extra_entries(recipe)
        for source in inputs:
            filename = source.get('file') or Path(source['url']).name
            output = target / 'sources' / filename
            if not output.exists():
                verified_copy(root / 'dist/sources' / filename, output, source['sha256'])
            actual = sha256_file(output)
            if actual != source['sha256']:
                raise ValueError('source SHA-256 mismatch: ' + filename)
            source_records.append({'recipe': recipe.name, 'file': filename,
                                   'sha256': actual, 'url': source['url']})
    snapshot = {'schema': 'kiki-stage3-candidate-v1', 'kernel': '6.1.187', 'release_ready': False,
                'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'packages': selected, 'excluded_unbuilt_packages': excluded, 'sources': source_records,
                'source_audit_sha256': sha256_file(audit_path),
                'note': 'Unsigned candidate. Frozen artifacts preserve existing installers; not a claim of a full source rebuild.'}
    with (target / 'snapshot.json').open('x', encoding='utf-8') as stream:
        json.dump(snapshot, stream, ensure_ascii=False, indent=2)
    return finalize(target)


def finalize(target):
    snapshot = json.loads((target / 'snapshot.json').read_text(encoding='utf-8'))
    directory = target / 'packages/x86_64'
    index_path = target / 'repo/index.x86_64.json'
    if index_path.exists():
        existing = json.loads(index_path.read_text())
        if existing.get('schema') == 'ki2-repository-v1':
            return verify(target)
        index_path.rename(index_path.with_suffix('.pre-validation.json'))
    entries = []
    for entry in snapshot['packages']:
        package = directory / entry['file']
        manifest = read_manifest(package)
        entries.append({**{key: manifest[key] for key in ('name', 'version', 'release', 'arch', 'summary', 'license', 'tier')},
                        'file': package.name, 'size': package.stat().st_size, 'sha256': entry['sha256'],
                        'dependencies': manifest['dependencies'],
                        'runtime_dependencies': manifest.get('runtime_dependencies', []),
                        'file_count': manifest['payload']['file_count']})
    (target / 'repo').mkdir(exist_ok=True)
    with (target / 'repo/index.x86_64.json').open('x', encoding='utf-8') as stream:
        json.dump({'schema': 'ki2-repository-v1', 'arch': 'x86_64', 'created_at': snapshot['created_at'],
                   'packages': sorted(entries, key=lambda e: e['name'])}, stream, indent=2)
    return verify(target)


def verify(target):
    snapshot = json.loads((target / 'snapshot.json').read_text(encoding='utf-8'))
    index = json.loads((target / 'repo/index.x86_64.json').read_text(encoding='utf-8'))
    if index.get('schema') != 'ki2-repository-v1':
        raise ValueError('unsupported repository index schema')
    names = {x['name'] for x in index['packages']}
    if snapshot.get('kernel') != '6.1.187' or not {'linux', 'linux-headers'} <= names:
        raise ValueError('candidate requires kernel and UAPI headers 6.1.187')
    if len(names) != len(index['packages']):
        raise ValueError('duplicate index package')
    locked = {x['file']: x for x in snapshot['packages']}
    if set(locked) != {x['file'] for x in index['packages']}:
        raise ValueError('index and snapshot package sets differ')
    for number, entry in enumerate(index['packages'], 1):
        path = target / 'packages/x86_64' / entry['file']
        actual = sha256_file(path)
        if actual != entry['sha256'] or actual != locked[entry['file']]['sha256'] or path.stat().st_size != entry['size']:
            raise ValueError('index SHA/size mismatch: ' + path.name)
        payload = audit_payload(path)
        if payload['errors']:
            raise ValueError(str(payload['errors']))
        if (payload['name'], payload['version'], str(payload['release']), payload['arch']) != (entry['name'], entry['version'], str(entry['release']), entry['arch']):
            raise ValueError('manifest identity mismatch: ' + path.name)
        if entry['name'] in ('linux', 'linux-headers') and entry['version'] != '6.1.187':
            raise ValueError('rejected kernel in candidate')
        for dependency in entry['runtime_dependencies']:
            if dependency not in names:
                raise ValueError('missing runtime dependency: ' + entry['name'] + ' -> ' + dependency)
        if number % 20 == 0:
            print('VERIFY packages', number, '/', len(names), flush=True)
    for entry in snapshot['sources']:
        if sha256_file(target / 'sources' / entry['file']) != entry['sha256']:
            raise ValueError('source changed: ' + entry['file'])
    return {'status': 'pass', 'kernel': '6.1.187', 'packages': len(names),
            'source_files': len({x['file'] for x in snapshot['sources']}),
            'source_references': len(snapshot['sources']), 'index_sha256': sha256_file(target / 'repo/index.x86_64.json'),
            'snapshot_sha256': sha256_file(target / 'snapshot.json')}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['create', 'finalize', 'verify'])
    p.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument('--target', type=Path, required=True)
    p.add_argument('--audit', type=Path)
    args = p.parse_args()
    result = create(args.root.resolve(), args.target.resolve(), args.audit.resolve()) if args.command == 'create' else finalize(args.target.resolve()) if args.command == 'finalize' else verify(args.target.resolve())
    print(json.dumps(result, indent=2), flush=True)
