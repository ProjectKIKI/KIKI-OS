#!/usr/bin/env python3
"""Build locked GNOME sources with the isolated target SDK and GI launchers."""
import argparse
import contextlib
import difflib
import io
import json
from pathlib import Path
import shutil
import tarfile
import tomli

import ki2sessioncandidate as c
from ki2integrity import sha256_file

PRESETS = {
    'upower': dict(options=['-Dman=false','-Dgtk-doc=false','-Dinstalled_tests=false','-Dintrospection=enabled','-Didevice=enabled','-Dpolkit=enabled','-Dos_backend=linux',
                           '-Dsystemdsystemunitdir=/usr/lib/systemd/system','-Dudevrulesdir=/usr/lib/udev/rules.d','-Dudevhwdbdir=/usr/lib/udev/hwdb.d','-Dhistorydir=/var/lib/upower','-Dstatedir=/var/lib/upower','-Dzshcompletiondir=no'],
                   dependencies=['glib','libgudev','libimobiledevice','libplist','polkit','systemd','glibc'],license='GPL-2.0-or-later'),
    'gnome-autoar': dict(options=['-Dgtk=false','-Dtests=false','-Dintrospection=enabled','-Dvapi=false'],dependencies=['glib','libarchive'],license='LGPL-2.1-or-later'),
    'hicolor-icon-theme': dict(options=[],dependencies=[],license='GPL-2.0-or-later'),
    'adwaita-icon-theme': dict(options=[],dependencies=[],license='LGPL-3.0-or-later OR CC-BY-SA-3.0'),
    'gnome-settings-daemon-schemas': dict(source_name='gnome-settings-daemon',options=[],dependencies=['gsettings-desktop-schemas'],license='GPL-2.0-or-later'),
    'gweather-locations': dict(options=[],dependencies=[],license='GPL-2.0-or-later'),
    'libxmlb': dict(options=['-Dgtkdoc=false','-Dintrospection=true','-Dtests=false','-Dcli=true','-Dlzma=enabled','-Dzstd=enabled'],
                    dependencies=['glib','xz','zstd'],license='LGPL-2.1-or-later'),
    'appstream': dict(options=['-Dstemming=false','-Dsystemd=false','-Dqt=false','-Dcompose=false','-Dbash-completion=false','-Dgir=true',
                               '-Dtools=false','-Dsvg-support=false','-Ddocs=false','-Dapidocs=false','-Dinstall-docs=false','-Dman=false','-Ddisplay-detection=none'],
                      dependencies=['glib','libxml2','libfyaml','libxmlb','curl','zstd'],license='LGPL-2.1-or-later'),
    'geocode-glib': dict(options=['-Dsoup2=false','-Denable-gtk-doc=false','-Denable-installed-tests=false','-Denable-introspection=true'],
                         dependencies=['glib','json-glib','libsoup'],license='LGPL-2.1-or-later'),
    'geoclue': dict(options=['-Denable-backend=false','-Dlibgeoclue=true','-Dintrospection=true','-Dvapi=false','-Dgtk-doc=false','-Ddemo-agent=false',
                             '-Dwifi-source=false','-D3g-source=false','-Dcdma-source=false','-Dmodem-gps-source=false','-Dnmea-source=false','-Dip-source=false','-Dcompass=false'],
                    dependencies=['glib'],license='LGPL-2.1-or-later'),
    'libgweather': dict(options=['-Denable_vala=false','-Dgtk_doc=false','-Dintrospection=true','-Dtests=false'],
                        dependencies=['glib','libsoup','geocode-glib','gweather-locations','tzdata'],license='LGPL-2.1-or-later'),
    'libnotify': dict(options=['-Dgtk_doc=false','-Ddocbook_docs=disabled','-Dman=false','-Dtests=false','-Dintrospection=enabled'],
                      dependencies=['glib','gdk-pixbuf'],license='LGPL-2.1-or-later'),
    'gsound': dict(options=['-Dgtk_doc=false','-Dintrospection=true','-Denable_vala=false'],dependencies=['glib','libcanberra'],license='LGPL-2.1-or-later'),
    'gnome-bluetooth': dict(options=['-Dsendto=false','-Dgtk_doc=false','-Dintrospection=true'],
                            dependencies=['glib','gtk','gsound','libadwaita','libnotify','systemd','upower'],license='LGPL-2.1-or-later'),
    'pulseaudio': dict(options=['-Ddaemon=false','-Dclient=true','-Ddoxygen=false','-Dman=false','-Dtests=false','-Ddatabase=simple',
                                '-Dbluez5=disabled','-Dgstreamer=disabled','-Dgtk=disabled','-Dasyncns=disabled','-Davahi=disabled','-Dorc=disabled','-Dfftw=disabled','-Djack=disabled','-Dglib=enabled',
                                '-Dbashcompletiondir=no','-Dzshcompletiondir=no'],dependencies=['glibc','glib','dbus','libsndfile'],license='LGPL-2.1-or-later'),
    'mutter': dict(options=['-Dxwayland=false','-Dopengl=false','-Dgles2=true','-Degl=true','-Dnative_backend=true','-Dlogind=true','-Dudev=true',
                            '-Dremote_desktop=false','-Dlibwacom=false','-Dsound_player=false','-Dstartup_notification=false','-Dprofiler=false','-Dtests=disabled',
                            '-Dcogl_tests=false','-Dclutter_tests=false','-Dmutter_tests=false','-Dinstalled_tests=false','-Ddocs=false','-Ddevkit=disabled','-Dbash_completion=false'],
                   dependencies=['glib','gtk','graphene','glycin','cairo','pixman','gsettings-desktop-schemas','libxkbcommon','at-spi2-core','colord','lcms2','libei',
                                 'libdisplay-info','libdrm','wayland','pango','harfbuzz','fribidi','gnome-desktop','libglvnd','libsystemd','libgudev','kiki-mesa-bootstrap','libinput'],license='GPL-2.0-or-later'),
    'gnome-shell': dict(options=['-Dnetworkmanager=false','-Dportal_helper=false','-Dcamera_monitor=false','-Dsystemd=true','-Dman=false','-Dtests=false'],
                        dependencies=['glib','at-spi2-core','evolution-data-server','gcr','gdk-pixbuf','gjs','gtk','libxml2','mutter','polkit','gsettings-desktop-schemas',
                                      'gnome-desktop','pango','libsystemd','gdm'],license='GPL-2.0-or-later'),
    'gdm': dict(options=['-Dx11-support=false','-Ddefault-pam-config=none','-Dsplit-authentication=false','-Dlibaudit=disabled','-Dplymouth=disabled','-Dselinux=disabled',
                         '-Dsystemdsystemunitdir=/usr/lib/systemd/system','-Dsystemduserunitdir=/usr/lib/systemd/user','-Dworking-dir=/var/lib/gdm','-Dinitial-vt=1'],
                dependencies=['glib','libgudev','accountsservice','polkit','json-glib','linux-pam','libsystemd','dconf','at-spi2-core','kiki-pam-config'],license='GPL-2.0-or-later'),
    'gnome-desktop': dict(options=['-Dlegacy_library=false','-Dbuild_gtk4=true','-Ddesktop_docs=false','-Ddebug_tools=false','-Dgtk_doc=false','-Dinstalled_tests=false','-Dintrospection=true','-Dsystemd=enabled','-Dudev=enabled'],
                          dependencies=['glib','gtk','gsettings-desktop-schemas','fontconfig','libxkbcommon','xkeyboard-config','iso-codes','libsystemd','bubblewrap'],license='LGPL-2.1-or-later'),
    'gnome-session': dict(options=['-Ddocbook=false','-Dman=false','-Dsystemduserunitdir=/usr/lib/systemd/user'],
                          dependencies=['glib','gnome-desktop','libsystemd','gnome-shell'],license='GPL-2.0-or-later'),
    'libgusb': dict(options=['-Dtests=false','-Dvapi=false','-Ddocs=false','-Dintrospection=true','-Dumockdev=disabled'],
                    dependencies=['glib','libusb','json-glib'],license='LGPL-2.1-or-later'),
    'libsecret': dict(options=['-Dvapi=false','-Dgtk_doc=false','-Dmanpage=false','-Dintrospection=true','-Dbash_completion=disabled','-Dtpm2=false'],
                     dependencies=['glib','libgcrypt'],license='LGPL-2.1-or-later'),
    'gcr': dict(options=['-Dvapi=false','-Dgtk_doc=false','-Dintrospection=true','-Dgtk4=true','-Dssh_agent=false','-Dsystemd=enabled','-Dgpg_path=/usr/bin/gpg'],
                dependencies=['glib','libgcrypt','p11-kit','gtk','libsystemd'],license='LGPL-2.1-or-later'),
    'libadwaita': dict(options=['-Dintrospection=enabled','-Dvapi=false','-Ddocumentation=false','-Dtests=false','-Dexamples=false'],
                       dependencies=['gtk','glib','fribidi'],license='LGPL-2.1-or-later'),
    'libei': dict(options=['-Dtests=disabled','-Ddocumentation=[]','-Dliboeffis=disabled','-Dlibei=enabled','-Dlibeis=enabled','-Dsd-bus-provider=libsystemd'],
                  dependencies=['glibc','libsystemd'],license='MIT'),
    'libdisplay-info': dict(options=[],dependencies=['glibc'],license='MIT'),
    'colord': dict(options=['-Ddaemon=false','-Dargyllcms_sensor=false','-Dbash_completion=false','-Dman=false','-Ddocs=false','-Dtests=false','-Dvapi=false'],
                   dependencies=['glib','lcms2','libgudev','polkit'],license='LGPL-2.1-or-later'),
    'glib-networking': dict(options=['-Dgnutls=enabled','-Dopenssl=disabled','-Dlibproxy=disabled','-Denvironment_proxy=enabled','-Dgnome_proxy=enabled','-Dinstalled_tests=false'],
                            dependencies=['glib','gnutls','gsettings-desktop-schemas','ca-certificates'],license='LGPL-2.1-or-later'),
    'libsoup': dict(options=['-Dintrospection=enabled','-Dvapi=disabled','-Ddocs=disabled','-Dtests=false','-Dsysprof=disabled','-Dgssapi=disabled','-Dntlm=disabled','-Dbrotli=disabled','-Dtls_check=false'],
                   dependencies=['glib','glib-networking','libpsl','nghttp2','zlib'],license='LGPL-2.1-or-later'),
    'glib': dict(options=['-Ddefault_library=shared', '-Dtests=false', '-Dinstalled_tests=false', '-Ddocumentation=false',
                         '-Dman-pages=disabled', '-Dnls=enabled', '-Dglib_debug=disabled', '-Dselinux=disabled', '-Dlibmount=enabled',
                         '-Dlibelf=disabled', '-Dsysprof=disabled', '-Ddtrace=disabled', '-Dsystemtap=disabled', '-Dintrospection=enabled'],
                 dependencies=['glibc','pcre2','libffi','zlib','util-linux'], license='LGPL-2.1-or-later'),
    'gjs': dict(options=['-Dinstalled_tests=false', '-Dprofiler=disabled', '-Dreadline=disabled', '-Dskip_gtk_tests=true', '-Dskip_dbus_tests=true'],
                dependencies=['glib','gobject-introspection','libffi','cairo','mozjs','libstdcxx'], license='MIT OR LGPL-2.0-or-later'),
    'libdrm': dict(options=['-Dintel=disabled', '-Dtests=false', '-Dman-pages=disabled', '-Dvalgrind=disabled'],
                   dependencies=['glibc'], license='MIT'),
    'libevdev': dict(options=['-Dtests=disabled', '-Dtools=enabled', '-Ddocumentation=disabled'],
                     dependencies=['glibc'], license='MIT'),
    'libinput': dict(options=['-Dlibwacom=false', '-Dmtdev=false', '-Ddebug-gui=false', '-Dtests=false', '-Dinstall-tests=false',
                             '-Ddocumentation=false', '-Dzshcompletiondir=no', '-Dlua-plugins=disabled', '-Dinternal-event-debugging=false'],
                     dependencies=['glibc','systemd','libevdev'], license='MIT'),
    'libglvnd': dict(options=['-Dx11=disabled', '-Dglx=disabled', '-Degl=true', '-Dgles1=true', '-Dgles2=true', '-Dheaders=true'],
                     dependencies=['glibc'], license='MIT'),
    'accountsservice': dict(options=['-Dsystemdsystemunitdir=/usr/lib/systemd/system', '-Dadmin_group=sudo', '-Dminimum_uid=1000',
                                    '-Dvapi=false', '-Dintrospection=true', '-Ddocbook=false', '-Dgtk_doc=false', '-Dtests=false', '-Dcreate_homed=false'],
                            dependencies=['glib','dbus','polkit','libxcrypt','libsystemd'], license='GPL-3.0-or-later'),
    'libepoxy': dict(options=['-Ddocs=false', '-Dtests=false', '-Dx11=false', '-Dglx=no', '-Degl=yes'],
                     dependencies=['glibc']),
    'shared-mime-info': dict(options=['-Dbuild-spec=false', '-Dbuild-tests=false', '-Dbuild-tools=true', '-Dbuild-translations=true', '-Dupdate-mimedb=false'],
                             dependencies=['glib', 'libxml2', 'libstdcxx']),
    'gtk': dict(options=['-Dx11-backend=false', '-Dwayland-backend=true', '-Dbroadway-backend=false', '-Dvulkan=disabled',
                        '-Dmedia-gstreamer=disabled', '-Dprint-cups=disabled', '-Ddocumentation=false', '-Dman-pages=false',
                        '-Dbuild-demos=false', '-Dbuild-examples=false', '-Dbuild-tests=false', '-Dbuild-testsuite=false', '-Dintrospection=enabled'],
                dependencies=['glib','cairo','pango','graphene','at-spi2-core','gdk-pixbuf','glycin','wayland','libxkbcommon','libtiff','libepoxy']),
    'bubblewrap': dict(options=['-Dman=disabled', '-Dselinux=disabled', '-Dtests=false', '-Dbash_completion=disabled', '-Dzsh_completion=disabled'],
                       dependencies=['glibc', 'libcap']),
    'gdk-pixbuf': dict(options=['-Ddocumentation=false', '-Dman=false', '-Dintrospection=enabled', '-Dtests=false', '-Dinstalled_tests=false',
                               '-Dthumbnailer=disabled', '-Dglycin=disabled', '-Dpng=enabled', '-Djpeg=enabled', '-Dtiff=disabled', '-Dgif=enabled', '-Dbuiltin_loaders=png,jpeg,gif,bmp,ico'],
                       dependencies=['glib', 'libpng', 'libjpeg-turbo', 'shared-mime-info']),
    'librsvg': dict(options=['-Ddocs=disabled', '-Dintrospection=enabled', '-Dpixbuf=enabled', '-Dpixbuf-loader=enabled',
                            '-Drsvg-convert=disabled', '-Dvala=disabled', '-Dtests=false', '-Davif=disabled', '-Dtriplet=x86_64-unknown-linux-gnu'],
                    dependencies=['glib', 'cairo', 'pango', 'gdk-pixbuf', 'libxml2', 'libgcc']),
    'at-spi2-core': dict(options=['-Dx11=disabled', '-Ddocs=false', '-Dintrospection=enabled', '-Ddefault_bus=dbus-daemon', '-Dgtk2_atk_adaptor=false'],
                         dependencies=['glib', 'dbus', 'libxml2', 'systemd']),
    'glycin': dict(options=['-Dlibglycin=true', '-Dlibglycin-gtk4=false', '-Dglycin-thumbnailer=false', '-Dglycin-loaders=true',
                            '-Dloaders=glycin-image-rs,glycin-svg', '-Dtests=false', '-Dintrospection=true', '-Dvapi=false', '-Dlto=false'],
                   dependencies=['glib', 'fontconfig', 'libseccomp', 'libgcc', 'lcms2', 'bubblewrap','librsvg']),
}


