#!/usr/bin/env python3
"""Read-only SHA-256 and streaming payload audit of existing ki2 artifacts."""
from __future__ import annotations

import argparse
import ast
import collections
import concurrent.futures
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys
import tarfile

sys.dont_write_bytecode = True
import ki2build


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def audit_payload(path):
    """Hash each archived file once, without extracting or running any payload."""
    manifest = None
    actual = {}
    errors = []
    with tarfile.open(path, 'r|gz', bufsize=2 * 1024 * 1024) as archive:
        for member in archive:
            name = member.name.rstrip('/')
            if name == 'manifest.json':
                if manifest is not None:
                    errors.append('duplicate manifest')
                manifest = json.load(archive.extractfile(member))
                continue
            if name == 'rootfs':
                continue
            parts = PurePosixPath(name).parts
            if not name.startswith('rootfs/') or '..' in parts or name.startswith('/'):
                errors.append('unexpected archive path: ' + name)
                continue
            rel = '/' + name[len('rootfs/'):]
            if rel in actual:
                errors.append('duplicate payload path: ' + rel)
            item = {'mode': member.mode}
            if member.isfile():
                digest = hashlib.sha256()
                size = 0
                stream = archive.extractfile(member)
                for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
                    digest.update(block)
                    size += len(block)
                item.update(type='file', sha256=digest.hexdigest(), size=size)
            elif member.isdir():
                item['type'] = 'dir'
            elif member.issym():
                item.update(type='symlink', target=member.linkname)
            elif member.islnk():
                target = '/' + member.linkname.removeprefix('rootfs/')
                if target not in actual or actual[target].get('type') != 'file':
                    errors.append('unresolved hardlink: ' + rel)
                    item['type'] = 'hardlink'
                else:
                    item = dict(actual[target], mode=member.mode)
            else:
                errors.append('unsupported payload entry: ' + rel)
            actual[rel] = item
    if manifest is None:
        return {'errors': errors + ['missing manifest'], 'files_checked': len(actual)}
    declared = {}
    for item in manifest.get('files', []):
        rel = item['path']
        if rel in declared:
            errors.append('duplicate manifest path: ' + rel)
        declared[rel] = item
    for rel in sorted(set(actual) | set(declared)):
        got, want = actual.get(rel), declared.get(rel)
        if got is None or want is None:
            errors.append(('missing payload: ' if got is None else 'undeclared payload: ') + rel)
            continue
        for key in ('type', 'size', 'sha256', 'target'):
            if key in want and got.get(key) != want[key]:
                errors.append(key + ' mismatch: ' + rel)
        if 'mode' in want and got['mode'] != int(want['mode'], 8):
            errors.append('mode mismatch: ' + rel)
    return {'name': manifest.get('name'), 'version': manifest.get('version'),
            'release': manifest.get('release'), 'arch': manifest.get('arch'),
            'recipe_digest': manifest.get('recipe_digest'), 'build_key': manifest.get('build_key'),
            'dependency_keys': manifest.get('dependency_keys', {}),
            'files_checked': len(actual), 'errors': errors}


