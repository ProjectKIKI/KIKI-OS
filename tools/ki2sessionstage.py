#!/usr/bin/env python3
"""Split session packages and repair file suppliers in the isolated candidate."""
import json
from pathlib import Path
import shutil

import ki2sessioncandidate as c
from ki2integrity import sha256_file
from ki2stage3candidate import read_manifest


catalog = json.loads((c.BASE / 'recipes/catalog.json').read_text())
original = {x['name']: x for x in catalog['recipes']}
snapshot = json.loads((c.BASE / 'snapshot.json').read_text())
records = {x['name']: x for x in snapshot['packages']}


def clone(name):
    return json.loads(json.dumps(original[name]))


def existing_payload(name):
    record = records[name]
    archive = c.BASE / 'packages/x86_64' / record['file']
    if sha256_file(archive) != record['sha256']:
        raise ValueError('parent package changed: ' + name)
    local = c.WORK / 'sources' / archive.name
    if not local.exists():
        shutil.copy2(archive, local)
    if sha256_file(local) != record['sha256']:
        raise ValueError('cached package changed: ' + name)
    payload = c.WORK / ('repack-' + name)
    c.build.extract_package_rootfs(local, payload)
    return payload


def local_recipe(name, payload, runtime):
    return dict(name=name, version='0.1.0', release='1', summary='KIKI native login and user-session integration',
                license='GPL-3.0-or-later', tier='base', architectures=['x86_64'],
                source=dict(type='local', path=str(payload)),
                dependencies=dict(build=[], runtime=runtime), build=dict(system='copy'))


def stage():
    systemd = c.WORK / 'build/systemd/source/dest'
    library = c.WORK / 'split-libsystemd'
    library.mkdir(exist_ok=False)
    paths = list(systemd.glob('usr/lib/libsystemd.so*')) + [systemd / 'usr/lib/pkgconfig/libsystemd.pc']
    paths += list(systemd.glob('usr/include/systemd/*.h'))
    for p in paths:
        relative = p.relative_to(systemd)
        target = library / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), target)
    raw = clone('systemd')
    raw.update(name='libsystemd', release='6', summary='Native systemd client library and development files')
    raw['dependencies'] = dict(build=[], runtime=['glibc', 'libcap', 'xz', 'zstd'])
    raw['build'] = dict(system='copy')
    c.package(raw, library, dict(split_from='systemd-255.7-6', purpose='Remove Linux-PAM/systemd runtime dependency cycle'))

    pam = existing_payload('linux-pam')
    raw = clone('linux-pam'); raw['release'] = '2'
    raw['dependencies']['runtime'] = ['libsystemd' if x == 'systemd' else x for x in raw['dependencies']['runtime']]
    c.package(raw, pam, dict(parent_sha256=records['linux-pam']['sha256'], unchanged_payload=True, dependency_supplier='libsystemd'))

    integration = c.WORK / 'session-integration'
    shutil.copytree(c.TARGET / 'payload', integration)
    pam_config = c.WORK / 'pam-config'
    (pam_config/'etc').mkdir(parents=True)
    shutil.move(str(integration/'etc/pam.d'), pam_config/'etc/pam.d')
    shadow = c.WORK / 'build/shadow/source/dest'
    for p in (shadow/'etc/pam.d').glob('*'):
        dest = pam_config/'etc/pam.d'/p.name
        if not dest.exists():
            shutil.copy2(p, dest)
        p.unlink()
    (systemd/'etc/pam.d/systemd-user').unlink(missing_ok=True)
    common = {
        'common-auth':'auth required pam_unix.so\n',
        'common-account':'account required pam_unix.so\n',
        'common-password':'password required pam_unix.so sha512 shadow\n',
        'common-session':'session required pam_unix.so\nsession required pam_limits.so\nsession optional pam_env.so\nsession optional pam_systemd.so\n',
        'common-session-noninteractive':'session required pam_unix.so\nsession required pam_limits.so\nsession optional pam_env.so\n',
    }
    for name, text in common.items():
        (pam_config/'etc/pam.d'/name).write_text(text)
    c.package(local_recipe('kiki-pam-config', pam_config, ['linux-pam']), pam_config,
              dict(policy_files=c.build.package_file_manifest(pam_config)))
    raw = clone('shadow'); raw['release'] = '3'
    raw['dependencies']['build'] = ['linux-pam', 'linux-headers']
    raw['dependencies']['runtime'] += ['linux-pam', 'kiki-pam-config']
    raw['build']['configure_options'] = ['--prefix=/usr', '--sysconfdir=/etc', '--with-libpam', '--without-selinux', '--without-acl', '--without-libbsd', '--without-bcrypt', '--without-libcrack']
    c.package(raw, shadow, dict(source_sha256=raw['source']['sha256'], pam_enabled=True, policy_supplier='kiki-pam-config'))
    raw = clone('systemd'); raw['release'] = '7'
    raw['dependencies']['build'] = ['linux-pam', 'linux-headers']
    raw['dependencies']['runtime'] += ['libsystemd', 'linux-pam', 'kiki-pam-config']
    raw['build']['configure_options'] += ['-Dpam=true', '-Dpamconfdir=/etc/pam.d', '-Dbzip2=false', '-Dimportd=false']
    c.package(raw, systemd, dict(source_sha256=raw['source']['sha256'], pam_enabled=True, split_library='libsystemd', policy_supplier='kiki-pam-config'))

    sockets = integration / 'usr/lib/systemd/user/sockets.target.wants'
    sockets.mkdir(parents=True)
    (sockets/'dbus.socket').symlink_to('../dbus.socket')
    (integration/'usr/libexec/kiki-wait-online-needed').chmod(0o755)
    c.package(local_recipe('kiki-session-integration', integration,
                          ['systemd', 'shadow', 'dbus', 'python', 'kiki-pam-config']), integration,
              dict(files=c.build.package_file_manifest(integration)))

    e2 = existing_payload('e2fsprogs')
    util = c.WORK / 'util-linux-reference'
    duplicates = []
    for p in list(e2.rglob('*')):
        if p.is_dir() and not p.is_symlink():
            continue
        relative = p.relative_to(e2)
        if (util/relative).exists() or str(relative).startswith(('usr/include/blkid/', 'usr/include/uuid/')):
            duplicates.append(str(relative)); p.unlink()
    raw = clone('e2fsprogs'); raw['release'] = str(int(raw['release']) + 1)
    raw['dependencies']['runtime'] = list(dict.fromkeys(raw['dependencies']['runtime'] + ['util-linux']))
    c.package(raw, e2, dict(parent_sha256=records['e2fsprogs']['sha256'], removed_duplicate_files=duplicates,
                           supplier='util-linux for UUID/blkid development files and shared command paths'))
    print('Session staging packages created; runtime validation and repository promotion still pending.')


if __name__ == '__main__':
    stage()
