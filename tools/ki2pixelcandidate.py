"""Audit a pinned desktop baseline and build an isolated Paper Pixel candidate.

No operation publishes a release, changes the default desktop, or overwrites an
existing candidate. Run with the existing native KIKI SDK on Linux.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import ki2build
import ki2installcatalog
import ki2media
import ki2repo
from ki2integrity import audit_payload


def require(condition, message):
    if not condition:
        raise ValueError(message)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def baseline(repo, profile):
    pin = ki2build.tomllib.loads(profile.read_text())['profile']['prebuilt']
    base = repo / pin['repository']
    index_path = base / 'repo/index.x86_64.json'
    public = base / pin['public_key']
    require(ki2repo.file_sha256(index_path) == pin['index_sha256'], 'Baseline index SHA mismatch')
    require(ki2repo.file_sha256(public) == pin['public_key_sha256'], 'Baseline public key SHA mismatch')
    metadata = json.loads((base / 'repo/metadata.x86_64.json').read_text())
    require(ki2repo.verify_metadata_ed25519(metadata, public), 'Baseline signature invalid')
    require(metadata['index']['sha256'] == pin['index_sha256'], 'Signed index SHA mismatch')
    index = json.loads(index_path.read_text())
    names = [p['name'] for p in index['packages']]
    require(len(names) == len(set(names)), 'Ambiguous baseline package names')
    for record in index['packages']:
        require(Path(record['file']).name == record['file'], 'Unsafe package filename')
        require(ki2repo.file_sha256(base / 'packages/x86_64' / record['file']) == record['sha256'],
                'Baseline package SHA mismatch: ' + record['name'])
    selected = ki2installcatalog.expand(ki2installcatalog.load(), ['desktop-gnome'])['packages']
    closure = ki2media.runtime_closure(index, selected)
    return base, public, index, closure


def audit(args, repo):
    base, public, index, closure = baseline(repo, args.profile)
    def check(record):
        value = audit_payload(base / 'packages/x86_64' / record['file'])
        require(not value['errors'], str(value))
        return value
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        audits = list(pool.map(check, index['packages']))
    protected = set()
    for root in [repo / 'dist', repo / 'artifacts']:
        for pattern in (['*.ki2', '*.iso'] if root.name == 'dist' else ['*.iso']):
            protected.update(p for p in root.rglob(pattern) if p.is_file())
    protected.update(p for p in (repo / 'cmd').glob('kiki-installer*/*') if p.is_file())
    protected.add(args.profile)
    def digest(path):
        return str(path.resolve()), ki2repo.file_sha256(path)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        hashes = dict(pool.map(digest, sorted(protected)))
    save(args.output / 'preservation-before.json', hashes)
    save(args.output / 'baseline-audit.json', dict(
        schema='kiki-pixel-baseline-v1', signature='Ed25519 verified',
        profile=str(args.profile), repository=str(base), index_sha256=ki2repo.file_sha256(base/'repo/index.x86_64.json'),
        public_key_sha256=ki2repo.file_sha256(public), packages=len(audits),
        runtime_closure=closure, payload_audits=audits, protected_files=len(hashes),
        runtime_verified=False))
    print(json.dumps(dict(packages=len(audits), desktop_packages=len(closure), protected_files=len(hashes))))


def preserve(args, repo):
    previous = json.loads((args.output / 'preservation-before.json').read_text())
    def check(item):
        name, sha = item
        path = Path(name)
        if os.name == 'nt' and name.startswith('/mnt/') and len(name)>7 and name[5].isalpha() and name[6]=='/':
            path=Path(name[5].upper()+':/'+name[7:])
        return name if not path.is_file() or ki2repo.file_sha256(path)!=sha else None
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        changed=[p for p in pool.map(check,previous.items()) if p]
    save(args.output / 'preservation-after.json', dict(checked=len(previous), changed=changed))
    require(not changed, 'Original files changed: ' + str(changed))
    print('Preservation verified:', len(previous))


def build(args, repo):
    base, baseline_public, index, _ = baseline(repo, args.profile)
    require((args.output / 'baseline-audit.json').is_file(), 'Run baseline audit first')
    require(args.sdk and args.work and args.candidate and args.sign_key, 'Build needs SDK, work, candidate and signing key')
    work, candidate, sdk = args.work.resolve(), args.candidate.resolve(), args.sdk.resolve()
    require(not work.exists() and not candidate.exists(), 'Work and candidate must be new paths')
    require(not args.sign_key.resolve().is_relative_to(candidate), 'Signing key must stay private')
    work.mkdir(parents=True)
    staged = work / 'staged'
    source = work / 'admin-source'
    shutil.copytree(repo / 'cmd/kiki-admin', source,
                    ignore=shutil.ignore_patterns('kiki-admin', 'ui-test', '*.o', '__pycache__'))
    env = dict(os.environ, PKG_CONFIG_SYSROOT_DIR=str(sdk), PKG_CONFIG_LIBDIR=':'.join(
        str(sdk / p) for p in ['usr/lib/pkgconfig', 'usr/lib64/pkgconfig', 'usr/share/pkgconfig']))
    cflags = '--sysroot='+str(sdk)+' -O2 -pipe -Wall -Wextra -Werror -fstack-protector-strong'
    ldflags = '--sysroot='+str(sdk)+' '+' '.join('-L'+str(sdk/p)+' -Wl,-rpath-link,'+str(sdk/p)
        for p in ['usr/lib','usr/lib64','lib64'])+' -Wl,-z,relro,-z,now'
    subprocess.run(['make', '-C', str(source), 'kiki-admin', 'ui-test', 'CFLAGS='+cflags, 'LDFLAGS='+ldflags], env=env, check=True)
    admin = staged / 'kiki-admin'
    shutil.copytree(repo / 'distro/sources/kiki-admin', admin)
    (admin/'usr/bin').mkdir(parents=True, exist_ok=True)
    shutil.copy2(source/'kiki-admin', admin/'usr/bin/kiki-admin')
    for p in [admin/'usr/bin/kiki-admin', admin/'usr/bin/kiki-adminctl',
              admin/'usr/libexec/kiki-admin-helper', admin/'usr/libexec/kiki-admin-backend.py']:
        p.chmod(0o755)
    session = staged / 'kiki-session-gnome-ops'
    shutil.copytree(repo/'distro/sources/kiki-session-gnome-ops', session)
    shutil.copytree(repo/'desktop/gnome/kiki-ops', session/'usr/share/gnome-shell/extensions/kiki-ops@kikios.org')
    shutil.copytree(repo/'assets/desktop/paper-pixel', session/'usr/share/kiki-paper-pixel', dirs_exist_ok=True)
    for p in (session/'usr/libexec').iterdir(): p.chmod(0o755)
    packages = work / 'packages/x86_64'
    packages.mkdir(parents=True)
    changed = {}
    recipes = ki2build.load_recipes(repo/'distro/recipes')
    records = {r['name']: r for r in index['packages']}
    for name in ['kiki-admin', 'kiki-session-gnome-ops']:
        recipe = recipes[name]
        root = staged / name
        for p in root.rglob('__pycache__'): shutil.rmtree(p)
        package = packages / ki2build.package_filename(recipe, 'x86_64')
        dependency_keys = {}
        for dep in recipe.dependencies.get('runtime', []):
            if dep in changed:
                dependency_keys[dep] = ki2repo.read_package_manifest(packages/changed[dep]['file'])['build_key']
            else:
                record = records[dep]
                dependency_keys[dep] = ki2repo.read_package_manifest(base/'packages/x86_64'/record['file'])['build_key']
        key = ki2build.stable_hash(dict(recipe=recipe.digest, files=ki2build.package_file_manifest(root),
                                      baseline=ki2repo.file_sha256(base/'repo/index.x86_64.json'), dependencies=dependency_keys))
        ki2build.create_package(SimpleNamespace(arch='x86_64'), recipe, root, package, key, dependency_keys)
        audit_result = audit_payload(package)
        require(not audit_result['errors'], str(audit_result))
        changed[name] = dict(file=package.name, sha256=ki2repo.file_sha256(package), audit=audit_result)
    for r in index['packages']:
        if r['name'] in changed: continue
        # Existing immutable archive bytes are never written through a hardlink.
        source_package = base/'packages/x86_64'/r['file']
        dest = packages/r['file']
        try: os.link(source_package, dest)
        except OSError: shutil.copy2(source_package, dest)
    public = work/'paper-pixel.ed25519.pub'
    public.write_bytes(ki2repo.run_openssl(['pkey', '-in', str(args.sign_key), '-pubout']))
    subprocess.run([sys.executable, str(repo/'tools/ki2repo.py'), '--packages-dir', str(packages),
        '--repo-dir', str(work/'repo'), '--iso-dir', str(work/'iso'), 'generate', '--include-all-staged',
        '--channel', candidate.name, '--sign-key', str(args.sign_key), '--sign-algorithm', 'ed25519'], check=True)
    generated = json.loads((work/'repo/index.x86_64.json').read_text())
    require(ki2repo.verify_metadata_ed25519(json.loads((work/'repo/metadata.x86_64.json').read_text()), public), 'New signature invalid')
    selected = ki2installcatalog.expand(ki2installcatalog.load(), ['desktop-gnome'])['packages']+['kiki-session-gnome-ops']
    closure = ki2media.runtime_closure(generated, selected)
    owners = {}
    rows = {r['name']: r for r in generated['packages']}
    for name in closure:
        for entry in ki2repo.read_package_manifest(packages/rows[name]['file'])['files']:
            if entry['type'] == 'dir': continue
            require(entry['path'] not in owners, 'File ownership conflict: '+entry['path'])
            owners[entry['path']] = name
    candidate.mkdir(parents=True)
    shutil.copytree(work/'repo', candidate/'repo')
    shutil.copy2(public, candidate/public.name)
    (candidate/'packages/x86_64').mkdir(parents=True)
    for p in packages.glob('*.ki2'):
        try: os.link(p, candidate/'packages/x86_64'/p.name)
        except OSError: shutil.copy2(p, candidate/'packages/x86_64'/p.name)
    result = dict(schema='kiki-paper-pixel-build-v1', baseline_index_sha256=ki2repo.file_sha256(base/'repo/index.x86_64.json'),
        index_sha256=ki2repo.file_sha256(candidate/'repo/index.x86_64.json'), public_key_sha256=ki2repo.file_sha256(public),
        packages=len(rows), runtime_packages=len(closure), changed=changed, ownership_conflicts=0,
        work=str(work), candidate=str(candidate), iso_rebuilt=False, runtime_verified=False)
    save(candidate/'pixel-build.json', result)
    save(args.output/'candidate-build.json', result)
    print(json.dumps(result))


def overlay(args, repo):
    """A thin test repository for an exact, independently pinned installed GA.

    Unchanged archives are intentionally absent: the guest installer must first
    prove they already match. This overlay is never an ISO supplier repository.
    """
    require(args.ga_index and args.ga_input and args.candidate and args.sign_key and args.overlay,
            'Overlay requires pinned GA input/index, candidate, key and new overlay path')
    frozen = json.loads(args.ga_input.read_text())
    require(ki2repo.file_sha256(args.ga_index) == frozen['snapshot']['index_sha256'], 'GA index SHA mismatch')
    ga = json.loads(args.ga_index.read_text())
    require({r['name']: r['sha256'] for r in ga['packages']} ==
            {n: r['sha256'] for n,r in frozen['packages'].items()}, 'GA package map mismatch')
    report = json.loads((args.candidate/'pixel-build.json').read_text())
    pub = args.candidate/'paper-pixel.ed25519.pub'
    require(ki2repo.file_sha256(pub) == report['public_key_sha256'], 'Candidate key mismatch')
    require(ki2repo.file_sha256(args.candidate/'repo/index.x86_64.json') == report['index_sha256'], 'Candidate index mismatch')
    require(ki2repo.verify_metadata_ed25519(json.loads((args.candidate/'repo/metadata.x86_64.json').read_text()), pub), 'Candidate signature mismatch')
    require(not args.overlay.exists(), 'Overlay must be a new path')
    target = args.overlay
    (target/'repo').mkdir(parents=True)
    packages = target/'packages/x86_64'
    packages.mkdir(parents=True)
    changes = set(report['changed'])
    original = json.loads((args.candidate/'repo/index.x86_64.json').read_text())
    changed_records = [r for r in original['packages'] if r['name'] in changes]
    require(len(changed_records) == 2, 'Expected only administrator and session changes')
    ga['packages'] = [r for r in ga['packages'] if r['name'] not in changes] + changed_records
    ga['packages'].sort(key=lambda r:r['name'])
    ki2repo.write_json(target/'repo/index.x86_64.json', ga)
    for r in changed_records:
        src = args.candidate/'packages/x86_64'/r['file']
        require(ki2repo.file_sha256(src) == r['sha256'], 'Changed archive SHA mismatch')
        shutil.copy2(src, packages/r['file'])
    metadata = ki2repo.build_metadata(name='kiki-paper-pixel-ga-overlay', title='Paper Pixel installed-GA test overlay',
        description='Thin repository; exact unchanged GA packages must already be installed; not an ISO source',
        channel='paper-pixel-ga-overlay', arch='x86_64', base_url='',
        created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(), repo_dir=target/'repo',
        packages_dir=packages, iso_dir=target/'iso', packages=ga['packages'])
    ki2repo.write_json(target/'repo/metadata.x86_64.json', ki2repo.sign_metadata_ed25519(metadata, args.sign_key))
    shutil.copy2(pub, target/pub.name)
    save(target/'overlay.json', dict(schema='kiki-paper-pixel-test-overlay-v1',
        required_ga_index_sha256=frozen['snapshot']['index_sha256'], available_archives=2,
        changed=report['changed'], not_for_iso=True))
    print('Created exact installed-GA overlay:', target)


def refresh(args, repo):
    """Repackage session-only fixes, preserving the verified native app bytes.

    The prior repository may be thin on the signing host. The final client
    assembles unchanged archives only after checking every declared SHA.
    """
    require(args.prior and args.candidate and args.sign_key, 'Refresh needs prior, candidate and key')
    pin = ki2build.tomllib.loads(args.profile.read_text())['profile']['prebuilt']
    prior = args.prior.resolve()
    public = prior / pin['public_key']
    require(ki2repo.file_sha256(public) == pin['public_key_sha256'], 'Prior public key mismatch')
    require(ki2repo.file_sha256(prior/'repo/index.x86_64.json') == pin['index_sha256'], 'Prior index mismatch')
    require(ki2repo.verify_metadata_ed25519(json.loads((prior/'repo/metadata.x86_64.json').read_text()), public), 'Prior signature invalid')
    require(not args.candidate.exists(), 'Refresh output must be new')
    recipes = ki2build.load_recipes(repo/'distro/recipes')
    index = json.loads((prior/'repo/index.x86_64.json').read_text())
    rows = {r['name']:r for r in index['packages']}
    native = prior/'packages/x86_64'/rows['kiki-admin']['file']
    require(ki2repo.file_sha256(native) == rows['kiki-admin']['sha256'], 'Prior native administrator SHA mismatch')
    require(ki2repo.read_package_manifest(native)['recipe_digest'] == recipes['kiki-admin'].digest, 'Native app recipe changed; full native build required')
    out = args.candidate
    packages = out/'packages/x86_64'
    packages.mkdir(parents=True)
    root = out/'staged-session'
    shutil.copytree(repo/'distro/sources/kiki-session-gnome-ops', root)
    shutil.copytree(repo/'desktop/gnome/kiki-ops', root/'usr/share/gnome-shell/extensions/kiki-ops@kikios.org')
    shutil.copytree(repo/'assets/desktop/paper-pixel', root/'usr/share/kiki-paper-pixel', dirs_exist_ok=True)
    for p in (root/'usr/libexec').iterdir(): p.chmod(0o755)
    recipe = recipes['kiki-session-gnome-ops']
    previous = ki2repo.read_package_manifest(prior/'packages/x86_64'/rows[recipe.name]['file'])
    dependencies = previous['dependency_keys']
    key = ki2build.stable_hash(dict(recipe=recipe.digest, files=ki2build.package_file_manifest(root), dependencies=dependencies))
    package = packages/ki2build.package_filename(recipe, 'x86_64')
    ki2build.create_package(SimpleNamespace(arch='x86_64'), recipe, root, package, key, dependencies)
    session_record = ki2repo.package_entry(package, ki2repo.read_package_manifest(package))
    index['packages'] = [r for r in index['packages'] if r['name'] != recipe.name]+[session_record]
    index['packages'].sort(key=lambda r:r['name'])
    ki2repo.write_json(out/'repo/index.x86_64.json', index)
    new_public = out/'paper-pixel.ed25519.pub'
    new_public.write_bytes(ki2repo.run_openssl(['pkey','-in',str(args.sign_key),'-pubout']))
    metadata = ki2repo.build_metadata(name=out.name, title='KIKI Paper Pixel candidate',
        description='Session fixes with verified unchanged native administrator', channel=out.name, arch='x86_64',
        base_url='', created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(), repo_dir=out/'repo',
        packages_dir=packages, iso_dir=out/'iso', packages=index['packages'])
    ki2repo.write_json(out/'repo/metadata.x86_64.json', ki2repo.sign_metadata_ed25519(metadata,args.sign_key))
    shutil.copy2(native,packages/native.name)
    changed = {}
    for p in [packages/native.name,package]:
        result = audit_payload(p)
        require(not result['errors'], str(result))
        changed[result['name']] = dict(file=p.name,sha256=ki2repo.file_sha256(p),audit=result)
    selected = ki2installcatalog.expand(ki2installcatalog.load(), ['desktop-gnome'])['packages']+[recipe.name]
    closure = ki2media.runtime_closure(index, selected)
    result = dict(schema='kiki-paper-pixel-build-v1', index_sha256=ki2repo.file_sha256(out/'repo/index.x86_64.json'),
        public_key_sha256=ki2repo.file_sha256(new_public), packages=len(index['packages']),runtime_packages=len(closure),
        changed=changed, native_rebuilt=False, native_reused_sha256=rows['kiki-admin']['sha256'],
        prior_index_sha256=pin['index_sha256'], iso_rebuilt=False,runtime_verified=False,
        archive_supply='thin signing output; unchanged archives must be assembled and SHA verified')
    save(out/'pixel-build.json',result)
    print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['audit', 'preserve', 'build', 'overlay', 'refresh'])
    parser.add_argument('--profile', type=Path, default=Path('distro/profiles/desktop-gnome.toml'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--sdk', type=Path)
    parser.add_argument('--work', type=Path)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--sign-key', type=Path)
    parser.add_argument('--ga-index', type=Path)
    parser.add_argument('--ga-input', type=Path)
    parser.add_argument('--overlay', type=Path)
    parser.add_argument('--prior', type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    args.profile = args.profile.resolve()
    {'audit': audit, 'preserve': preserve, 'build': build, 'overlay': overlay, 'refresh': refresh}[args.action](args, repo)


if __name__ == '__main__':
    main()