def run(root, report_path, workers=3, include_iso=True):
    root = root.resolve()
    recipes = ki2build.load_recipes(root / 'distro/recipes')
    expectations = collections.defaultdict(list)
    missing_sources = []
    for recipe in recipes.values():
        sources = [recipe.source] if recipe.source.get('type') == 'url' else []
        sources += ki2build.source_extra_entries(recipe)
        for source in sources:
            filename = source.get('file') or Path(source.get('url', '')).name
            path = root / 'dist/sources' / filename
            item = {'recipe': recipe.name, 'sha256': source.get('sha256'), 'url': source.get('url')}
            expectations[path].append(item)
            if not path.is_file():
                missing_sources.append(dict(item, path=str(path)))
    planning = root / 'distro/specs/gnome-desktop-sources.toml'
    if planning.is_file():
        data = ki2build.read_structured_file(planning)
        for source in data.get('source', []):
            path = root / 'dist/sources' / Path(source['url']).name
            expectations[path].append({'recipe': 'planning:' + source['name'],
                                       'sha256': source.get('sha256'), 'url': source['url']})
        if data.get('metadata_url'):
            expectations[root / 'dist/sources' / Path(data['metadata_url']).name].append({
                'recipe': 'planning:gnome-build-meta', 'sha256': data['metadata_sha256']})
    # The frozen installer has explicit source pins outside the recipe catalog.
    graphics = root / 'tools/ki2graphics.py'
    if graphics.is_file():
        constants = {}
        for node in ast.parse(graphics.read_text(encoding='utf-8')).body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        constants[target.id] = node.value.value
        for name in ('CAGE', 'SEATD', 'WLROOTS'):
            filename = name.lower() + '-' + constants[name + '_VERSION'] + '.tar.gz'
            expectations[root / 'dist/sources' / filename].append({
                'recipe': 'installer:' + name.lower(), 'sha256': constants[name + '_SHA256'],
                'origin': 'tools/ki2graphics.py'})
    sources = sorted(p for p in (root / 'dist/sources').iterdir() if p.is_file())
    packages = sorted(p for directory in ('dist', 'build', 'x86_64')
                      for p in (root / directory).rglob('*.ki2') if p.is_file())
    images = sorted(p for p in (root / 'dist').rglob('*.iso') if p.is_file()) if include_iso else []
    records = []
    print(json.dumps({'phase': 'inventory', 'sources': len(sources), 'packages': len(packages),
                      'iso': len(images), 'bytes': sum(p.stat().st_size for p in sources + packages + images)}), flush=True)

    def hash_one(path):
        before = path.stat()
        digest = sha256_file(path)
        after = path.stat()
        return {'path': str(path.relative_to(root)), 'sha256': digest, 'bytes': after.st_size,
                'changed_during_read': (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)}

    with concurrent.futures.ThreadPoolExecutor(workers) as pool:
        for i, item in enumerate(pool.map(hash_one, sources + packages + images), 1):
            records.append(item)
            if i % 100 == 0:
                print(json.dumps({'phase': 'archive_hash', 'done': i}), flush=True)
    by_path = {root / r['path']: r for r in records}
    source_results = []
    for path in sources:
        item = dict(by_path[path], kind='source', comparisons=[])
        for reference in expectations[path]:
            expected = reference.get('sha256')
            valid = isinstance(expected, str) and len(expected) == 64 and all(c in '0123456789abcdef' for c in expected)
            item['comparisons'].append(dict(reference, match=item['sha256'] == expected if valid else None))
        source_results.append(item)
    unique = {}
    for path in packages:
        unique.setdefault(by_path[path]['sha256'], path)
    print(json.dumps({'phase': 'payload_start', 'unique_archives': len(unique)}), flush=True)
    payloads = {}

    def check_one(pair):
        digest, path = pair
        try:
            result = audit_payload(path)
        except Exception as exc:
            result = {'errors': [type(exc).__name__ + ': ' + str(exc)]}
        return digest, result

    with concurrent.futures.ThreadPoolExecutor(workers) as pool:
        for i, (digest, result) in enumerate(pool.map(check_one, unique.items()), 1):
            payloads[digest] = result
            if result['errors'] or i % 20 == 0:
                print(json.dumps({'phase': 'payload', 'done': i, 'name': result.get('name'),
                                  'errors': result['errors'][:4]}), flush=True)
    package_results = []
    for path in packages:
        item = dict(by_path[path], kind='package', payload=payloads[by_path[path]['sha256']])
        recipe = recipes.get(item['payload'].get('name'))
        item['matches_current_recipe'] = bool(recipe and item['payload'].get('recipe_digest') == recipe.digest)
        package_results.append(item)
    index_results = []
    for index in (root / 'dist/ki2').rglob('index*.json'):
        try:
            data = json.loads(index.read_text(encoding='utf-8'))
        except (ValueError, OSError) as exc:
            index_results.append({'index': str(index.relative_to(root)), 'error': str(exc)})
            continue
        for entry in data.get('packages', []):
            filename = entry.get('file', '')
            candidates = [index.parent / filename, index.parent.parent / 'packages' / entry.get('arch', data.get('arch', 'x86_64')) / filename,
                          index.parent.parent / 'packages' / filename]
            path = next((p.resolve() for p in candidates if p.is_file()), None)
            item = {'index': str(index.relative_to(root)), 'file': filename, 'expected_sha256': entry.get('sha256')}
            if path is None:
                item['status'] = 'missing'
            elif path not in by_path:
                item.update(status='outside_audited_paths', path=str(path))
            else:
                actual = by_path[path]
                item.update(path=actual['path'], actual_sha256=actual['sha256'],
                            status='match' if entry.get('sha256') == actual['sha256'] and entry.get('size', actual['bytes']) == actual['bytes'] else 'mismatch')
            index_results.append(item)
    summary = {'sources': len(sources), 'packages': len(packages), 'unique_packages': len(unique),
               'iso_baselines': len(images), 'source_hash_mismatches': sum(any(c['match'] is False for c in r['comparisons']) for r in source_results),
               'sources_without_reference': sum(not any(c['match'] is not None for c in r['comparisons']) for r in source_results),
               'package_payload_failures': sum(bool(r['payload']['errors']) for r in package_results),
               'unique_payload_failures': sum(bool(r['errors']) for r in payloads.values()),
               'index_statuses': dict(collections.Counter(r.get('status', 'error') for r in index_results)),
               'files_changed_during_audit': sum(r['changed_during_read'] for r in records),
               'missing_recipe_sources': len(missing_sources)}
    data = {'schema': 'kiki-integrity-audit-v1', 'timestamp_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'scope': 'All cached dist/sources files, all .ki2 under dist/build/x86_64, all dist ISO baselines. No VM disk reads or payload extraction.',
            'summary': summary, 'sources': source_results, 'packages': package_results,
            'indexes': index_results, 'images': [by_path[p] for p in images], 'missing_sources': missing_sources}
    with report_path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'phase': 'complete', 'report': str(report_path), 'summary': summary}), flush=True)
    return data


def build_gate(data):
    summary = data['summary']
    return not (summary['source_hash_mismatches'] or summary['package_payload_failures']
                or summary['files_changed_during_audit'] or summary['missing_recipe_sources']
                or any(status != 'match' and count for status, count in summary['index_statuses'].items()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--no-iso', action='store_true')
    args = parser.parse_args()
    result = run(args.root, args.report, args.workers, not args.no_iso)
    raise SystemExit(0 if build_gate(result) else 1)
