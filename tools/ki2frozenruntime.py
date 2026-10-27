#!/usr/bin/env python3
"""Repackage the rebuilt installer and validate four packages in disposable roots."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import importlib.util
from types import SimpleNamespace

import ki2build as build
from ki2integrity import audit_payload, sha256_file
from ki2stage3candidate import read_manifest
from ki2frozenrebuild import BASE, RUN, NAMES


def save(path, data):
    with path.open('x') as stream:
        json.dump(data, stream, indent=2)


def installer(repo):
    base, run = repo / BASE, repo / BASE / RUN
    work = Path('/home/tang/kiki-build/meson-1.9.2-frozen4-20261017/installer')
    binary = work / 'kiki-installer-gtk'
    records = json.loads((base / 'snapshot.json').read_text())
    entry = next(x for x in records['packages'] if x['name'] == NAMES[3])
    package = base / 'packages/x86_64' / entry['file']
    if sha256_file(package) != entry['sha256']:
        raise ValueError('installer baseline changed')
    cached = work / package.name
    shutil.copy2(package, cached)
    payload = run / 'inputs/installer-payload'
    if payload.exists():
        raise FileExistsError(payload)
    # Extract on the Linux filesystem, preserving Unix modes and symlinks.
    root = work / 'payload'
    build.extract_package_rootfs(cached, root)
    old = build.package_file_manifest(root)
    previous = root / 'usr/bin/kiki-installer-gtk'
    old_size = previous.stat().st_size
    shutil.copyfile(binary, previous)
    previous.chmod(0o755)
    manifest = root / 'usr/share/kiki-installer-gtk/runtime-manifest.json'
    runtime = json.loads(manifest.read_text())
    if runtime.get('installer_ui', 'c') != 'c' or runtime.get('gtk') != '4.12.3':
        raise ValueError('unsupported frozen installer runtime')
    runtime['bytes'] += binary.stat().st_size - old_size
    runtime['installer_ui'] = 'c'
    stylesheet = root / 'usr/share/kiki-installer-gtk/style.css'
    old_style_size = stylesheet.stat().st_size
    shutil.copyfile(run / 'inputs/cmd/kiki-installer-gtk/style.css', stylesheet)
    runtime['bytes'] += stylesheet.stat().st_size - old_style_size
    manifest.write_text(json.dumps(runtime, indent=2, sort_keys=True) + '\n')
    new = build.package_file_manifest(root)
    before, after = {x['path']: x for x in old}, {x['path']: x for x in new}
    changed = [key for key in sorted(set(before) | set(after)) if before.get(key) != after.get(key)]
    required = {'/usr/bin/kiki-installer-gtk', '/usr/share/kiki-installer-gtk/runtime-manifest.json'}
    if not required <= set(changed) or set(changed) - required - {'/usr/share/kiki-installer-gtk/style.css'}:
        raise ValueError('unexpected bootstrap runtime changes: ' + str(changed))
    # Use a relative symlink into dedicated Linux work, never the legacy rootfs.
    payload.symlink_to(root, target_is_directory=True)
    provenance = json.loads((run / 'inputs/installer-build-provenance.json').read_text())
    provenance.update(baseline_sha256=entry['sha256'], changed_payload_files=changed,
                      unchanged_payload_entries=len(before) - len(changed), payload_sha256=build.stable_hash(new))
    (run / 'inputs/installer-build-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    profile = json.loads((run / 'profile.json').read_text())
    envroot = Path(profile['root'])
    from ki2buildenv import check, stable
    state = check(run / 'profile.json')
    if sha256_file(Path(build.__file__)) != profile['builder_sha256']:
        raise ValueError('packager differs from frozen builder')
    recipe = build.load_recipes(run / 'recipes')[NAMES[3]]
    output = run / 'build/packages/x86_64' / build.package_filename(recipe, 'x86_64')
    if output.exists():
        raise FileExistsError(output)
    inputs = json.loads((run / 'preservation.json').read_text())['source_inputs']
    key = stable({'environment': state['fingerprint'], 'provenance': provenance,
                  'recipe': recipe.digest, 'source_inputs': inputs, 'builder': profile['builder_sha256']})
    dependencies = {x['name']: read_manifest(base / 'packages/x86_64' / x['file'])['build_key']
                    for x in records['packages'] if x['name'] in recipe.dependencies['runtime']}
    build.create_package(SimpleNamespace(arch='x86_64'), recipe, root, output, key, dependencies)
    save(run / 'installer-package.json', {'file': str(output), 'build_key': key, 'sha256': sha256_file(output),
                                         'recipe_digest': recipe.digest, 'builder_sha256': profile['builder_sha256']})
    save(run / 'installer-preservation.json', provenance)
    print(json.dumps(provenance, indent=2), flush=True)


PROBE = r'''
import ctypes as c
libc = c.CDLL('libc.so.6'); libc.gnu_get_libc_version.restype=c.c_char_p
assert libc.gnu_get_libc_version()==b'2.39'
gi=c.CDLL('libgirepository-1.0.so.1')
gi.g_irepository_get_default.restype=c.c_void_p
gi.g_irepository_require.argtypes=[c.c_void_p,c.c_char_p,c.c_char_p,c.c_int,c.POINTER(c.c_void_p)]
gi.g_irepository_require.restype=c.c_void_p
repository=gi.g_irepository_get_default()
for name,version in [(b'GDesktopEnums',b'3.0'),(b'Json',b'1.0'),(b'GUdev',b'1.0')]:
 error=c.c_void_p(); assert gi.g_irepository_require(repository,name,version,0,c.byref(error)),name
 assert not error.value; print('TYPELIB_OK',name.decode())
obj=c.CDLL('libgobject-2.0.so.0'); obj.g_object_unref.argtypes=[c.c_void_p]
glib=c.CDLL('libglib-2.0.so.0');glib.g_error_free.argtypes=[c.c_void_p];glib.g_free.argtypes=[c.c_void_p]
j=c.CDLL('libjson-glib-1.0.so.0');j.json_parser_new.restype=c.c_void_p
j.json_parser_load_from_data.argtypes=[c.c_void_p,c.c_char_p,c.c_ssize_t,c.POINTER(c.c_void_p)]
j.json_parser_load_from_data.restype=c.c_int
p=j.json_parser_new(); assert p
e=c.c_void_p(); assert j.json_parser_load_from_data(p,'{"상태":"정상","count":42}'.encode(),-1,c.byref(e)); assert not e.value
e=c.c_void_p(); assert not j.json_parser_load_from_data(p,b'{invalid',-1,c.byref(e)); assert e.value
glib.g_error_free(e); obj.g_object_unref(p); print('JSON_UTF8_AND_INVALID_INPUT_OK')
g=c.CDLL('libgudev-1.0.so.0');g.g_udev_client_new.argtypes=[c.c_void_p];g.g_udev_client_new.restype=c.c_void_p
client=g.g_udev_client_new(None);assert client;obj.g_object_unref(client);print('GUDEV_CLIENT_LIFECYCLE_OK')
gio=c.CDLL('libgio-2.0.so.0');gio.g_settings_new.argtypes=[c.c_char_p];gio.g_settings_new.restype=c.c_void_p
gio.g_settings_get_string.argtypes=[c.c_void_p,c.c_char_p];gio.g_settings_get_string.restype=c.c_void_p
gio.g_settings_set_string.argtypes=[c.c_void_p,c.c_char_p,c.c_char_p];gio.g_settings_set_string.restype=c.c_int
s=gio.g_settings_new(b'org.gnome.desktop.interface');assert s
assert gio.g_settings_set_string(s,b'color-scheme',b'prefer-dark')
v=gio.g_settings_get_string(s,b'color-scheme');assert c.string_at(v)==b'prefer-dark';glib.g_free(v);obj.g_object_unref(s)
print('GSETTINGS_MEMORY_READ_WRITE_OK')
'''


def verify_runtime(repo):
    if os.geteuid() != 0:
        raise ValueError('target chroot checks require root')
    base, run = repo / BASE, repo / BASE / RUN
    recipes = build.load_recipes(run / 'recipes')
    packages = run / 'build/packages/x86_64'
    profile = json.loads((run / 'profile.json').read_text())
    envroot = Path(profile['root'])
    result = {'status': 'pending', 'validated_packages': [], 'package_sha256': {}, 'rpath_runpath': {}, 'limitations': ['Disposable target-only roots and Xvfb GUI smoke; no VM boot, disk installation, LightDM/GNOME login, or hardware udev event claim.']}
    for name in NAMES:
        package = packages / build.package_filename(recipes[name], 'x86_64')
        audit = audit_payload(package)
        if audit['errors']:
            raise ValueError(str(audit['errors']))
        result['package_sha256'][name] = sha256_file(package)
    clean = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'TZ': 'UTC', 'PYTHONDONTWRITEBYTECODE': '1', 'GSETTINGS_BACKEND': 'memory', 'HOME': '/tmp'}
    def run_command(command, env=None, timeout=60):
        process = subprocess.run(command, env=env or clean, capture_output=True, text=True, timeout=timeout)
        if process.returncode:
            raise ValueError(str(command) + '\n' + process.stdout + process.stderr)
        return process.stdout + process.stderr
    with tempfile.TemporaryDirectory(prefix='kiki-frozen4-runtime-') as temporary:
        work = Path(temporary)
        native_cache = run / 'native-runtime-check.json'
        if native_cache.exists():
            cached_result = json.loads(native_cache.read_text())
            if any(cached_result['package_sha256'][name] != result['package_sha256'][name] for name in NAMES[:3]):
                raise ValueError('native package changed after validation')
            current_digests = result['package_sha256']
            result.update(cached_result)
            result['package_sha256'] = current_digests
            loader = result['target_loader_path']
        else:
            root = work / 'native'
            selected = build.dependency_closure(recipes, NAMES[:3], 'x86_64', include_build_deps=True)
            for name in selected:
                package = packages / build.package_filename(recipes[name], 'x86_64')
                cached = work / package.name
                shutil.copy2(package, cached)
                build.extract_package_rootfs(cached, root)
            (root / 'tmp').mkdir(exist_ok=True)
            (root / 'dev').mkdir(exist_ok=True)
            (root / 'dev/null').touch()
            loaders = [p for p in root.rglob('ld-linux-x86-64.so.2') if p.is_file() and not p.is_symlink()]
            if len(loaders) != 1:
                raise ValueError('expected one target loader')
            loader = '/' + str(loaders[0].relative_to(root))
            launch = ['/usr/sbin/chroot', str(root), loader, '--inhibit-cache', '--library-path', '/usr/lib:/usr/lib64:/lib:/lib64']
            result['native_loader'] = run_command(launch + ['--list', '/usr/bin/python3.12'])
            for name, library in [('json-glib', 'libjson-glib-1.0.so.0'), ('libgudev', 'libgudev-1.0.so.0')]:
                dynamic = run_command(['/usr/bin/readelf', '-d', str(root / 'usr/lib' / library)])
                if re.search(r'\((RPATH|RUNPATH)\)', dynamic):
                    raise ValueError('unexpected RPATH: ' + name)
                result['rpath_runpath'][name] = 'absent'
                result[name + '_loader'] = run_command(launch + ['--list', '/usr/lib/' + library])
            result['schema_compile'] = run_command(launch + ['/usr/bin/glib-compile-schemas', '--strict', '/usr/share/glib-2.0/schemas'])
            (root / 'probe.py').write_text(PROBE)
            result['native_probe'] = run_command(launch + ['/usr/bin/python3.12', '-B', '/probe.py'])
            # GLib trap tests re-exec their ELF. Execute the entire suite inside the
            # target root so children also use packaged glibc and GLib.
            builddir = envroot / 'work/x86_64/work/json-glib/build/json'
            source = envroot / 'work/x86_64/work/json-glib/source/json-glib-1.10.8'
            testroot = root / 'json-tests'
            shutil.copytree(builddir / 'json-glib/tests', testroot / 'build', symlinks=True)
            shutil.copytree(source / 'json-glib/tests', testroot / 'source', symlinks=True)
            testenv = dict(clean, G_TEST_SRCDIR='/json-tests/source', G_TEST_BUILDDIR='/json-tests/build',
                           LD_LIBRARY_PATH='/usr/lib:/usr/lib64:/lib:/lib64')
            tests = json.loads((builddir / 'meson-info/intro-tests.json').read_text())
            results = []
            for test in tests:
                oldpath = Path(test['cmd'][0])
                command = '/json-tests/build/' + str(oldpath.relative_to(builddir / 'json-glib/tests'))
                output = run_command(launch + [command] + test['cmd'][1:], env=testenv)
                results.append({'name': test['name'], 'status': 'pass', 'output': output})
            result['json_upstream_tests'] = results
            result['json_upstream_test_count'] = len(results)
            result["target_loader_path"] = loader
            save(native_cache, result)
        # GUI root includes only the preserved bootstrap payload and KIKI libc.
        gui = work / 'gui'
        installer_package = packages / build.package_filename(recipes[NAMES[3]], 'x86_64')
        cached = work / installer_package.name
        shutil.copy2(installer_package, cached)
        build.extract_package_rootfs(cached, gui)
        libc_package = packages / build.package_filename(recipes['glibc'], 'x86_64')
        cached_libc = work / libc_package.name
        if not cached_libc.exists():
            shutil.copy2(libc_package, cached_libc)
        build.extract_package_rootfs(cached_libc, gui)
        for sub in ('tmp', 'dev', 'proc'):
            (gui / sub).mkdir(exist_ok=True)
        # No disks, procfs or device tree are exposed. A plain empty file is
        # sufficient for this display-only smoke's /dev/null writes.
        (gui / 'dev/null').touch()
        guilaunch = ['/usr/sbin/chroot', str(gui), loader, '--inhibit-cache', '--library-path', '/usr/lib64:/lib64:/usr/lib:/lib']
        result['installer_loader'] = run_command(guilaunch + ['--list', '/usr/bin/kiki-installer-gtk'])
        dynamic = run_command(['/usr/bin/readelf', '-d', str(gui / 'usr/bin/kiki-installer-gtk')])
        if re.search(r'\((RPATH|RUNPATH)\)', dynamic):
            raise ValueError('unexpected installer RPATH')
        result['rpath_runpath'][NAMES[3]] = 'absent'
        display = ':197'
        attempt = len(list(run.glob('installer-xvfb-*.log'))) + 1
        xvfb_log = (run / ('installer-xvfb-%02d.log' % attempt)).open('x')
        server = subprocess.Popen(['/usr/bin/Xvfb', display, '-screen', '0', '1280x900x24', '-listen', 'tcp', '-nolisten', 'unix', '-ac'], stdout=xvfb_log, stderr=subprocess.STDOUT, env=clean)
        try:
            for _ in range(50):
                if server.poll() is not None:
                    raise ValueError('Xvfb exited')
                ready = subprocess.run(['/usr/bin/xdpyinfo', '-display', '127.0.0.1' + display], env=clean, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if ready.returncode == 0:
                    break
                time.sleep(.1)
            else:
                raise ValueError('Xvfb not ready')
            guienv = dict(clean, DISPLAY='127.0.0.1' + display, GDK_BACKEND='x11', GSK_RENDERER='cairo', GTK_A11Y='none', NO_AT_BRIDGE='1', XDG_RUNTIME_DIR='/tmp', GSETTINGS_SCHEMA_DIR='/usr/share/glib-2.0/schemas')
            with (run / ('installer-gui-%02d.log' % attempt)).open('x') as log:
                app = subprocess.Popen(guilaunch + ['/usr/bin/kiki-installer-gtk'], env=guienv, stdout=log, stderr=subprocess.STDOUT)
                try:
                    windows = ''
                    for _ in range(500):
                        if app.poll() is not None:
                            raise ValueError('installer exited before displaying its window')
                        windows = run_command(['/usr/bin/xwininfo', '-display', guienv['DISPLAY'], '-root', '-tree'], env=dict(clean, LC_ALL='C.utf8'))
                        if 'Scratch Pad' in windows:
                            break
                        time.sleep(.1)
                    else:
                        raise ValueError('installer language window missing: ' + windows + '\n' + (run / ('installer-gui-%02d.log' % attempt)).read_text())
                    result['installer_language_window'] = windows
                    # Activate the focused language button with XTest; no
                    # installation controls or disk paths are exercised.
                    import ctypes as c
                    x = c.CDLL('libX11.so.6'); xt = c.CDLL('libXtst.so.6')
                    x.XOpenDisplay.argtypes=[c.c_char_p]; x.XOpenDisplay.restype=c.c_void_p
                    x.XKeysymToKeycode.argtypes=[c.c_void_p,c.c_ulong]; x.XKeysymToKeycode.restype=c.c_uint
                    x.XSetInputFocus.argtypes=[c.c_void_p,c.c_ulong,c.c_int,c.c_ulong]
                    x.XFlush.argtypes=[c.c_void_p]; x.XCloseDisplay.argtypes=[c.c_void_p]
                    xt.XTestFakeKeyEvent.argtypes=[c.c_void_p,c.c_uint,c.c_int,c.c_ulong]
                    d=x.XOpenDisplay(guienv['DISPLAY'].encode()); assert d
                    try:
                        window = re.search(r'(0x[0-9a-f]+) "Scratch Pad', windows)
                        if not window:
                            raise ValueError('language window XID missing')
                        x.XSetInputFocus(d,int(window.group(1),16),1,0)
                        for symbol in (0xff09,0xff0d):
                            key=x.XKeysymToKeycode(d,symbol)
                            xt.XTestFakeKeyEvent(d,key,1,0);xt.XTestFakeKeyEvent(d,key,0,0)
                        x.XFlush(d)
                    finally:
                        x.XCloseDisplay(d)
                    for _ in range(500):
                        if app.poll() is not None:
                            raise ValueError('installer exited while opening the main UI')
                        windows = run_command(['/usr/bin/xwininfo', '-display', guienv['DISPLAY'], '-root', '-tree'], env=dict(clean, LC_ALL='C.utf8'))
                        if 'KIKI OS' in windows:
                            break
                        time.sleep(.1)
                    else:
                        raise ValueError('installer main window missing')
                    result['installer_main_window'] = windows
                    result['installer_gui_smoke'] = 'Language chooser and main installer window displayed with preserved bundle and KIKI glibc; process remained alive. No install requested.'
                finally:
                    app.terminate()
                    app.wait(timeout=10)
        finally:
            server.terminate()
            server.wait(timeout=10)
            xvfb_log.close()
    result.update(status='pass', validated_packages=NAMES,
                  installer_preservation=json.loads((run / 'installer-preservation.json').read_text()),
                  environment_fingerprint=json.loads((envroot / 'manifests/environment.json').read_text())['fingerprint'])
    save(run / 'runtime-check.json', result)
    print(json.dumps({k: v for k, v in result.items() if k not in ('json_upstream_tests', 'installer_preservation')}, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['installer', 'verify'])
    parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    frozen = args.repo_root / BASE / 'build-tools/ki2build.py'
    profile = json.loads((args.repo_root / BASE / RUN / 'profile.json').read_text())
    if sha256_file(frozen) != profile['builder_sha256']:
        raise ValueError('frozen builder changed')
    spec = importlib.util.spec_from_file_location('ki2_frozen_build', frozen)
    build = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = build
    spec.loader.exec_module(build)
    (installer if args.command == 'installer' else verify_runtime)(args.repo_root)
