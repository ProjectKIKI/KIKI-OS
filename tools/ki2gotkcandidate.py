"""Build a gotk candidate from verified baseline media, replacing only two packages."""
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import ki2build
import ki2media
import ki2graphics


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--graphics', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--gui-release', required=True)
    args = p.parse_args()
    repo = Path(__file__).resolve().parents[1]
    baseline = args.baseline.resolve(strict=True)
    ki2media.verify_media(baseline, repo / 'build/ki2/keys/stage3-v3-repo.ed25519.pub')
    graphics = args.graphics.resolve(strict=True)
    runtime = json.loads((graphics / 'usr/share/kiki-installer-gtk/runtime-manifest.json').read_text())
    if runtime.get('installer_ui') != 'gotk':
        raise ValueError('requires a gotk graphics runtime')
    ki2graphics.relativize_runtime_links(graphics)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    packages = out / 'packages/x86_64'
    packages.mkdir(parents=True)
    changes = {'kiki-installer-gtk': graphics,
               'kiki-netconfig': repo / 'distro/sources/kiki-netconfig'}
    manifests = {}
    for source in sorted((baseline / 'kiki/packages/x86_64').glob('*.ki2')):
        manifest = ki2build.read_package_manifest(source)
        if manifest['name'] in changes:
            continue
        target = packages / source.name
        shutil.copyfile(source, target)
        if ki2build.file_sha256(source) != ki2build.file_sha256(target):
            raise ValueError('package copy mismatch')
        manifests[manifest['name']] = (target, manifest)
    recipes = ki2build.load_recipes(repo / 'distro/recipes')
    overrides = []
    for name, payload in changes.items():
        recipe = recipes[name]
        digest = hashlib.sha256(json.dumps(ki2build.package_file_manifest(payload), sort_keys=True).encode()).hexdigest()
        if name == 'kiki-installer-gtk':
            recipe = replace(recipe, release=args.gui_release,
                             summary='KIKI Go/gotk4 installer and Cage runtime',
                             license=recipe.license + ' AND BSD-3-Clause AND Apache-2.0',
                             digest=digest)
        target = packages / ki2build.package_filename(recipe, 'x86_64')
        ki2build.create_package(SimpleNamespace(arch='x86_64'), recipe, payload, target, digest, {})
        manifests[name] = (target, ki2build.read_package_manifest(target))
        overrides.append({'name': name, 'file': target.name, 'payload_sha256': digest})
    rootfs = out / 'rootfs'
    rootfs.mkdir()
    subprocess.run(['tar', '-xzf', str(baseline / 'kiki/rootfs.tar.gz'),
                    '--no-same-owner', '-C', str(rootfs)], check=True)
    state = json.loads((rootfs / 'var/lib/ki2/installed.json').read_text())
    installed = set(state['packages']) | set(changes)
    for name in changes:
        ki2build.extract_package_rootfs(manifests[name][0], rootfs)
    # Graphics contains the host util-linux ABI; preserve the target util-linux pair.
    ki2build.extract_package_rootfs(manifests['util-linux'][0], rootfs)
    ki2build.write_rootfs_installed_state(rootfs, [manifests[n] for n in sorted(installed)])
    (out / 'candidate.json').write_text(json.dumps({
        'baseline': str(baseline), 'overrides': overrides,
        'packages': [{'name': n, 'file': path.name, 'sha256': ki2build.file_sha256(path)}
                     for n, (path, _) in sorted(manifests.items())]}, indent=2)+'\n')
    print('Candidate packages:', len(manifests), flush=True)


if __name__ == '__main__':
    main()