def build(name, configure_only=False, refresh_dependencies=False, release_override=None):
    preset = PRESETS[name]
    lock = json.loads((c.TARGET/'gnome50-source-lock.json').read_text())
    source_name = preset.get('source_name',name)
    source = next(x for x in lock['sources'] if x.get('name') == source_name or Path(x['file']).name.startswith(source_name + '-'))
    archive = Path(source['file'])
    if sha256_file(archive) != source['sha256']:
        raise ValueError('GNOME source SHA changed')
    root = c.WORK/'desktop-build'/name
    src = root/'source'
    if not src.exists():
        src.mkdir(parents=True)
        with tarfile.open(archive) as t:
            t.extractall(src)
    src = next(p for p in src.iterdir() if p.is_dir())
    patches = []
    if name == 'gnome-settings-daemon-schemas':
        buildfile=src/'meson.build'
        before=buildfile.read_text()
        after="""# KIKI: upstream data/enumerations split; daemon services are a separate scope.
project('gnome-settings-daemon','c',version:'50.1')
gnome=import('gnome')
pkg=import('pkgconfig')
i18n=import('i18n')
gsd_version=meson.project_version()
gsd_api_name='gnome-settings-daemon-3.0'
gsd_datadir=get_option('prefix') / get_option('datadir')
gsd_schemadir=gsd_datadir / 'glib-2.0/schemas'
gsd_pkgincludedir=get_option('prefix') / get_option('includedir') / gsd_api_name
enable_wwan=true
subdir('data')
subdir('po')
"""
        patch=c.TARGET/'inputs/patches/gnome-settings-daemon-data-split.patch'
        if before!=after:
            patch.write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/meson.build',tofile='b/meson.build')));buildfile.write_text(after)
        patches.append(dict(path=str(patch),sha256=sha256_file(patch),scope='upstream schemas/enumerations only; no daemon services'))
    if name == 'gnome-desktop':
        p=src/'meson.build';before=p.read_text()
        after=before.replace("iso_codes_prefix = iso_codes_dep.get_variable(pkgconfig: 'prefix')", "iso_codes_prefix = get_option('prefix')")
        patch=c.TARGET/'inputs/patches/gnome-desktop-target-iso-codes-prefix.patch'
        if before!=after:
            patch.write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/meson.build',tofile='b/meson.build')));p.write_text(after)
        patches.append(dict(path=str(patch),sha256=sha256_file(patch)))
    if name == 'libgweather':
        p=src/'meson.build';before=p.read_text()
        after=before.replace("get_option('introspection') and g_ir_scanner.found() and not meson.is_cross_build()", "get_option('introspection') and g_ir_scanner.found()")
        patch=c.TARGET/'inputs/patches/libgweather-target-gi-launcher.patch'
        if before!=after:
            patch.write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/meson.build',tofile='b/meson.build')));p.write_text(after)
        patches.append(dict(path=str(patch),sha256=sha256_file(patch),reason='Target GI scanner/loader configured explicitly; preserve requested introspection during cross build'))
        before=p.read_text()
        after=before.replace("locations_bin = dependency('gweather-locations').get_variable(\n  pkgconfig: 'locations_db',\n  default_value: get_option('prefix') / get_option('libdir') / 'gweather-locations/Locations.bin',\n)", "locations_bin = get_option('prefix') / get_option('libdir') / 'gweather-locations/Locations.bin'")
        patch=c.TARGET/'inputs/patches/libgweather-target-locations-path.patch'
        if before!=after:
            patch.write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/meson.build',tofile='b/meson.build')));p.write_text(after)
        patches.append(dict(path=str(patch),sha256=sha256_file(patch)))
    if name == 'appstream':
        # Library-only mode needs its ITS/config data, not translated metadata
        # for an uninstalled CLI or a second native AppStream build.
        buildfile = src/'data/meson.build'
        before = buildfile.read_text()
        start = before.find('# Do not rely on an exe wrapper')
        end = before.find('# install appstream.conf default template')
        patch = c.TARGET/'inputs/patches/appstream-library-only-metadata.patch'
        if start >= 0 and end > start and 'if get_option(\'tools\')\n# Do not rely' not in before:
            after = before[:start]+"if get_option('tools')\n"+before[start:end]+'endif\n\n'+before[end:]
            patch.write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/data/meson.build',tofile='b/data/meson.build')))
            buildfile.write_text(after)
        patches.append(dict(path=str(patch),sha256=sha256_file(patch)))
    if name == 'gnome-shell':
        p=src/'meson.build';before=p.read_text()
        after=before.replace("mutter_typelibdir = mutter_dep.get_variable('typelibdir')", "mutter_typelibdir = prefix / 'lib/mutter-18'")
        patch=c.TARGET/'inputs/patches/gnome-shell-target-mutter-typelibdir.patch'
        if before!=after:
            patch.write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/meson.build',tofile='b/meson.build')));p.write_text(after)
        patches.append(dict(path=str(patch),sha256=sha256_file(patch)))
        relative = 'src/shell-app-usage.c'
        p = src/relative
        before = p.read_text()
        after = before.replace('#include <X11/Xlib.h>\n', '').replace('#include <X11/Xatom.h>\n', '')
        patch = c.TARGET/'inputs/patches/gnome-shell-remove-unused-x11-includes.patch'
        patch.parent.mkdir(parents=True, exist_ok=True)
        if before != after:
            patch.write_text(''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile='a/'+relative, tofile='b/'+relative)))
            p.write_text(after)
        patches.append(dict(path=str(patch), sha256=sha256_file(patch)))
        relative = 'meson.build'
        p = src/relative
        before = p.read_text()
        after = before.replace("systemduserunitdir = systemd_dep.get_variable('systemduserunitdir',\n    pkgconfig_define: ['prefix', prefix])", "systemduserunitdir = prefix / 'lib/systemd/user'")
        patch = c.TARGET/'inputs/patches/gnome-shell-target-systemd-unitdir.patch'
        if before != after:
            patch.write_text(''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile='a/'+relative, tofile='b/'+relative)))
            p.write_text(after)
        patches.append(dict(path=str(patch), sha256=sha256_file(patch)))
        p = src/'js/dbusServices/meson.build'
        before = p.read_text()
        after = before.replace("serviceconf.set('gjs', gjs.full_path())", "serviceconf.set('gjs', '/usr/bin/gjs')")
        patch = c.TARGET/'inputs/patches/gnome-shell-target-gjs-activation.patch'
        if before != after:
            patch.write_text(''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile='a/js/dbusServices/meson.build', tofile='b/js/dbusServices/meson.build')))
            p.write_text(after)
        patches.append(dict(path=str(patch), sha256=sha256_file(patch)))
    if name == 'gdm':
        # GDM has no switch for its translated manual, which otherwise pulls
        # extra host Python/XML tools into the minimal login build.
        buildfile = src/'meson.build'
        before = buildfile.read_text()
        after = before.replace("subdir('docs')", "# KIKI minimal login candidate: omit translated manuals")
        patch = c.TARGET/'inputs/patches/gdm-omit-manual.patch'
        patch.parent.mkdir(parents=True,exist_ok=True)
        if after != before:
            patch.write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/meson.build',tofile='b/meson.build')))
            buildfile.write_text(after)
        patches.append(dict(path=str(patch),sha256=sha256_file(patch)))
        before = buildfile.read_text()
        after = before.replace("dconf_prefix = dconf_dep.get_variable(pkgconfig: 'prefix')", "dconf_prefix = gdm_prefix")
        patch = c.TARGET/'inputs/patches/gdm-target-dconf-prefix.patch'
        if after != before:
            patch.write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/meson.build',tofile='b/meson.build')))
            buildfile.write_text(after)
        patches.append(dict(path=str(patch),sha256=sha256_file(patch)))
    if name == 'libdisplay-info':
        hwdata = next((c.WORK/'desktop-build/hwdata/source').glob('*/pnp.ids'))
        buildfile = src/'meson.build'
        before = buildfile.read_text()
        after = before.replace("files('/usr/share/hwdata/pnp.ids')", "files('"+str(hwdata)+"')")
        patch = c.TARGET/'inputs/patches/libdisplay-info-locked-hwdata.patch'
        patch.parent.mkdir(parents=True,exist_ok=True)
        if after != before:
            patch.write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/meson.build',tofile='b/meson.build')))
            buildfile.write_text(after)
        patches.append(dict(path=str(patch),sha256=sha256_file(patch),pnp_ids_sha256=sha256_file(hwdata)))
    if name == 'gjs':
        # The archive's redirect assumes an unpinned GLib checkout. Reuse the
        # GVDB source contained in our SHA-locked GLib release instead.
        gvdb = c.WORK/'desktop-build/glib/source/glib-2.88.3/subprojects/gvdb'
        if not (src/'subprojects/gvdb').exists():
            shutil.copytree(gvdb, src/'subprojects/gvdb', symlinks=True)
        shutil.copy2(gvdb.parent/'gvdb.wrap', src/'subprojects/gvdb.wrap')
    if name == 'glycin':
        changes = []
        for relative in ['meson.build', 'build-aux/crates-version.py']:
            p = src/relative
            before = p.read_text()
            if relative == 'meson.build':
                after = before.replace("rust_target = 'release'", "rust_target = 'x86_64-unknown-linux-gnu/release'")
                after = after.replace("cargo_env.set('CARGO_HOME', cargo_home)", "cargo_env.set('CARGO_HOME', cargo_home)\ncargo_env.set('CARGO_BUILD_TARGET', 'x86_64-unknown-linux-gnu')") if "cargo_env.set('CARGO_BUILD_TARGET'" not in before else after
            else:
                after = before.replace('import tomllib\n', 'try:\n    import tomllib\nexcept ImportError:\n    import tomli as tomllib\n') if 'import tomli as tomllib' not in before else before
            if before != after:
                changes += list(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile='a/'+relative, tofile='b/'+relative))
                p.write_text(after)
        patch = c.TARGET/'inputs/patches/glycin-cross-build.patch'
        patch.parent.mkdir(parents=True, exist_ok=True)
        if changes:
            patch.write_text(''.join(changes))
        patches = [dict(path=str(patch), sha256=sha256_file(patch))]
    out = root/'build'; out.mkdir(exist_ok=True)
    dest = root/'dest'; dest.mkdir(exist_ok=True)
    tools = out/'tools'; tools.mkdir(exist_ok=True)
    frozen = c.TARGET/'inputs/distro/scripts'; frozen.mkdir(parents=True, exist_ok=True)
    for name_ in ['ki2-target-run', 'ki2-target-python3', 'ki2-target-g-ir-scanner', 'ki2-target-g-ir-compiler', 'ki2-target-pkg-config']:
        shutil.copy2(c.REPO/'distro/scripts'/name_, frozen/name_)
    for name_ in ['g-ir-scanner', 'g-ir-compiler', 'pkg-config']:
        shutil.copy2(frozen/('ki2-target-'+name_), tools/name_)
        (tools/name_).chmod(0o755)
    if name == 'gweather-locations':
        python = tools/'python3'
        python.write_text('#!/bin/sh\nexec /bin/sh "'+str(frozen/'ki2-target-python3')+'" "$@"\n')
        python.chmod(0o755)
    for name_ in ['wayland-scanner', 'glib-compile-resources', 'glib-compile-schemas', 'glib-genmarshal', 'gi-compile-repository',
                  'gdbus-codegen', 'glib-mkenums', 'gdk-pixbuf-query-loaders', 'gdk-pixbuf-pixdata', 'gjs', 'gtk4-update-icon-cache']:
        program = c.SDK/'usr/bin'/name_
        real_program = program.with_name(name_+'.kiki-real')
        if program.exists() or real_program.exists():
            is_wrapper = program.exists() and program.read_bytes().startswith(b'#!/bin/sh\nexec /bin/sh ')
            if program.exists() and not is_wrapper:
                if real_program.exists():
                    backup = c.WORK/'sdk-tool-backups'/(name_+'-'+sha256_file(real_program))
                    backup.parent.mkdir(exist_ok=True)
                    if not backup.exists():
                        shutil.copy2(real_program, backup)
                    real_program.unlink()
                program.rename(real_program)
            launcher = 'ki2-target-run' if real_program.read_bytes()[:4] == b'\x7fELF' else 'ki2-target-python3'
            content = '#!/bin/sh\nexec /bin/sh "'+str(frozen/launcher)+'" "'+str(real_program)+'" "$@"\n'
            if not program.exists() or program.read_text() != content:
                temporary = program.with_name(name_+'.kiki-wrapper-tmp')
                temporary.write_text(content)
                temporary.chmod(0o755)
                temporary.replace(program)
            program.chmod(0o755)
            tool = tools/name_
            tool.write_text('#!/bin/sh\nexec "'+str(program)+'" "$@"\n')
            tool.chmod(0o755)
    real = c.SDK/'usr/bin/g-ir-compiler'
    if not (c.WORK/'g-ir-compiler.real').exists():
        shutil.copy2(real, c.WORK/'g-ir-compiler.real')
    shutil.copy2(c.WORK/'g-ir-compiler.real', out/'g-ir-compiler.real')
    # GI's pkgconfig files point to these SDK paths directly.
    shutil.copy2(frozen/'ki2-target-g-ir-compiler', real)
    real.chmod(0o755)
    (out/'real').mkdir(exist_ok=True)
    for relative in ['lib', 'share']:
        if not (out/relative).exists():
            (out/relative).symlink_to(c.SDK/'usr'/relative, target_is_directory=True)
    scanner = c.SDK/'usr/bin/g-ir-scanner'
    text = scanner.read_text(); scanner.write_text('#!/bin/sh\nexec /bin/sh "'+str(frozen/'ki2-target-python3')+'" "'+str(out/'real/g-ir-scanner')+'" "$@"\n')
    if not (c.WORK/'g-ir-scanner.real').exists():
        (c.WORK/'g-ir-scanner.real').write_text(text)
    shutil.copy2(c.WORK/'g-ir-scanner.real', out/'real/g-ir-scanner')
    (out/'real/g-ir-scanner').chmod(0o755)
    scanner.chmod(0o755)
    (tools/'g-ir-scanner').write_text('#!/bin/sh\nexec "'+str(scanner)+'" "$@"\n')
    (tools/'g-ir-scanner').chmod(0o755)
    cross = out/'cross.ini'
    cross.write_text("[binaries]\nc = 'gcc'\nrust = '"+str(c.WORK/'rust-1.94.0/bin/rustc')+"'\ncpp = 'g++'\nar = 'ar'\nstrip = 'strip'\npkg-config = '"+str(tools/'pkg-config')+"'\nexe_wrapper = ['/bin/sh', '"+str(frozen/'ki2-target-run')+"']\n[host_machine]\nsystem = 'linux'\ncpu_family = 'x86_64'\ncpu = 'x86_64'\nendian = 'little'\n[properties]\nneeds_exe_wrapper = true\n")
    if name == 'gjs':
        cross.write_text(cross.read_text().replace("cpp = 'g++'", "cpp = '"+str(c.WORK/'host-tools/bin/clang++')+"'"))
    env = dict(KI2_REPO_ROOT=str(c.TARGET/'inputs'), KI2_BUILD_DIR=str(out), KI2_USE_TARGET_LOADER='1',
               GI_CROSS_LAUNCHER='/bin/sh '+str(frozen/'ki2-target-run'),
               PATH=str(tools)+':'+str(c.VENV/'bin')+':'+str(c.WORK/'host-tools/bin')+':'+str(c.WORK/'rust-1.94.0/bin')+':/usr/bin:/bin',
               CARGO_HOME=str(c.WORK/'cargo-home'), CARGO_TARGET_DIR=str(root/'cargo-target'),
               GETTEXTDATADIRS=str(c.SDK/'usr/share/gettext'),
               KI2_SYSROOT_LIBRARY_PATH=str(out)+':'+c.environment()['KI2_SYSROOT_LIBRARY_PATH'])
    if name == 'glib':
        env['KI2_SYSROOT_LIBRARY_PATH'] = ':'.join(str(out/'meson'/x) for x in ['glib','gobject','gio','gmodule','girepository']) + ':' + env['KI2_SYSROOT_LIBRARY_PATH']
        env['LDFLAGS'] = ' '.join('-L'+str(out/'meson'/x) for x in ['glib','gobject','gio','gmodule','girepository'])+' '+c.environment()['LDFLAGS']
        scanner_cc = out/'scanner-cc'
        scanner_cc.write_text('#!/bin/sh\nexec /usr/bin/gcc '+ ' '.join('-L'+str(out/'meson'/x) for x in ['glib','gobject','gio','gmodule','girepository'])+' "$@"\n')
        scanner_cc.chmod(0o755)
        env['CC'] = str(scanner_cc)
        shutil.copy2(scanner_cc, tools/'gcc')
    if name in ['glycin','librsvg']:
        linker = out/'target-linker-v2'
        # Cargo uses the same GNU triple for build tools and target artifacts.
        # Only output under the explicit target directory may use KIKI libc.
        linker.write_text('#!/bin/sh\nprevious=\noutput=\nfor argument do\n'
                          '  if [ "$previous" = -o ]; then output=$argument; break; fi\n'
                          '  previous=$argument\ndone\n'
                          'case "$output" in\n'
                          '  */x86_64-unknown-linux-gnu/*) exec gcc '+c.environment()['LDFLAGS']+' "$@" ;;\n'
                          '  *) exec gcc "$@" ;;\nesac\n')
        linker.chmod(0o755)
        env['CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER'] = str(linker)
        env['CARGO_BUILD_JOBS'] = '2'
        env['CARGO_NET_OFFLINE'] = 'true'
        cargo_home = out/'meson/cargo-home' if name == 'glycin' else root/'cargo-home'
        cargo_home.mkdir(parents=True, exist_ok=True)
        config = src/'.cargo/config.toml' if name == 'glycin' else c.WORK/'librsvg-vendor-config.toml'
        shutil.copy2(config, cargo_home/'config.toml')
        if name == 'librsvg':
            env['CARGO_HOME'] = str(cargo_home)
            env['PKG_CONFIG_ALLOW_CROSS'] = '1'
    log = c.TARGET/'validation'/(name+'-build.log')
    if not (out/'meson/build.ninja').exists():
        c.run(['meson', 'setup', str(out/'meson'), str(src), '--cross-file', str(cross), '--prefix=/usr', '--libdir=lib',
               '--sysconfdir=/etc', '--buildtype=release', '--wrap-mode=nodownload'] + preset['options'], out, log, env)
    elif refresh_dependencies:
        c.run(['meson','setup','--reconfigure','--clearcache',str(out/'meson'),str(src)]+preset['options'],out,log,env)
    if configure_only:
        print(name, 'configured'); return
    c.run(['ninja', '-C', str(out/'meson'), '-j2'], out, log, env)
    c.run(['meson', 'install', '-C', str(out/'meson'), '--no-rebuild'], out, log, dict(env, DESTDIR=str(dest)))
    launcher_changes=[]
    if name=='gnome-shell':
        for program in ['gnome-extensions-app','gnome-shell-extension-tool','gnome-shell-test-tool']:
            p=dest/'usr/bin'/program;before=p.read_text()
            after=before.replace(str(out/'tools/gjs'),'/usr/bin/gjs').replace('#!'+str(c.VENV/'bin/python3'),'#!/usr/bin/python3')
            if before!=after:p.write_text(after);p.chmod(0o755);launcher_changes.append(dict(path='/usr/bin/'+program,sha256=sha256_file(p)))
    version = source.get('version', archive.name[len(source_name)+1:].removesuffix('.tar.xz').removesuffix('.tar.gz').removesuffix('.tar.bz2'))
    raw = dict(name=name, version=version, release='2' if name in ['glycin','gdm'] else '1', summary='Native GNOME 50 desktop dependency', license=preset.get('license', 'LGPL-2.1-or-later'),
               tier='desktop', architectures=['x86_64'], source=dict(type='url', url=source['url'], sha256=source['sha256']),
               dependencies=dict(build=['linux-headers','gobject-introspection'], runtime=preset['dependencies']),
               build=dict(system='meson', configure_options=preset['options']))
    if release_override:
        prior=tomli.loads((c.TARGET/'recipes'/(name+'.toml')).read_text())['recipe'][0]
        raw['release']=release_override
        raw['dependencies']['runtime']=sorted(set(raw['dependencies']['runtime'])|set(prior['dependencies']['runtime']))
    with contextlib.redirect_stdout(io.StringIO()):
        c.package(raw, dest, dict(source_lock=source, options=preset['options'], patches=patches, target_launcher_corrections=launcher_changes, cross_file_sha256=sha256_file(cross)))
    print('Built', name, version, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name', choices=list(PRESETS))
    parser.add_argument('--configure-only', action='store_true')
    parser.add_argument('--refresh-dependencies', action='store_true')
    parser.add_argument('--release')
    args = parser.parse_args()
    build(args.name, args.configure_only,args.refresh_dependencies,args.release)
