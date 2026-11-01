"""Install the packaged SSH defaults before other sshd settings are evaluated."""
import argparse
from pathlib import Path
import shutil

INCLUDE='Include /etc/ssh/sshd_config.d/00-kiki-defaults.conf\n'


def prepare(root,source):
    root=Path(root).resolve(strict=True);source=Path(source)
    if root==Path('/'):raise ValueError('a separate package staging root is required')
    config=root/'etc/ssh/sshd_config'
    if config.is_symlink() or not config.resolve().is_relative_to(root):raise ValueError('unsafe SSH configuration path')
    text=config.read_text(encoding='utf-8')
    if not text.startswith(INCLUDE):config.write_text(INCLUDE+text,encoding='utf-8')
    config.chmod(0o644)
    dest=root/'etc/ssh/sshd_config.d'
    if not dest.resolve().is_relative_to(root):raise ValueError('unsafe SSH policy directory')
    dest.mkdir(parents=True,exist_ok=True)
    path=dest/'00-kiki-defaults.conf'
    if path.is_symlink():raise ValueError('unsafe SSH policy file')
    shutil.copyfile(source/'etc/ssh/sshd_config.d/00-kiki-defaults.conf',path);path.chmod(0o644)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--source',type=Path,required=True)
    p.add_argument('--baseline',type=Path);p.add_argument('--expected')
    a=p.parse_args()
    if bool(a.baseline)!=bool(a.expected):p.error('baseline and expected hash must be provided together')
    if a.baseline:
        import ki2build
        if ki2build.file_sha256(a.baseline)!=a.expected:raise ValueError('OpenSSH baseline SHA mismatch')
        if ki2build.read_package_manifest(a.baseline)['name']!='openssh':raise ValueError('OpenSSH package required')
        ki2build.extract_package_rootfs(a.baseline,a.root)
    prepare(a.root,a.source)
