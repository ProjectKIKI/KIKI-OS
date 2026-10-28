import importlib.util
from pathlib import Path
import sys
import os

spec=importlib.util.spec_from_file_location('context',Path(__file__).with_name('context.py'))
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)

def meson(name,options,deps,license='LGPL-2.1-or-later',release='1'):
    root=a.work/name;src=next((root/'source').iterdir());build=root/'build';dest=root/'dest'
    if not (build/'build.ninja').exists():
        a.run(['meson','setup',build,src,'--cross-file',a.cross,'--prefix=/usr','--libdir=lib','--libexecdir=libexec',
               '--buildtype=release','--wrap-mode=nodownload',*options])
    else:a.run(['meson','configure',build,*options])
    a.run(['ninja','-C',build,'-j4'])
    a.run(['meson','install','-C',build,'--no-rebuild'],dict(DESTDIR=str(dest)))
    if name=='fuse3':(dest/'usr/bin/fusermount3').chmod(0o4755)
    if name=='gnome-backgrounds':
        # The preserved GNOME runtime decodes SVG/PNG/JPEG. Avoid advertising
        # JPEG XL backgrounds until a matching decoder is included and tested.
        for path in (dest/'usr/share/gnome-background-properties').glob('*.xml'):
            if '.jxl' in path.read_text():path.unlink()
        for path in (dest/'usr/share/backgrounds').rglob('*.jxl'):path.unlink()
    version=(build/'meson-info/intro-projectinfo.json')
    import json
    version=json.loads(version.read_text())['version']
    return a.package(name,version,dest,deps,a.records[name],license=license,release=release)

def gnu(name,version,options,deps,subdir='',license='LGPL-2.1-or-later',release='1'):
    root=a.work/name;src=next((root/'source').iterdir())/subdir;dest=root/'dest'
    previous=Path.cwd()
    try:
        os.chdir(src)
        if name=='udisks2' and not (src/'gtk-doc.make').exists():
            a.run(['gtkdocize','--copy'])
            a.run(['autoreconf','-fi'])
        if not (src/'configure').exists():a.run(['autoreconf','-fi'])
        if name=='krb5' and not (a.sdk/'usr/lib/libcom_err.so').exists():
            (a.sdk/'usr/lib/libcom_err.so').symlink_to('../../lib64/libcom_err.so.2')
        if name=='krb5':
            import subprocess,json
            probe=root/'target-features.c';binary=root/'target-features'
            probe.write_text('#include <stdio.h>\nstatic void __attribute__((constructor)) start(void){puts("C");}\nstatic void __attribute__((destructor)) finish(void){puts("D");}\nint main(void){printf("%2$d%1$d\\n",2,1);return 0;}\n')
            a.run(['gcc',*a.env['CFLAGS'].split(),probe,'-o',binary,*a.env['LDFLAGS'].split()])
            result=subprocess.check_output([str(a.wrapper),str(binary)],text=True)
            assert result=='C\n12\nD\n',result
            (root/'target-features.json').write_text(json.dumps(dict(constructor=True,destructor=True,printf_positional=True,stdout=result))+'\n')
        # Autoconf cannot execute target probes during a cross build. The KIKI
        # glibc implements GNU malloc/realloc zero-size semantics.
        a.run([src/'configure','--prefix=/usr','--libdir=/usr/lib','--sysconfdir=/etc',
               '--build=x86_64-pc-linux-gnu','--host=x86_64-kiki-linux-gnu','--disable-static',*options],
              dict(CC='gcc --sysroot='+str(a.sdk),CXX=str(a.tools/'clang++')+' --sysroot='+str(a.sdk),
                   ac_cv_func_malloc_0_nonnull='yes',ac_cv_func_realloc_0_nonnull='yes',
                   **({'krb5_cv_attr_constructor_destructor':'yes,yes','ac_cv_printf_positional':'yes'} if name=='krb5' else {})))
        if name in ['libndp','readline']:a.run(['make','clean'])
        a.run(['make','-j4']+(['SHLIB_LIBS=-lncursesw'] if name=='readline' else []))
        a.run(['make','DESTDIR='+str(dest),'install'])
        for path in (dest/'usr/lib').glob('*.la'):path.unlink()
        return a.package(name,version,dest,deps,a.records[name],license=license,release=release)
    finally:os.chdir(previous)

