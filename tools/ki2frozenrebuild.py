#!/usr/bin/env python3
"""Prepare frozen inputs and promote separately validated Stage 3 rebuilds."""
import argparse
import datetime
import json
from pathlib import Path
import shutil
import sys

import ki2build as build
from ki2integrity import sha256_file, audit_payload
from ki2stage3candidate import recipe_toml, read_manifest, verified_copy, verify, finalize

NAMES = ['gsettings-desktop-schemas', 'json-glib', 'libgudev', 'kiki-installer-gtk']
BASE = 'dist/ki2/stage3-6.1.187-candidate-20261016'
RUN = 'rebuild-frozen-20261017'
TARGET = 'dist/ki2/stage3-6.1.187-candidate-20261017'
LINUX = '/mnt/e/dev/KIKI-OS/'


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


def prepare(repo):
    base, run = repo / BASE, repo / BASE / RUN
    run.mkdir(exist_ok=False)
    catalog = json.loads((base / 'recipes/catalog.json').read_text())
    raws = catalog['recipes']
    by_name = {r['name']: r for r in raws}
    original = build.load_recipes(base / 'recipes')
    snapshot = json.loads((base / 'snapshot.json').read_text())
    records = {r['name']: r for r in snapshot['packages']}
    preservation = {'baseline_metadata': {}, 'packages': [], 'source_inputs': {}}
    for path in ['snapshot.json', 'repo/index.x86_64.json', 'gate.json']:
        preservation['baseline_metadata'][path] = sha256_file(base / path)
    for item in snapshot['packages']:
        package = base / 'packages/x86_64' / item['file']
        if sha256_file(package) != item['sha256']:
            raise ValueError('baseline SHA changed: ' + item['file'])
        preservation['packages'].append({'path': str(package.relative_to(repo)), 'sha256': item['sha256']})
        source = repo / item['source']
        if source.is_file() and source != package:
            preservation['packages'].append({'path': str(source.relative_to(repo)), 'sha256': sha256_file(source)})
    for name in NAMES[:3]:
        raw = by_name[name]
        raw['release'] = '2'
        recipe = raw['build']
        recipe['sysroot_exclude'] = []
        raw['dependencies']['build'].append('linux-headers')
        recipe['inputs'] = list(dict.fromkeys(by_name['graphene']['build']['inputs']))
        directory = {'gsettings-desktop-schemas': 'schemas', 'json-glib': 'json', 'libgudev': 'gudev'}[name]
        options = ' '.join(recipe['configure_options'])
        commands = list(by_name['graphene']['build']['configure'][:-1])
        commands.append('PATH="${KI2_BUILD_DIR}/tools:$PATH" meson setup "${KI2_BUILD_DIR}/' + directory + '" "${KI2_SOURCE_DIR}" --cross-file "${KI2_BUILD_DIR}/cross.ini" --prefix=/usr --libdir=lib --buildtype=release --wrap-mode=nofallback ' + options)
        recipe['configure'] = commands
        recipe['env'] = dict(by_name['graphene']['build']['env'])
        recipe['env']['KI2_SYSROOT_LIBRARY_PATH'] = '${KI2_BUILD_DIR}/' + directory + '/' + {'json-glib': 'json-glib', 'libgudev': 'gudev'}.get(name, '') + ':${KI2_SYSROOT_LIBRARY_PATH}'
        if name != 'json-glib':
            recipe['compile'].append('meson test -C "${KI2_BUILD_DIR}/' + directory + '" --print-errorlogs --no-rebuild')
    # Recompile the matching frontend against the preserved bootstrap ABI and
    # package its payload separately with the frozen standard packager.
    installer = by_name[NAMES[3]]
    installer['release'] = '18'
    installer['source']['path'] = 'installer-payload'
    installer['source']['inputs'] = list(installer['source']['inputs']) + ['installer-build-provenance.json']
    inputs = run / 'inputs'
    inputs.mkdir()
    copied = set()
    for name in NAMES:
        raw = by_name[name]
        for relative in raw['build'].get('inputs', []) + raw['source'].get('inputs', []):
            source = repo / relative
            if source.is_file() and relative not in copied:
                destination = inputs / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                preservation['source_inputs'][relative] = sha256_file(destination)
                copied.add(relative)
    # Freeze test and module metadata as well as production sources.
    for source in (repo / 'cmd/kiki-installer-gotk').glob('*'):
        if source.suffix in ('.go', '.mod', '.sum') or source.name == 'Makefile':
            relative = str(source.relative_to(repo)).replace('\\', '/')
            destination = inputs / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                shutil.copy2(source, destination)
            preservation['source_inputs'][relative] = sha256_file(destination)
    (inputs / 'distro/profiles').mkdir(parents=True, exist_ok=True)
    (inputs / 'distro/profiles/rebuild.toml').write_text('[profile]\nname="frozen-rebuild"\narch="x86_64"\npackages=' + json.dumps(NAMES) + '\n', encoding='utf-8')
    recipes = run / 'recipes'
    recipes.mkdir()
    write(recipes / 'catalog.json', catalog)
    (recipes / 'catalog.toml').write_text(recipe_toml(raws), encoding='utf-8', newline='\n')
    loaded = build.load_recipes(recipes)
    seed = build.dependency_closure(loaded, NAMES[:3], 'x86_64', include_build_deps=True)
    seed = [name for name in seed if name not in NAMES]
    if any(name not in records for name in seed):
        raise ValueError('dependency missing from baseline')
    profile = json.loads((repo / 'distro/specs/build-env-meson-1.9.2.json').read_text())
    profile.update(id='meson-1.9.2-frozen4-20261017', root='/home/tang/kiki-build/meson-1.9.2-frozen4-20261017',
                   seed_packages=seed, build_packages=NAMES[:3], package_profile='distro/profiles/rebuild.toml',
                   recipe_dir=LINUX + BASE + '/' + RUN + '/recipes',
                   recipe_catalog_sha256=sha256_file(recipes / 'catalog.json'),
                   recipe_toml_sha256=sha256_file(recipes / 'catalog.toml'), result_dir=RUN + '/build')
    write(run / 'profile.json', profile)
    shutil.copy2(repo / 'distro/specs/build-env-meson-1.9.2.lock', run / profile['lock'])
    write(run / 'preservation.json', preservation)
    write(run / 'plan.json', {'packages': [{'name': name, 'old_release': original[name].release, 'new_release': loaded[name].release, 'recipe_digest': loaded[name].digest} for name in NAMES], 'seeds': seed, 'isolated_source_root': str(inputs)})
    print(json.dumps({'run': str(run), 'seed_count': len(seed), 'packages': NAMES}, indent=2))


