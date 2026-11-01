"""Stage the desktop defaults and their declared boot-time service links."""
import argparse
from pathlib import Path
import shutil

LINKS={
 'usr/lib/systemd/user/graphical-session-pre.target.wants/xdg-user-dirs.service':'../xdg-user-dirs.service',
 'etc/systemd/system/multi-user.target.wants/kiki-desktop-firewall.service':'../../../../usr/lib/systemd/system/kiki-desktop-firewall.service',
 'etc/systemd/system/sysinit.target.wants/systemd-timesyncd.service':'../../../../usr/lib/systemd/system/systemd-timesyncd.service',
}


def stage(source,dest):
    source=Path(source).resolve(strict=True);dest=Path(dest).resolve()
    if dest==Path('/') or dest==source or dest.is_relative_to(source):raise ValueError('separate package staging root required')
    shutil.copytree(source,dest,symlinks=True,dirs_exist_ok=True)
    for path in dest.rglob('*'):
        if path.is_symlink():continue
        path.chmod(0o755 if path.is_dir() else 0o644)
    for name,target in LINKS.items():
        path=dest/name
        if not path.parent.resolve().is_relative_to(dest):raise ValueError('service link escapes package root')
        path.parent.mkdir(parents=True,exist_ok=True)
        if path.is_symlink():path.unlink()
        elif path.exists():raise ValueError('service link destination is a regular file')
        path.symlink_to(target)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--dest',type=Path,required=True)
    a=p.parse_args();stage(a.source,a.dest)
