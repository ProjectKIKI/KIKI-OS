"""Snapshot current package artifacts for a fresh installer candidate, without signing."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

import ki2build


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def snapshot(repo, baseline_index, destination, profile_path):
    recipes = ki2build.load_recipes(repo / 'distro/recipes')
    profile = ki2build.load_profile(profile_path)
    baseline = json.loads(baseline_index.read_text())
    if baseline['arch'] != 'x86_64':
        raise ValueError('candidate supports x86_64 only')
    names = {entry['name'] for entry in baseline['packages']}
    names.update(profile['packages'])
    names = ki2build.dependency_closure(recipes, sorted(names), 'x86_64', include_build_deps=False)
    sources = []
    for name in names:
        filename = ki2build.package_filename(recipes[name], 'x86_64')
        if Path(filename).name != filename:
            raise ValueError('unsafe package filename')
        source = repo / 'dist/ki2/packages/x86_64' / filename
        if not source.is_file():
            raise FileNotFoundError(source)
        sources.append((name, source))
    # Never merge a new snapshot into an older candidate or erase its inputs.
    destination.mkdir(parents=True, exist_ok=False)
    packages = destination / 'packages/x86_64'
    packages.mkdir(parents=True)
    manifest = []
    for name, source in sources:
        original_hash = sha256_file(source)
        target = packages / source.name
        shutil.copy2(source, target)
        copied_hash = sha256_file(target)
        if copied_hash != original_hash or source.stat().st_size != target.stat().st_size:
            raise ValueError('package changed during copy: ' + source.name)
        manifest.append({'name':name, 'file':source.name, 'sha256':copied_hash,
                         'size':target.stat().st_size})
    (destination / 'snapshot.json').write_text(json.dumps({'arch':'x86_64','packages':manifest},
                                                        indent=2) + '\n')
    print('verified package copies:',len(manifest))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--baseline-index',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    parser.add_argument('--profile',type=Path,required=True)
    args=parser.parse_args()
    snapshot(args.repo_root,args.baseline_index,args.destination,args.profile)


if __name__=='__main__':
    main()
