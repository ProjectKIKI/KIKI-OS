#!/usr/bin/env python3
"""Publish KIKI build artifacts into a deployable directory tree."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
from pathlib import Path
from typing import Any


UTC = dt.timezone.utc


class PublishError(RuntimeError):
    pass


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def copytree_contents(source: Path, target: Path) -> int:
    count = 0
    if not source.exists():
        return count
    target.mkdir(parents=True, exist_ok=True)
    for child in sorted(source.iterdir()):
        dest = target / child.name
        if child.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(child, dest)
            count += sum(1 for path in dest.rglob("*") if path.is_file())
        else:
            shutil.copy2(child, dest)
            count += 1
    return count


def publish(repo_root: Path, target: Path, arch: str) -> dict[str, Any]:
    sources = {
        "repo": repo_root / "dist" / "ki2" / "repo",
        "packages": repo_root / "dist" / "ki2" / "packages" / arch,
        "iso": repo_root / "dist" / "iso",
    }
    if not any(path.exists() for path in sources.values()):
        raise PublishError("no build artifacts found under dist/")

    target.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "ki2-publish-v1",
        "arch": arch,
        "created_at": dt.datetime.now(UTC).isoformat(),
        "target": str(target),
        "items": {},
    }
    for name, source in sources.items():
        destination = target / name
        count = copytree_contents(source, destination)
        manifest["items"][name] = {
            "source": str(source),
            "destination": str(destination),
            "files": count,
        }

    (target / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def command_publish(args: argparse.Namespace) -> None:
    manifest = publish(args.repo_root.resolve(), args.target.resolve(), args.arch)
    print(f"ki2publish: wrote {manifest['target']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish KIKI build artifacts")
    parser.add_argument("--repo-root", type=Path, default=default_repo_root())
    parser.add_argument("--target", type=Path, default=None)
    parser.add_argument("--arch", default="x86_64")
    parser.set_defaults(func=command_publish)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.target is None:
        args.target = args.repo_root / "dist" / "publish"
    try:
        args.func(args)
    except PublishError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
