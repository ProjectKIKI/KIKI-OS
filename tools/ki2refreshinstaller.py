#!/usr/bin/env python3
"""Rebuild the Go Scratch Pad KI2 from a verified graphical runtime package.

The caller must verify the baseline package against signed repository metadata
before invoking this tool. Other runtime files are preserved byte-for-byte.
"""

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
from types import SimpleNamespace

import ki2build


TITLE = b"KIKI OS Scratch Pad"
OLD_TITLE = b"KIKI OS Installer"


def refresh(baseline: Path, binary: Path, output: Path, release: int, repo_root: Path) -> None:
    if output.exists():
        raise ValueError(f"refusing to overwrite package: {output}")
    old = ki2build.read_package_manifest(baseline)
    if old["name"] != "kiki-installer-gtk" or old["arch"] != "x86_64":
        raise ValueError("baseline must be the x86_64 graphical installer package")
    if release <= int(old["release"]):
        raise ValueError("new release must be greater than the baseline release")
    new_binary = binary.read_bytes()
    if TITLE not in new_binary or OLD_TITLE in new_binary or b"Go/GTK4" in new_binary:
        raise ValueError("binary does not contain only the new Scratch Pad title")

    with tempfile.TemporaryDirectory(prefix="kiki-installer-refresh-") as temporary:
        payload = Path(temporary) / "rootfs"
        payload.mkdir()
        ki2build.extract_package_rootfs(baseline, payload)
        runtime_path = payload / "usr/share/kiki-installer-gtk/runtime-manifest.json"
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        if runtime.get("installer_ui") != "gotk":
            raise ValueError("baseline must contain the Go/GTK graphical runtime")
        installed_binary = payload / "usr/bin/kiki-installer-gtk"
        previous_size = installed_binary.stat().st_size
        shutil.copyfile(binary, installed_binary)
        installed_binary.chmod(0o755)
        runtime["bytes"] += len(new_binary) - previous_size
        runtime["display_name"] = TITLE.decode("ascii")
        runtime_path.write_text(json.dumps(runtime, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                                encoding="utf-8")

        files = ki2build.package_file_manifest(payload)
        digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
        recipe = ki2build.load_recipes(repo_root / "distro/recipes")["kiki-installer-gtk"]
        recipe = replace(recipe, release=str(release),
                         summary="KIKI OS Scratch Pad graphical installer and Cage runtime",
                         license=old["license"], digest=digest)
        ki2build.create_package(SimpleNamespace(arch="x86_64"), recipe, payload, output, digest, {})

    updated = ki2build.read_package_manifest(output)
    if updated["release"] != str(release) or updated["name"] != old["name"]:
        raise ValueError("new installer package metadata is invalid")
    with tarfile.open(output, "r:gz") as archive:
        member = archive.extractfile("rootfs/usr/bin/kiki-installer-gtk")
        if member is None or hashlib.sha256(member.read()).digest() != hashlib.sha256(new_binary).digest():
            raise ValueError("new package does not contain the rebuilt binary")


def refresh_rootfs(baseline_rootfs: Path, output_rootfs: Path, package: Path) -> None:
    """Update the preinstalled GUI without overwriting target util-linux libraries."""
    if output_rootfs.exists():
        raise ValueError(f"refusing to overwrite rootfs: {output_rootfs}")
    manifest = ki2build.read_package_manifest(package)
    if manifest["name"] != "kiki-installer-gtk":
        raise ValueError("rootfs update requires a graphical installer package")
    state_path = baseline_rootfs / "var/lib/ki2/installed.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    previous = state["packages"].get("kiki-installer-gtk")
    if previous is None or int(previous["release"]) >= int(manifest["release"]):
        raise ValueError("rootfs must contain an older graphical installer")
    shutil.copytree(baseline_rootfs, output_rootfs, symlinks=True)
    with tarfile.open(package, "r:gz") as archive:
        for relative in ("usr/bin/kiki-installer-gtk",
                         "usr/share/kiki-installer-gtk/runtime-manifest.json"):
            member = archive.extractfile("rootfs/" + relative)
            if member is None:
                raise ValueError(f"package is missing {relative}")
            target = output_rootfs / relative
            if not target.is_file() or target.is_symlink():
                raise ValueError(f"rootfs does not contain a regular {relative}")
            target.write_bytes(member.read())
            target.chmod(0o755 if relative.startswith("usr/bin/") else 0o644)
    previous.update({
        "version": manifest["version"], "release": manifest["release"],
        "file": package.name, "sha256": ki2build.file_sha256(package),
        "summary": manifest["summary"], "dependencies": manifest["dependencies"],
        "files": ki2build.package_manifest_files(manifest),
    })
    (output_rootfs / "var/lib/ki2/installed.json").write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-package", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--release", required=True, type=int)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--baseline-rootfs", type=Path)
    parser.add_argument("--rootfs-output", type=Path)
    args = parser.parse_args()
    if bool(args.baseline_rootfs) != bool(args.rootfs_output):
        parser.error("--baseline-rootfs and --rootfs-output must be used together")
    refresh(args.baseline_package.resolve(strict=True), args.binary.resolve(strict=True),
            args.output.resolve(), args.release, args.repo_root.resolve(strict=True))
    print(f"Rebuilt Scratch Pad package: {args.output}")
    if args.baseline_rootfs:
        refresh_rootfs(args.baseline_rootfs.resolve(strict=True), args.rootfs_output.resolve(),
                       args.output.resolve(strict=True))
        print(f"Updated rootfs: {args.rootfs_output}")


if __name__ == "__main__":
    main()
