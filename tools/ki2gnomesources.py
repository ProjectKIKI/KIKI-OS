#!/usr/bin/env python3
"""Extend the candidate source lock from preserved GNOME metadata and upstream releases."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import re
import urllib.request

import ki2sessioncandidate as c


def main():
    path = c.TARGET/'gnome50-source-lock.json'
    lock = json.loads(path.read_text())
    jobs = []
    for name in ['evolution-data-server', 'gnome-settings-daemon', 'libsecret', 'glib-networking', 'ibus', 'libgweather', 'gnome-bluetooth',
                 'geocode-glib','gweather-locations','gsound','libnotify','libcanberra','gnome-autoar']:
        text = (c.TARGET/'inputs/meta'/(name+'.bst')).read_text()
        url = re.search(r'  url: (\S+)', text)[1]
        url = url.replace('gnome_downloads:', 'https://download.gnome.org/sources/').replace('github_files:', 'https://github.com/')
        url = url.replace('0pointer:', 'https://0pointer.de/')
        sha = re.search(r'  ref: ([0-9a-f]{64})', text)[1]
        version = url.rsplit('/',1)[-1][len(name)+1:].split('.tar.')[0]
        jobs.append(dict(name=name, version=version, url=url, sha256=sha, verification='GNOME 50.4 official metadata SHA-256'))
    for name, version, url in [
        ('libarchive','3.8.1','https://github.com/libarchive/libarchive/releases/download/v3.8.1/libarchive-3.8.1.tar.xz'),
        ('patchelf-host','0.18.0','https://github.com/NixOS/patchelf/releases/download/0.18.0/patchelf-0.18.0.tar.bz2'),
        ('libsass-host','3.6.6','https://github.com/sass/libsass/archive/refs/tags/3.6.6.tar.gz'),
        ('sassc-host','3.6.2','https://github.com/sass/sassc/archive/refs/tags/3.6.2.tar.gz'),
        ('hicolor-icon-theme','0.18','https://icon-theme.freedesktop.org/releases/hicolor-icon-theme-0.18.tar.xz'),
        ('libfyaml','0.9.6','https://github.com/pantoniou/libfyaml/releases/download/v0.9.6/libfyaml-0.9.6.tar.gz'),
        ('geoclue','2.8.0','https://gitlab.freedesktop.org/geoclue/geoclue/-/archive/2.8.0/geoclue-2.8.0.tar.gz'),
        ('pulseaudio','17.0','https://www.freedesktop.org/software/pulseaudio/releases/pulseaudio-17.0.tar.xz'),
        ('alsa-lib','1.2.14','https://www.alsa-project.org/files/pub/lib/alsa-lib-1.2.14.tar.bz2'),
        ('libsndfile','1.2.2','https://github.com/libsndfile/libsndfile/releases/download/1.2.2/libsndfile-1.2.2.tar.xz'),
        ('libogg','1.3.5','https://downloads.xiph.org/releases/ogg/libogg-1.3.5.tar.xz'),
        ('libvorbis','1.3.7','https://downloads.xiph.org/releases/vorbis/libvorbis-1.3.7.tar.xz'),
        ('libtool','2.4.7','https://ftp.gnu.org/gnu/libtool/libtool-2.4.7.tar.xz'),
        ('libyaml','0.2.5','https://github.com/yaml/libyaml/releases/download/0.2.5/yaml-0.2.5.tar.gz'),
        ('libxmlb','0.3.24','https://github.com/hughsie/libxmlb/releases/download/0.3.24/libxmlb-0.3.24.tar.xz'),
        ('appstream','1.1.6','https://www.freedesktop.org/software/appstream/releases/AppStream-1.1.6.tar.xz'),
        ('icu','76.1','https://github.com/unicode-org/icu/releases/download/release-76-1/icu4c-76_1-src.tgz'),
        ('libgusb','0.4.9','https://github.com/hughsie/libgusb/archive/refs/tags/0.4.9.tar.gz'),
        ('hwdata','0.410','https://github.com/vcrhonek/hwdata/archive/8bb6c48dc2e683777e625d1c9ef02c1b25b741cd.tar.gz'),
        ('sqlite','3.50.4','https://www.sqlite.org/2025/sqlite-autoconf-3500400.tar.gz'),
        ('colord','1.4.8','https://github.com/hughsie/colord/archive/e3ee294acdc53d7f191e1090631d75f471e59d82.tar.gz'),
        ('libdisplay-info','0.4.0','https://gitlab.freedesktop.org/emersion/libdisplay-info/-/archive/c67a3e9bedb05ab61c7443704a1a107e76254595/libdisplay-info-c67a3e9bedb05ab61c7443704a1a107e76254595.tar.gz'),
        ('libei','1.5.0','https://gitlab.freedesktop.org/libinput/libei/-/archive/1.5.0/libei-1.5.0.tar.gz'),
        ('iso-codes','4.18.0','https://salsa.debian.org/iso-codes-team/iso-codes/-/archive/v4.18.0/iso-codes-v4.18.0.tar.gz'),
        ('libical','3.0.20','https://github.com/libical/libical/releases/download/v3.0.20/libical-3.0.20.tar.gz'),
        ('libpsl','0.21.5','https://github.com/rockdaboot/libpsl/releases/download/0.21.5/libpsl-0.21.5.tar.gz'),
        ('nghttp2','1.64.0','https://github.com/nghttp2/nghttp2/releases/download/v1.64.0/nghttp2-1.64.0.tar.xz'),
    ]:
        s=dict(name=name,version=version,url=url,verification='Official upstream HTTPS; locally pinned SHA-256 (no signature claim)')
        if name=='libfyaml':
            release=json.load(urllib.request.urlopen('https://api.github.com/repos/pantoniou/libfyaml/releases/tags/v0.9.6',timeout=30))
            asset=next(a for a in release['assets'] if a['name']=='libfyaml-0.9.6.tar.gz')
            if asset['browser_download_url']!=url:raise ValueError('Unexpected official release URL')
            c.save(c.TARGET/'validation/libfyaml-release.json',asset)
            s.update(sha256=asset['digest'].removeprefix('sha256:'),verification='Official GitHub release asset SHA-256 digest')
        jobs.append(s)
    def download(s):
        if s.get('sha256') and not re.fullmatch('[0-9a-f]{64}',s['sha256']):raise ValueError('Invalid expected SHA-256 format')
        prior=next((x for x in lock['sources'] if x.get('name')==s['name']),None)
        if prior and prior.get('version')==s.get('version'):
            if s.get('sha256') and s['sha256']!=prior['sha256']:raise ValueError('Official source digest changed: '+s['name'])
            if hashlib.sha256(Path(prior['file']).read_bytes()).hexdigest()!=prior['sha256']:
                raise ValueError('Changed source: '+s['name'])
            return prior
        extension='.tar.xz' if s['url'].endswith('.tar.xz') else '.tar.gz'
        f=c.WORK/'sources'/(s['name']+'-'+s['version']+extension)
        if not f.exists():
            request=urllib.request.Request(s['url'],headers={'User-Agent':'KIKI-candidate-source-verifier'})
            with urllib.request.urlopen(request,timeout=90) as r:
                data=r.read()
            digest=hashlib.sha256(data).hexdigest()
            if s.get('sha256') and s['sha256']!=digest:
                raise ValueError('Official SHA mismatch: '+s['name'])
            f.write_bytes(data)
        digest=hashlib.sha256(f.read_bytes()).hexdigest()
        if s.get('sha256') and s['sha256']!=digest:
            raise ValueError('Cached SHA mismatch: '+s['name'])
        return dict(s,file=str(f),sha256=digest,bytes=f.stat().st_size)
    failures=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures={pool.submit(download,s):s for s in jobs}
        for future in concurrent.futures.as_completed(futures):
            try:
                s=future.result()
                prior=next((x for x in lock['sources'] if x.get('name')==s['name']),None)
                if prior is None:lock['sources'].append(s)
                elif prior.get('version')!=s.get('version'):
                    lock.setdefault('superseded_sources',[]).append(prior)
                    lock['sources'].remove(prior);lock['sources'].append(s)
                print(s['name'],s['sha256'],flush=True)
            except Exception as e:
                failures.append(dict(name=futures[future]['name'],error=str(e)))
    c.save(path,lock)
    c.save(c.TARGET/'validation/extended-source-fetch.json',dict(failures=failures))
    if failures:
        raise RuntimeError(str(failures))


if __name__=='__main__':
    main()
