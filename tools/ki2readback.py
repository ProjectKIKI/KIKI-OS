"""Read-only checks of an extracted ISO, not a boot/install test.

Compare selected GTK/schema files against external build references. References
are caller-selected evidence, not independent authenticity anchors.
"""
import argparse
import gzip
import hashlib
from pathlib import Path, PurePosixPath
import stat
import tarfile

import ki2media


class ReadbackError(ValueError):
    pass


def read_exact(stream, length):
    data = stream.read(length)
    if len(data) != length:
        raise ReadbackError("truncated newc archive")
    return data


def digest_stream(stream, length):
    digest = hashlib.sha256()
    while length:
        chunk = read_exact(stream, min(length, 1024 * 1024))
        digest.update(chunk)
        length -= len(chunk)
    return digest.hexdigest()


def member_name(name):
    if name.startswith("./"):
        name = name[2:]
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not name or "\x00" in name:
        raise ReadbackError("unsafe archive member name")
    return str(path)


def verify_newc(stream, expected):
    seen = set()
    found = set()
    while True:
        header = read_exact(stream, 110)
        if header[:6] != b"070701":
            raise ReadbackError("unsupported newc header")
        try:
            fields = [int(header[6 + i*8:14 + i*8], 16) for i in range(13)]
        except ValueError as exc:
            raise ReadbackError("invalid newc numeric field") from exc
        size, namesize = fields[6], fields[11]
        if not 1 <= namesize <= 4096:
            raise ReadbackError("invalid newc name length")
        raw = read_exact(stream, namesize)
        if not raw.endswith(b"\0") or b"\0" in raw[:-1]:
            raise ReadbackError("invalid newc name")
        name = raw[:-1].decode("utf-8")
        read_exact(stream, (-(110 + namesize)) % 4)
        if name == "TRAILER!!!":
            if size:
                raise ReadbackError("nonempty newc trailer")
            break
        name = member_name(name)
        if name in seen:
            raise ReadbackError("duplicate newc member: " + name)
        seen.add(name)
        digest = digest_stream(stream, size)
        read_exact(stream, (-size) % 4)
        if name in expected:
            if not stat.S_ISREG(fields[1]) or digest != expected[name]:
                raise ReadbackError("newc mismatch: " + name)
            found.add(name)
    # Drain to EOF to force gzip CRC validation; only zero padding is allowed.
    while True:
        tail = stream.read(1024 * 1024)
        if not tail:
            break
        if any(tail):
            raise ReadbackError("nonzero data after newc trailer")
    if found != set(expected):
        raise ReadbackError("newc missing expected files: " + str(set(expected) - found))
    return len(found)


def reference_files(root):
    root = Path(root).resolve(strict=True)
    schemas = root / "usr/share/glib-2.0/schemas"
    xml = list(schemas.glob("*.gschema.xml"))
    if not xml:
        raise ReadbackError("reference has no schema XML")
    paths = [root / "usr/bin/kiki-installer-gtk", schemas / "gschemas.compiled"]
    paths += [p for p in schemas.iterdir() if p.is_file() and p.name != "gschemas.compiled"]
    result = {}
    for path in paths:
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
            raise ReadbackError("invalid reference file: " + str(path))
        result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def verify_tar(path, expected):
    found = set()
    with gzip.open(path, "rb") as stream:
        with tarfile.open(fileobj=stream, mode="r|") as archive:
            for member in archive:
                name = member_name(member.name)
                if name not in expected:
                    continue
                if name in found or not member.isfile():
                    raise ReadbackError("duplicate or non-regular tar target: " + name)
                if digest_stream(archive.extractfile(member), member.size) != expected[name]:
                    raise ReadbackError("tar mismatch: " + name)
                found.add(name)
        while stream.read(1024 * 1024):
            pass
    if found != set(expected):
        raise ReadbackError("tar missing expected files: " + str(set(expected) - found))
    return len(found)


def tui_reference(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ReadbackError('invalid TUI reference file')
    return {'usr/bin/kiki-installer-tui': hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media-root", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--graphics-reference", type=Path, required=True)
    parser.add_argument("--rootfs-reference", type=Path, required=True)
    parser.add_argument("--tui-reference", type=Path,
                        help="optional external TUI executable to compare in both archives")
    args = parser.parse_args()
    try:
        packages = ki2media.verify_media(args.media_root, args.public_key)
        graphics = reference_files(args.graphics_reference)
        rootfs = reference_files(args.rootfs_reference)
        if args.tui_reference:
            tui = tui_reference(args.tui_reference)
            graphics.update(tui)
            rootfs.update(tui)
        with gzip.open(args.media_root / "boot/initramfs-kiki.img", "rb") as stream:
            init_count = verify_newc(stream, graphics)
        root_count = verify_tar(args.media_root / "kiki/rootfs.tar.gz", rootfs)
    except (OSError, ValueError, tarfile.TarError, ki2media.MediaError) as exc:
        parser.exit(1, f"Readback failed: {exc}\n")
    print(f"Verified {packages} packages, {init_count} initramfs and {root_count} rootfs selected files (TUI checked: {bool(args.tui_reference)}); NOT a VM test.")


if __name__ == "__main__":
    main()
