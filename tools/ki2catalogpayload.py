"""Refresh a GTK installer payload while preserving a pinned host ABI runtime."""
import argparse
import json
from pathlib import Path
import shutil
import ki2build


def refresh(baseline, expected, binary, catalog, css, dest):
    if ki2build.file_sha256(baseline) != expected:
        raise ValueError('GTK baseline package SHA-256 mismatch')
    manifest = ki2build.read_package_manifest(baseline)
    if manifest['name'] != 'kiki-installer-gtk':
        raise ValueError('GTK baseline package required')
    ki2build.extract_package_rootfs(baseline, dest)
    target = dest / 'usr/bin/kiki-installer-gtk'
    shutil.copyfile(binary, target); target.chmod(0o755)
    target_css = dest / 'usr/share/kiki-installer-gtk/style.css'
    shutil.copyfile(css, target_css); target_css.chmod(0o644)
    path = dest / 'usr/share/kiki-installer-gtk/runtime-manifest.json'
    data = json.loads(path.read_text())
    data.update(installer_binary_sha256=ki2build.file_sha256(target),
                catalog_sha256=ki2build.file_sha256(catalog), parent_package_sha256=expected)
    files = [p for p in dest.rglob('*') if p.is_file() and not p.is_symlink() and p != path]
    data.update(files=len(files), bytes=sum(p.stat().st_size for p in files))
    path.write_text(json.dumps(data, sort_keys=True, indent=2)+'\n', encoding='utf-8')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['baseline','binary','catalog','css','dest']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--expected',required=True);a=p.parse_args()
    refresh(a.baseline,a.expected,a.binary,a.catalog,a.css,a.dest)


if __name__=='__main__':main()
