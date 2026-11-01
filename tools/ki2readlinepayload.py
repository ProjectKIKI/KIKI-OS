"""Remove install backups and validate Readline's native terminal dependency."""
import argparse
from pathlib import Path
import re
import subprocess


def prepare(root):
    root=Path(root).resolve(strict=True)
    if root==Path('/') or not (root/'usr/lib').resolve().is_relative_to(root):
        raise ValueError('a separate package staging root is required')
    directory=root/'usr/lib'
    removed=[]
    for pattern in ('libreadline*.old','libhistory*.old'):
        for path in directory.glob(pattern):
            if path.is_dir():raise ValueError('unexpected library backup directory')
            path.unlink();removed.append(path.name)
    binary=directory/'libreadline.so.8.3'
    if not binary.resolve(strict=True).is_relative_to(root):raise ValueError('library escapes package root')
    dynamic=subprocess.check_output(['readelf','-d',str(binary)],text=True)
    if not re.search(r'\(NEEDED\).*\[libncursesw\.so\.6\]',dynamic):
        raise ValueError('Readline must link the native wide-character ncurses library')
    for name in ('libreadline','libhistory'):
        target=name+'.so.8.3';library=directory/target
        if not library.is_file():raise ValueError('missing '+target)
        link=directory/(name+'.so.8')
        if link.is_symlink():link.unlink()
        elif link.exists():raise ValueError('unexpected regular SONAME file')
        link.symlink_to(target)
    return removed


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    print('Removed Readline install backups:',prepare(parser.parse_args().root))