def promote(repo):
    base, run, target = repo / BASE, repo / BASE / RUN, repo / TARGET
    if target.exists():
        raise FileExistsError(target)
    runtime = json.loads((run / 'runtime-check.json').read_text())
    if runtime.get('status') != 'pass' or set(runtime.get('validated_packages', [])) != set(NAMES):
        raise ValueError('all four runtime checks must pass before promotion')
    records = json.loads((run / 'preservation.json').read_text())
    for relative, digest in records['baseline_metadata'].items():
        if sha256_file(base / relative) != digest:
            raise ValueError('baseline metadata changed: ' + relative)
    for entry in records['packages']:
        if sha256_file(repo / entry['path']) != entry['sha256']:
            raise ValueError('original package changed: ' + entry['path'])
    for relative, digest in records['source_inputs'].items():
        if sha256_file(run / 'inputs' / relative) != digest:
            raise ValueError('frozen build input changed: ' + relative)
    recipes = build.load_recipes(run / 'recipes')
    validated = {}
    for name in NAMES:
        package = run / 'build/packages/x86_64' / build.package_filename(recipes[name], 'x86_64')
        audit = audit_payload(package)
        if audit['errors']:
            raise ValueError(str(audit['errors']))
        digest = sha256_file(package)
        if runtime['package_sha256'][name] != digest:
            raise ValueError('package changed after runtime check: ' + name)
        manifest = read_manifest(package)
        recipe = recipes[name]
        if (manifest['name'], manifest['version'], str(manifest['release']), manifest['arch'], manifest['recipe_digest']) != (name, recipe.version, recipe.release, 'x86_64', recipe.digest):
            raise ValueError('rebuilt manifest differs from frozen recipe: ' + name)
        validated[name] = (package, digest, manifest)
    snapshot = json.loads((base / 'snapshot.json').read_text())
    snapshot.update(created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    parent_snapshot_sha256=sha256_file(base / 'snapshot.json'),
                    note='Unsigned candidate with four source-rebuilt, SHA and runtime validated replacements. Original candidate and installers preserved.')
    for item in snapshot['packages']:
        if item['name'] in validated:
            package, digest, manifest = validated[item['name']]
            item.update(file=package.name, sha256=digest, source=str(package.relative_to(repo)).replace('\\', '/'),
                        policy='source-rebuilt-runtime-validated', artifact_recipe_digest=manifest['recipe_digest'], current_recipe_digest=recipes[item['name']].digest)
        else:
            package, digest = base / 'packages/x86_64' / item['file'], item['sha256']
        verified_copy(package, target / 'packages/x86_64' / item['file'], digest)
    for item in snapshot['sources']:
        output = target / 'sources' / item['file']
        if not output.exists():
            verified_copy(base / 'sources' / item['file'], output, item['sha256'])
    write(target / 'snapshot.json', snapshot)
    shutil.copytree(run / 'recipes', target / 'recipes')
    shutil.copytree(base / 'build-tools', target / 'build-tools')
    gate = finalize(target)
    gate.update(runtime_report_sha256=sha256_file(run / 'runtime-check.json'), validated_rebuilds=NAMES,
                original_package_copies_preserved=len(records['packages']), release_ready=False)
    iso = json.loads((run / 'original-iso-preservation.json').read_text())
    if iso.get('status') != 'pass':
        raise ValueError('original ISO preservation check did not pass')
    gate['original_iso_images_preserved'] = len(iso['images'])
    write(target / 'gate.json', gate)
    report = {'status': 'pass', 'candidate': str(target), 'gate': gate, 'runtime': runtime,
              'rebuilds': [{'name': n, 'file': p.name, 'sha256': d, 'release': m['release']} for n, (p, d, m) in validated.items()]}
    write(repo / 'artifacts/stage3-frozen4-rebuild-20261017.json', report)
    print(json.dumps({k: v for k, v in report.items() if k != 'runtime'}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'promote'])
    parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    (prepare if args.command == 'prepare' else promote)(args.repo_root)
