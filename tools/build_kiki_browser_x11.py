"""Build pinned X.Org client libraries in a private SDK copy. No base SDK writes."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import urllib.request


def unpack(archive, directory):
    assert not directory.exists();directory.mkdir()
    with tarfile.open(archive) as t:
        for m in t:
            path=PurePosixPath(m.name)
            assert not path.is_absolute() and '..' not in path.parts
            dest=directory/path
            if m.isdir():dest.mkdir(parents=True,exist_ok=True)
            elif m.isfile():
                dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(t.extractfile(m).read());dest.chmod(m.mode & 0o755);os.utime(dest,(m.mtime,m.mtime))
            elif m.issym():
                assert not PurePosixPath(m.linkname).is_absolute()
                assert (dest.parent/m.linkname).resolve().is_relative_to(directory.resolve())
                dest.parent.mkdir(parents=True,exist_ok=True);dest.symlink_to(m.linkname)
            elif m.islnk():
                link=directory/PurePosixPath(m.linkname)
                assert link.resolve().is_relative_to(directory.resolve()) and link.is_file()
                dest.parent.mkdir(parents=True,exist_ok=True);os.link(link,dest)
            else:raise ValueError('Unsupported source archive member: '+m.name)
    children=list(directory.iterdir());assert len(children)==1 and children[0].is_dir();return children[0]


def build(sdk, work, inputs, lockfile, stage, resume=False):
    sdk=sdk.resolve();work=work.resolve();stage=stage.resolve();inputs=inputs.resolve()
    assert sdk.is_dir() and (resume or (not work.exists() and not stage.exists()))
    assert not work.is_relative_to(sdk) and not stage.is_relative_to(sdk)
    work.mkdir(parents=True,exist_ok=resume);inputs.mkdir(parents=True,exist_ok=True)
    lock=json.loads(lockfile.read_text());assert lock['schema']=='kiki-browser-x11-sources-v1'
    for item in lock['sources']:
        archive=inputs/item['file']
        assert archive.name==item['file'] and item['url'].startswith('https://www.x.org/releases/individual/lib/')
        if not archive.exists():
            with urllib.request.urlopen(item['url'],timeout=90) as r:data=r.read()
            assert hashlib.sha256(data).hexdigest()==item['sha256'];archive.write_bytes(data)
        assert hashlib.sha256(archive.read_bytes()).hexdigest()==item['sha256']
    private=work/'sdk';receipt=work/'progress.json'
    identity=dict(base_sdk=str(sdk),stage=str(stage),lock_sha256=hashlib.sha256(lockfile.read_bytes()).hexdigest())
    if resume:
        progress=json.loads(receipt.read_text());assert all(progress[k]==v for k,v in identity.items()) and private.is_dir()
    else:
        subprocess.run(['cp','-a','--reflink=auto',str(sdk),str(private)],check=True);progress=dict(identity,completed=[]);receipt.write_text(json.dumps(progress,indent=2))
    # Libtool .la absolute paths refer to /usr/lib on the build host. Shared
    # objects and pkg-config provide the target dependencies without these files.
    for path in private.rglob('*.la'):path.unlink()
    env=dict(os.environ,CC='gcc --sysroot='+str(private),CC_FOR_BUILD='gcc',BUILD_CC='gcc',CFLAGS_FOR_BUILD='-O2',CFLAGS='-O2 -pipe -fstack-protector-strong',
        LDFLAGS='--sysroot='+str(private)+' '+' '.join('-L'+str(private/p)+' -Wl,-rpath-link,'+str(private/p) for p in ['usr/lib','usr/lib64','lib64']),
        PKG_CONFIG_SYSROOT_DIR=str(private),PKG_CONFIG_LIBDIR=':'.join(str(private/p) for p in ['usr/lib/pkgconfig','usr/lib64/pkgconfig','usr/share/pkgconfig']))
    stage.mkdir(parents=True,exist_ok=resume);(stage/'usr/lib').mkdir(parents=True,exist_ok=resume)
    for item in lock['sources']:
        if item['name'] in progress['completed']:continue
        source_dir=work/(item['name']+'-source')
        source=next(source_dir.iterdir()) if resume and source_dir.exists() else unpack(inputs/item['file'],source_dir)
        out=work/(item['name']+'-build');out.mkdir(exist_ok=resume)
        dest=work/(item['name']+'-stage')
        with (work/(item['name']+'.log')).open('w') as log:
            args=[str(source/'configure'),'--prefix=/usr','--libdir=/usr/lib','--host=x86_64-kiki-linux-gnu','--build=x86_64-pc-linux-gnu',
                  '--disable-static','--disable-specs','--disable-devel-docs','--without-xmlto','--without-fop']
            for command in [args,['make','-j2'],['make','DESTDIR='+str(dest),'install']]:
                subprocess.run(command,cwd=out,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
        shutil.copytree(dest,private,dirs_exist_ok=True,symlinks=True)
        for path in private.rglob('*.la'):path.unlink()
        if item['name']!='xtrans':
            for path in (dest/'usr/lib').glob('lib*.so*'):
                target=stage/'usr/lib'/path.name;assert not target.exists() and not target.is_symlink()
                if path.is_symlink():target.symlink_to(os.readlink(path))
                else:shutil.copy2(path,target)
            locale=dest/'usr/share/X11/locale'
            if locale.is_dir():shutil.copytree(locale,stage/'usr/share/X11/locale')
        license=source/'COPYING'
        if license.is_file():
            target=stage/'usr/share/licenses/kiki-browser-x11-libs'/(item['name']+'.txt');target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(license,target)
        print('Native candidate library built:',item['name'],item['version'],flush=True)
        progress['completed'].append(item['name']);receipt.write_text(json.dumps(progress,indent=2))
    (work/'build-inputs.json').write_text(json.dumps(dict(base_sdk=str(sdk),private_sdk=str(private),lock_sha256=hashlib.sha256(lockfile.read_bytes()).hexdigest(),sources=lock['sources'],builder_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),resumed=resume),indent=2))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['sdk','work','inputs','lock','stage']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--resume',action='store_true',help='Continue only a matching, receipted private SDK and payload')
    a=p.parse_args();build(a.sdk,a.work,a.inputs,a.lock,a.stage,a.resume)


if __name__=='__main__':main()
