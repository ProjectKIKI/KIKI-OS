#!/usr/bin/env python3
"""Create a KIKI distribution ISO image from built rootfs and repository output."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any


UTC = dt.timezone.utc


class IsoError(RuntimeError):
    pass


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def copytree_contents(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for child in sorted(source.iterdir()):
        dest = target / child.name
        if child.is_dir():
            shutil.copytree(child, dest, dirs_exist_ok=True)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, dest)


def write_rootfs_tar(rootfs_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz") as tar:
        for path in sorted(rootfs_dir.rglob("*")):
            rel = path.relative_to(rootfs_dir).as_posix()
            tar.add(path, arcname=rel, recursive=False)


def prepare_iso_tree(
    rootfs_dir: Path,
    repo_dir: Path,
    tree_dir: Path,
    *,
    arch: str,
    profile: str,
    label: str,
) -> dict[str, Any]:
    if not rootfs_dir.exists():
        raise IsoError(f"rootfs directory not found: {rootfs_dir}")
    if not repo_dir.exists():
        raise IsoError(f"repository directory not found: {repo_dir}")

    if tree_dir.exists():
        shutil.rmtree(tree_dir)
    tree_dir.mkdir(parents=True)

    payload_dir = tree_dir / "kiki"
    payload_dir.mkdir()
    copytree_contents(repo_dir, payload_dir / "repo")
    write_rootfs_tar(rootfs_dir, payload_dir / "rootfs.tar.gz")

    manifest = {
        "schema": "ki2-iso-v1",
        "arch": arch,
        "profile": profile,
        "label": label,
        "created_at": dt.datetime.now(UTC).isoformat(),
        "rootfs": "kiki/rootfs.tar.gz",
        "repo": "kiki/repo",
        "bootable": False,
        "notes": [
            "This is an early KIKI distribution media image.",
            "Bootloader and initramfs integration are not included yet.",
        ],
    }
    (tree_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (tree_dir / "README.txt").write_text(
        "\n".join(
            [
                "KIKI OS distribution media",
                "",
                f"Profile: {profile}",
                f"Architecture: {arch}",
                "",
                "Contents:",
                "- manifest.json",
                "- kiki/rootfs.tar.gz",
                "- kiki/repo/",
                "",
                "This first ISO is a packaging and installer payload image.",
                "A bootable ISO needs the next bootloader/initramfs milestone.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return manifest


def find_iso_tool() -> tuple[str, list[str]]:
    for name in ("xorriso", "genisoimage", "mkisofs"):
        path = shutil.which(name)
        if path:
            if name == "xorriso":
                return path, [path, "-as", "mkisofs"]
            return path, [path]
    raise IsoError("ISO builder not found; install xorriso or genisoimage")


def build_iso(tree_dir: Path, output: Path, label: str) -> None:
    _, base_cmd = find_iso_tool()
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp_output = output.with_suffix(output.suffix + ".tmp")
    if tmp_output.exists():
        tmp_output.unlink()

    cmd = [
        *base_cmd,
        "-r",
        "-J",
        "-V",
        label[:32],
        "-o",
        str(tmp_output),
        str(tree_dir),
    ]
    subprocess.run(cmd, check=True)
    tmp_output.replace(output)


def command_build(args: argparse.Namespace) -> None:
    repo_root = args.repo_root.resolve()
    rootfs_dir = args.rootfs_dir or repo_root / "dist" / "rootfs" / args.profile
    repo_dir = args.repo_dir or repo_root / "dist" / "ki2" / "repo"
    output = args.output or repo_root / "dist" / "iso" / f"kiki-{args.profile}-{args.arch}.iso"
    label = args.label or f"KIKI_{args.profile}_{args.arch}".replace("-", "_").upper()

    if args.keep_tree:
        tree_dir = args.keep_tree
        manifest = prepare_iso_tree(rootfs_dir, repo_dir, tree_dir, arch=args.arch, profile=args.profile, label=label)
        if args.dry_run:
            print(f"prepared ISO tree: {tree_dir}")
            print(json.dumps(manifest, indent=2, sort_keys=True))
            return
        build_iso(tree_dir, output, label)
    else:
        with tempfile.TemporaryDirectory(prefix="ki2iso-") as tmp:
            tree_dir = Path(tmp) / "iso-tree"
            manifest = prepare_iso_tree(rootfs_dir, repo_dir, tree_dir, arch=args.arch, profile=args.profile, label=label)
            if args.dry_run:
                print(f"would build ISO: {output}")
                print(json.dumps(manifest, indent=2, sort_keys=True))
                return
            build_iso(tree_dir, output, label)

    print(f"ki2iso: wrote {output}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create an early KIKI distribution ISO")
    parser.add_argument("--repo-root", type=Path, default=default_repo_root())
    parser.add_argument("--arch", default="x86_64")
    parser.add_argument("--profile", default="bootstrap-stage1")
    parser.add_argument("--rootfs-dir", type=Path, default=None)
    parser.add_argument("--repo-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--label", default=None)
    parser.add_argument("--keep-tree", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.set_defaults(func=command_build)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (IsoError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