if __name__=='__main__':
    for name in sys.argv[1:]:
        if name=='sqlite':
            import subprocess,tarfile,json,hashlib
            lock=json.loads((a.repo/'dist/ki2/stage3-6.1.187-gnome50-candidate-20261017/gnome50-source-lock.json').read_text())
            source=next(r for r in lock['sources'] if r.get('name')=='sqlite')
            archive=Path(source['file']);assert hashlib.sha256(archive.read_bytes()).hexdigest()==source['sha256']
            dest=a.work/name/'dest';root=a.work/name/'source'
            if not root.exists():
                root.mkdir(parents=True)
                with tarfile.open(archive) as t:t.extractall(root)
            src=next(root.iterdir())
            import os
            os.chdir(src)
            a.run([src/'configure','--prefix=/usr','--libdir=/usr/lib','--enable-fts5','--disable-static','--disable-readline'],dict(CC='gcc --sysroot='+str(a.sdk),CFLAGS=a.env['CFLAGS']+' -DSQLITE_ENABLE_COLUMN_METADATA -DSQLITE_ENABLE_UNLOCK_NOTIFY',LDFLAGS=a.env['LDFLAGS'])) if not (src/'Makefile').exists() else None
            a.run(['make','-C',src,'-j4'])
            a.run(['make','-C',src,'DESTDIR='+str(dest),'install'])
            a.run([a.tools/'patchelf','--set-soname','libsqlite3.so.0',dest/'usr/lib/libsqlite3.so.3.50.4'])
            a.package(name,'3.50.4',dest,['glibc','zlib'],source,license='Public-Domain',release='5')
            os.chdir(a.repo)
        elif name=='xdg-user-dirs':
            src=next((a.work/name/'source').iterdir());path=src/'data/meson.build'
            path.write_text(path.read_text().replace("systemd_dep.get_variable(pkgconfig: 'systemduserunitdir')","get_option('prefix') / get_option('libdir') / 'systemd' / 'user'"))
            meson(name,['-Ddocs=false'],['glibc'],license='GPL-2.0-or-later',release='2')
        elif name=='fuse3':meson(name,['-Duseroot=false','-Dexamples=false','-Dtests=false','-Denable-io-uring=false','-Dinitscriptdir=','-Dudevrulesdir=/usr/lib/udev/rules.d'],['glibc','util-linux'],license='GPL-2.0-or-later AND LGPL-2.1-or-later',release='2')
        elif name=='pipewire':meson(name,['-Dauto_features=disabled','-Dexamples=disabled','-Dtests=disabled','-Dpipewire-jack=disabled','-Dsession-managers=[]','-Dsystemd=enabled','-Dsystemd-user-service=enabled','-Dsystemd-system-service=disabled'],['glibc','libsystemd'],license='MIT')
        elif name=='gstreamer':meson(name,['-Dauto_features=disabled','-Dbase=enabled','-Dgood=disabled','-Dugly=disabled','-Dbad=disabled','-Dlibav=disabled','-Ddevtools=disabled','-Dges=disabled','-Drtsp_server=disabled','-Dpython=disabled','-Dgst-examples=disabled','-Dgstreamer:introspection=disabled','-Dgstreamer:tests=disabled','-Dgst-plugins-base:introspection=disabled','-Dgst-plugins-base:tests=disabled','-Dgst-plugins-base:typefind=enabled','-Dgst-plugins-base:playback=enabled','-Dorc-source=system'],['glib','glibc','zlib','libatomic'],license='LGPL-2.1-or-later')
        elif name=='xdg-desktop-portal':meson(name,['-Dtests=disabled','-Ddocumentation=disabled','-Dman-pages=disabled','-Dflatpak-interfaces=disabled','-Dgeoclue=disabled','-Dsystemd-user-unit-dir=/usr/lib/systemd/user'],['glib','json-glib','fuse3','gdk-pixbuf','gstreamer','pipewire','libsystemd','libgudev','bubblewrap'],license='LGPL-2.1-or-later')
        elif name=='xdg-desktop-portal-gnome':meson(name,['-Dsystemduserunitdir=/usr/lib/systemd/user','-Dlibgxdp:tests=false'],['gtk','libadwaita','glib','gnome-desktop','gsettings-desktop-schemas','xdg-desktop-portal'],license='LGPL-2.1-or-later')
        elif name=='libportal':meson(name,['-Dbackend-gtk3=disabled','-Dbackend-gtk4=enabled','-Dbackend-qt5=disabled','-Dbackend-qt6=disabled','-Dintrospection=false','-Dvapi=false','-Ddocs=false','-Dtests=false'],['gtk','glib'])
        elif name=='tinysparql':meson(name,['-Ddocs=false','-Dman=false','-Dtests=false','-Dintrospection=disabled','-Dvapi=disabled','-Dstemmer=disabled','-Davahi=disabled','-Dsystemd_user_services_dir=/usr/lib/systemd/user'],['glib','icu','sqlite','json-glib','libxml2','libsoup'],release='3')
        elif name=='localsearch':
            src=next((a.work/name/'source').iterdir());path=src/'src/common/tracker-seccomp.c';text=path.read_text()
            for macro in ['FS_IOC_GETFSUUID','ARCH_SHSTK_DISABLE']:
                lines=text.splitlines(keepends=True)
                for i,line in enumerate(lines):
                    if 'CUSTOM_RULE' in line and macro in line and (i==0 or '#ifdef '+macro not in lines[i-1]):
                        lines[i]='#ifdef '+macro+'\n'+line+'#endif\n'
                text=''.join(lines)
            path.write_text(text)
            import re
            path=src/'src/indexer/tracker-indexing-tree-methods.c'
            path.write_text(re.sub(r'#ifdef __linux__\n(?=\s*if \(!id\))', '#if defined(__linux__) && defined(FS_IOC_GETFSUUID)\n',path.read_text()))
            meson(name,['-Dtiff=disabled','-Draw=disabled','-Diptc=disabled','-Dexif=disabled','-Dwebp=disabled','-Dlibav=disabled','-Dfunctional_tests=false','-Dsandbox_tests=false','-Dman=false','-Dwriteback=false','-Dbash_completion=true','-Dbash_completion_dir=/usr/share/bash-completion/completions','-Dsystemd_user_services_dir=/usr/lib/systemd/user'],['glib','tinysparql','libseccomp','upower','icu','libxml2','zlib','libjpeg-turbo','libpng','libtiff'],license='GPL-2.0-or-later')
        elif name=='nautilus':meson(name,['-Dselinux=disabled','-Dcloudproviders=disabled','-Dextensions=false','-Dintrospection=false','-Dtests=none'],['gtk','glib','libadwaita','libportal','tinysparql','gnome-autoar','gnome-desktop','glycin','glycin-gtk4','icu','gsettings-desktop-schemas','localsearch'],license='GPL-3.0-or-later',release='3')
        elif name=='accountsservice-pc':
            import json,shutil
            candidate=a.repo/'dist/ki2/desktop-installer-20261027'
            record=next(r for r in json.loads((candidate/'repo/index.x86_64.json').read_text())['packages'] if r['name']=='accountsservice')
            package=candidate/'packages/x86_64'/record['file'];assert a.ki2build.file_sha256(package)==record['sha256']
            dest=a.work/'accountsservice-pc/dest'
            if not dest.exists():a.ki2build.extract_package_rootfs(package,dest)
            pc=dest/'usr/lib/pkgconfig/accountsservice.pc'
            import re
            pc.write_text(re.sub(r'^Version:.*$', 'Version: '+record['version'],pc.read_text(),flags=re.M))
            a.package('accountsservice',record['version'],dest,record['dependencies']['runtime'],dict(parent_sha256=record['sha256'],pkgconfig_version_correction=True),license='GPL-3.0-or-later',release='4')
        elif name=='gnome-control-center':
            import shutil
            src=next((a.work/name/'source').iterdir())
            if not (src/'subprojects/tecla').exists():shutil.copytree(next((a.work/'tecla/source').iterdir()),src/'subprojects/tecla')
            meson(name,['-Ddocumentation=false','-Dtests=false','-Dsnap=false','-Dmalcontent=false'],['gtk','glib','libadwaita','gnome-desktop','gnome-settings-daemon','gsettings-desktop-schemas','gnome-online-accounts','cups-base','NetworkManager','libnma','ModemManager','libwacom','pwquality','colord-gtk','colord','libgtop','udisks2','smbclient','krb5','pulseaudio','upower','polkit','accountsservice','ibus','libgudev','gcr','libxml2','json-glib','libsecret','gsound','gnome-bluetooth','wayland','libepoxy','libxcrypt'],license='GPL-2.0-or-later',release='2')
        elif name=='krb5':gnu(name,'1.22.2',['--disable-rpath','--without-system-verto','--with-system-et','--with-system-ss'],['glibc','e2fsprogs','openssl','libcom-err'],subdir='src',license='MIT',release='2')
        elif name=='readline':gnu(name,'8.3',['--with-curses'],['glibc','ncurses'],license='GPL-3.0-or-later',release='3')
        elif name=='cups-base':gnu(name,'2.4.12',['--disable-gssapi','--disable-avahi','--with-tls=openssl','--with-rundir=/run/cups','--with-system-groups=root wheel'],['glibc','openssl','zlib','libsystemd'],license='Apache-2.0')
        elif name=='libgtop':gnu(name,'2.41.3',['--disable-introspection'],['glib','libsystemd'],license='GPL-2.0-or-later',release='2')
        elif name=='colord-gtk':meson(name,['-Dgtk2=false','-Dgtk3=false','-Dgtk4=true','-Ddocs=false','-Dman=false','-Dvapi=false'],['gtk','glib','colord','lcms2'])
        elif name=='udisks2':gnu(name,'2.11.1',['--disable-daemon','--disable-gtk-doc','--disable-introspection'],['glib','polkit','libsystemd'],license='LGPL-2.0-or-later')
        elif name=='libndp':gnu(name,'1.9',[],['glibc'])
        elif name=='cracklib':gnu(name,'2.10.3',['--without-python'],['glibc','zlib'],subdir='src')
        elif name=='pwquality':gnu(name,'1.4.5',['--disable-python-bindings','--with-securedir=/usr/lib/security'],['glibc','cracklib','linux-pam'])
        elif name=='libwacom':meson(name,['-Dtests=disabled'],['glib','libevdev','libgudev'])
        elif name=='librest':meson(name,['-Dgtk_doc=false','-Dtests=false','-Dexamples=false','-Dintrospection=false','-Dvapi=false'],['glib','libsoup','libxml2'])
        elif name=='gnome-online-accounts':meson(name,['-Dkerberos=false','-Ddocumentation=false','-Dman=false','-Dintrospection=false','-Dvapi=false'],['gtk','glib','gcr','libsecret','libsoup','librest','json-glib'],license='LGPL-2.1-or-later')
        elif name=='NetworkManager':meson(name,['-Dman=false','-Dclat=false','-Dselinux=false','-Dlibaudit=no','-Dnmtui=false','-Dnm_cloud_setup=false','-Dmodem_manager=false','-Dppp=false','-Dovs=false','-Debpf=false','-Dnbft=false','-Dintrospection=false','-Dvapi=false','-Ddocs=false','-Dtests=no','-Dcrypto=gnutls','-Dreadline=libreadline','-Dsystemdsystemunitdir=/usr/lib/systemd/system','-Dudev_dir=/usr/lib/udev','-Ddbus_conf_dir=/usr/share/dbus-1/system.d','-Druntime_dir=/run'],['glib','libsystemd','polkit','libndp','gnutls','libpsl','curl','readline'],license='GPL-2.0-or-later')
        elif name=='gtk+-3':meson(name,['-Dx11_backend=false','-Dwayland_backend=true','-Dbroadway_backend=false','-Dintrospection=false','-Ddemos=false','-Dexamples=false','-Dtests=false','-Dinstalled_tests=false','-Dgtk_doc=false','-Dman=false','-Dprint_backends=file'],['glib','pango','cairo','gdk-pixbuf','at-spi2-core','libepoxy','wayland','libxkbcommon','fontconfig'],license='LGPL-2.1-or-later')
        elif name=='libnma':meson(name,['-Dlibnma_gtk4=true','-Dgcr=false','-Dmobile_broadband_provider_info=false','-Dintrospection=false','-Dvapi=false','-Dgtk_doc=false'],['gtk','gtk+-3','glib','NetworkManager','gnutls'],license='GPL-2.0-or-later')
        elif name=='gnome-console':meson(name,[],['gtk','glib','libadwaita','vte','libgtop','nautilus'],license='GPL-3.0-or-later')
        elif name=='gnome-backgrounds':meson(name,[],[],license='LicenseRef-GNOME-backgrounds',release='2')
        elif name=='ModemManager':meson(name,['-Dbash_completion=false','-Dmbim=false','-Dqmi=false','-Dqrtr=false','-Dtests=false','-Dexamples=false','-Dintrospection=false','-Dvapi=false','-Dgtk_doc=false','-Dsystemdsystemunitdir=/usr/lib/systemd/system','-Dudevdir=/usr/lib/udev'],['glib','libgudev','libsystemd','polkit'],license='GPL-2.0-or-later AND LGPL-2.1-or-later')
        else:raise RuntimeError('Unknown build target '+name)
