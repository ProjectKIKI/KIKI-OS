#!/usr/bin/env python3
import argparse
import gzip
import os
import tarfile
import tempfile
from pathlib import Path


EXECUTABLE_PATHS = {
    "usr/local/bin/kiki-install",
    "usr/local/bin/kiki-install.py",
    "etc/local.d/kiki-autoinstall.start",
}


def should_skip(path):
    return "__pycache__" in path.parts or path.suffix == ".pyc"


def add_path(tar, root, path):
    arcname = "." if path == root else str(path.relative_to(root)).replace("\\", "/")
    if should_skip(path):
        return
    info = tar.gettarinfo(str(path), arcname=arcname)
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    info.mtime = 0
    info.pax_headers = {}
    if path.is_dir():
        info.mode = 0o755
        tar.addfile(info)
        return
    info.mode = 0o755 if arcname in EXECUTABLE_PATHS else 0o644
    with path.open("rb") as handle:
        tar.addfile(info, handle)


def build_overlay(source, output):
    source = source.resolve()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".kiki-overlay-", suffix=".tmp", dir=output.parent, delete=False) as handle:
            temporary = Path(handle.name)
            with gzip.GzipFile(filename="", mode="wb", fileobj=handle, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as tar:
                    add_path(tar, source, source)
                    for path in sorted(source.rglob("*")):
                        add_path(tar, source, path)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o640)
        os.replace(temporary, output)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Build a normalized KIKI Alpine overlay tarball")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build_overlay(args.source, args.output)


if __name__ == "__main__":
    main()
