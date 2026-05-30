#!/usr/bin/env python3
"""Generate KIKI HTTP repository indexes and operational metadata."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import re
import secrets
import sys
import tarfile
from pathlib import Path
from typing import Any


UTC = dt.timezone.utc
INDEX_SCHEMA = "ki2-repository-v1"
METADATA_SCHEMA = "ki2-repository-metadata-v1"
CHANNELS_SCHEMA = "ki2-repository-channels-v1"
SIGNATURE_ALGORITHM = "hmac-sha256"
DEFAULT_STAGE2_CHANNEL = "stage2-v2"


class Ki2RepoError(RuntimeError):
    pass


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_package_manifest(path: Path) -> dict[str, Any]:
    try:
        with tarfile.open(path, "r:gz") as tar:
            manifest_file = tar.extractfile("manifest.json")
            if manifest_file is None:
                raise Ki2RepoError(f"{path}: manifest.json is missing")
            return json.loads(manifest_file.read().decode("utf-8"))
    except (tarfile.TarError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise Ki2RepoError(f"{path}: cannot read package manifest: {exc}") from exc


def natural_key(value: Any) -> tuple[tuple[int, Any], ...]:
    parts: list[tuple[int, Any]] = []
    for part in re.split(r"([0-9]+)", str(value)):
        if not part:
            continue
        parts.append((0, int(part)) if part.isdigit() else (1, part))
    return tuple(parts)


def package_sort_key(pkg: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(pkg.get("name", "")),
        natural_key(pkg.get("version", "")),
        natural_key(pkg.get("release", "")),
        str(pkg.get("file", "")),
    )


def latest_sort_key(pkg: dict[str, Any]) -> tuple[Any, ...]:
    return (
        natural_key(pkg.get("version", "")),
        natural_key(pkg.get("release", "")),
        str(pkg.get("file", "")),
    )


def package_entry(path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    dependencies = manifest.get(
        "dependencies",
        {"build": [], "runtime": manifest.get("runtime_dependencies", [])},
    )
    if not isinstance(dependencies, dict):
        dependencies = {"build": [], "runtime": []}
    return {
        "name": manifest["name"],
        "version": str(manifest["version"]),
        "release": str(manifest["release"]),
        "arch": manifest["arch"],
        "file": path.name,
        "size": path.stat().st_size,
        "sha256": file_sha256(path),
        "summary": manifest.get("summary", ""),
        "license": manifest.get("license", ""),
        "tier": manifest.get("tier", ""),
        "dependencies": dependencies,
        "runtime_dependencies": dependencies.get("runtime", []),
        "file_count": manifest.get("payload", {}).get("file_count", len(manifest.get("files", []))),
    }


def scan_packages(packages_dir: Path, arch: str) -> list[dict[str, Any]]:
    if not packages_dir.exists():
        raise Ki2RepoError(f"package directory not found: {packages_dir}")
    packages: list[dict[str, Any]] = []
    for path in sorted(packages_dir.glob("*.ki2")):
        manifest = read_package_manifest(path)
        package_arch = str(manifest.get("arch", ""))
        if package_arch not in (arch, "all"):
            continue
        packages.append(package_entry(path, manifest))
    packages.sort(key=package_sort_key)
    return packages


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def canonical_json_bytes(data: dict[str, Any]) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def read_signing_key(path: Path) -> bytes:
    if not path.exists():
        raise Ki2RepoError(f"signing key not found: {path}")
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        raise Ki2RepoError(f"signing key is empty: {path}")
    try:
        return bytes.fromhex(raw)
    except ValueError:
        return raw.encode("utf-8")


def key_id(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:16]


def signature_payload(metadata: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(json.dumps(metadata))
    security = dict(payload.get("security", {}))
    security["signature"] = None
    payload["security"] = security
    return payload


def sign_metadata(metadata: dict[str, Any], key: bytes, *, signed_at: str | None = None) -> dict[str, Any]:
    signed = json.loads(json.dumps(metadata))
    capabilities = signed.setdefault("capabilities", [])
    if isinstance(capabilities, list) and "signed-metadata-hmac-sha256" not in capabilities:
        capabilities.append("signed-metadata-hmac-sha256")
    security = dict(signed.get("security", {}))
    security.update(
        {
            "signed": True,
            "algorithm": SIGNATURE_ALGORITHM,
            "key_id": key_id(key),
            "signed_at": signed_at or dt.datetime.now(UTC).isoformat(),
            "signature": None,
            "note": "Stage 2 repository metadata is signed with the development HMAC-SHA256 scheme.",
        }
    )
    signed["security"] = security
    digest = hmac.new(key, canonical_json_bytes(signature_payload(signed)), hashlib.sha256).hexdigest()
    signed["security"]["signature"] = digest
    return signed


def verify_metadata_signature(metadata: dict[str, Any], key: bytes) -> bool:
    security = metadata.get("security", {})
    if not isinstance(security, dict):
        return False
    if security.get("algorithm") != SIGNATURE_ALGORITHM:
        return False
    signature = str(security.get("signature") or "")
    if not signature:
        return False
    expected = hmac.new(key, canonical_json_bytes(signature_payload(metadata)), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def sign_metadata_file(metadata_path: Path, key_path: Path) -> dict[str, Any]:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    signed = sign_metadata(metadata, read_signing_key(key_path))
    write_json(metadata_path, signed)
    return signed


def verify_metadata_file(metadata_path: Path, key_path: Path) -> bool:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    return verify_metadata_signature(metadata, read_signing_key(key_path))


def build_index(packages: list[dict[str, Any]], arch: str, created_at: str) -> dict[str, Any]:
    return {
        "schema": INDEX_SCHEMA,
        "arch": arch,
        "created_at": created_at,
        "packages": packages,
    }


def latest_packages(packages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for pkg in packages:
        current = latest.get(str(pkg.get("name", "")))
        if current is None or latest_sort_key(pkg) > latest_sort_key(current):
            latest[str(pkg["name"])] = pkg
    return [latest[name] for name in sorted(latest)]


def tier_counts(packages: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for pkg in packages:
        tier = str(pkg.get("tier") or "unknown")
        counts[tier] = counts.get(tier, 0) + 1
    return dict(sorted(counts.items()))


def iso_entries(iso_dir: Path) -> list[dict[str, Any]]:
    if not iso_dir.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(iso_dir.glob("*.iso")):
        items.append(
            {
                "file": path.name,
                "size": path.stat().st_size,
                "sha256": file_sha256(path),
            }
        )
    return items


def build_metadata(
    *,
    name: str,
    title: str,
    description: str,
    channel: str,
    arch: str,
    base_url: str,
    created_at: str,
    repo_dir: Path,
    packages_dir: Path,
    iso_dir: Path,
    packages: list[dict[str, Any]],
) -> dict[str, Any]:
    index_path = repo_dir / f"index.{arch}.json"
    total_size = sum(int(pkg.get("size", 0)) for pkg in packages)
    latest = latest_packages(packages)
    return {
        "schema": METADATA_SCHEMA,
        "name": name,
        "title": title,
        "description": description,
        "channel": channel,
        "arch": arch,
        "base_url": base_url,
        "created_at": created_at,
        "index": {
            "path": f"repo/index.{arch}.json",
            "size": index_path.stat().st_size if index_path.exists() else 0,
            "sha256": file_sha256(index_path) if index_path.exists() else "",
            "package_count": len(packages),
            "total_package_size": total_size,
        },
        "packages": {
            "path": "packages/",
            "source_path": str(packages_dir),
            "count": len(packages),
            "total_size": total_size,
            "tiers": tier_counts(packages),
            "latest": [
                {
                    "name": pkg.get("name", ""),
                    "version": pkg.get("version", ""),
                    "release": pkg.get("release", ""),
                    "arch": pkg.get("arch", ""),
                    "file": pkg.get("file", ""),
                    "size": pkg.get("size", 0),
                    "sha256": pkg.get("sha256", ""),
                    "summary": pkg.get("summary", ""),
                    "tier": pkg.get("tier", ""),
                }
                for pkg in latest
            ],
        },
        "artifacts": {
            "iso_path": "iso/",
            "source_iso_path": str(iso_dir),
            "iso": iso_entries(iso_dir),
        },
        "capabilities": [
            "http-index",
            "sha256-packages",
            "runtime-dependencies",
            "ki2ctl-install",
            "ki2ctl-upgrade",
        ],
        "security": {
            "signed": False,
            "signature": None,
            "note": "Stage 2 metadata is unsigned; use tools/ki2repo.py generate --sign-key for verified update flows.",
        },
    }


def build_channels(
    *,
    name: str,
    channel: str,
    arch: str,
    base_url: str,
    created_at: str,
    metadata_path: Path,
    index_path: Path,
) -> dict[str, Any]:
    return {
        "schema": CHANNELS_SCHEMA,
        "name": name,
        "created_at": created_at,
        "channels": {
            channel: {
                "arch": arch,
                "base_url": base_url,
                "metadata": f"repo/{metadata_path.name}",
                "metadata_sha256": file_sha256(metadata_path) if metadata_path.exists() else "",
                "index": f"repo/{index_path.name}",
                "index_sha256": file_sha256(index_path) if index_path.exists() else "",
            }
        },
    }


def generate(args: argparse.Namespace) -> dict[str, Any]:
    created_at = dt.datetime.now(UTC).isoformat()
    packages = scan_packages(args.packages_dir, args.arch)
    index = build_index(packages, args.arch, created_at)
    index_path = args.repo_dir / f"index.{args.arch}.json"
    write_json(index_path, index)

    metadata = build_metadata(
        name=args.name,
        title=args.title,
        description=args.description,
        channel=args.channel,
        arch=args.arch,
        base_url=args.base_url,
        created_at=created_at,
        repo_dir=args.repo_dir,
        packages_dir=args.packages_dir,
        iso_dir=args.iso_dir,
        packages=packages,
    )
    metadata_path = args.repo_dir / f"metadata.{args.arch}.json"
    write_json(metadata_path, metadata)
    if getattr(args, "sign_key", None):
        sign_metadata_file(metadata_path, args.sign_key)

    channels = build_channels(
        name=args.name,
        channel=args.channel,
        arch=args.arch,
        base_url=args.base_url,
        created_at=created_at,
        metadata_path=metadata_path,
        index_path=index_path,
    )
    channels_path = args.repo_dir / "channels.json"
    write_json(channels_path, channels)

    return {
        "index": str(index_path),
        "metadata": str(metadata_path),
        "channels": str(channels_path),
        "packages": len(packages),
        "total_size": sum(int(pkg.get("size", 0)) for pkg in packages),
    }


def command_generate(args: argparse.Namespace) -> None:
    result = generate(args)
    print(f"[repo] wrote {result['index']} ({result['packages']} packages)")
    print(f"[repo] wrote {result['metadata']}")
    print(f"[repo] wrote {result['channels']}")


def command_summary(args: argparse.Namespace) -> None:
    metadata_path = args.repo_dir / f"metadata.{args.arch}.json"
    if not metadata_path.exists():
        raise Ki2RepoError(f"metadata not found: {metadata_path}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    print(f"Name      : {metadata.get('name')}")
    print(f"Channel   : {metadata.get('channel')}")
    print(f"Arch      : {metadata.get('arch')}")
    print(f"Base URL  : {metadata.get('base_url') or '-'}")
    print(f"Packages  : {metadata.get('index', {}).get('package_count', 0)}")
    print(f"Total size: {metadata.get('index', {}).get('total_package_size', 0)}")
    print(f"Signed    : {metadata.get('security', {}).get('signed', False)}")
    algorithm = metadata.get("security", {}).get("algorithm")
    if algorithm:
        print(f"Algorithm : {algorithm}")
        print(f"Key ID    : {metadata.get('security', {}).get('key_id', '-')}")


def command_keygen(args: argparse.Namespace) -> None:
    if args.output.exists() and not args.force:
        raise Ki2RepoError(f"key already exists: {args.output}; use --force to overwrite")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(secrets.token_hex(32) + "\n", encoding="utf-8")
    try:
        args.output.chmod(0o600)
    except OSError:
        pass
    print(f"[repo] wrote signing key {args.output}")


def command_sign(args: argparse.Namespace) -> None:
    metadata_path = args.repo_dir / f"metadata.{args.arch}.json"
    signed = sign_metadata_file(metadata_path, args.key)
    channels_path = args.repo_dir / "channels.json"
    if channels_path.exists():
        channels = json.loads(channels_path.read_text(encoding="utf-8"))
        channel = str(signed.get("channel", DEFAULT_STAGE2_CHANNEL))
        entry = channels.setdefault("channels", {}).setdefault(channel, {})
        entry["metadata_sha256"] = file_sha256(metadata_path)
        entry["metadata"] = f"repo/{metadata_path.name}"
        write_json(channels_path, channels)
    print(f"[repo] signed {metadata_path} key_id={signed['security']['key_id']}")


def command_verify(args: argparse.Namespace) -> None:
    metadata_path = args.repo_dir / f"metadata.{args.arch}.json"
    if not verify_metadata_file(metadata_path, args.key):
        raise Ki2RepoError(f"signature verification failed: {metadata_path}")
    print(f"[repo] verified {metadata_path}")


def resolve_paths(args: argparse.Namespace) -> None:
    args.repo_root = args.repo_root.resolve()
    defaults = {
        "packages_dir": args.repo_root / "dist" / "ki2" / "packages" / args.arch,
        "repo_dir": args.repo_root / "dist" / "ki2" / "repo",
        "iso_dir": args.repo_root / "dist" / "iso",
    }
    for attr, default in defaults.items():
        value = getattr(args, attr)
        setattr(args, attr, value.resolve() if value else default)
    for attr in ("sign_key", "key", "output"):
        if hasattr(args, attr):
            value = getattr(args, attr)
            if value is not None:
                path = value if value.is_absolute() else args.repo_root / value
                setattr(args, attr, path.resolve())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate KIKI repository metadata")
    parser.add_argument("--repo-root", type=Path, default=default_repo_root())
    parser.add_argument("--arch", default="x86_64")
    parser.add_argument("--packages-dir", type=Path, default=None)
    parser.add_argument("--repo-dir", type=Path, default=None)
    parser.add_argument("--iso-dir", type=Path, default=None)
    subcommands = parser.add_subparsers(dest="command", required=True)

    generate_parser = subcommands.add_parser("generate", help="write index, metadata, and channel files")
    generate_parser.add_argument("--name", default="kiki-os")
    generate_parser.add_argument("--title", default="KIKI OS Package Repository")
    generate_parser.add_argument("--description", default="KIKI OS .ki2 package repository")
    generate_parser.add_argument("--channel", default=DEFAULT_STAGE2_CHANNEL)
    generate_parser.add_argument("--base-url", default="")
    generate_parser.add_argument("--sign-key", type=Path, default=None, help="optional HMAC signing key")
    generate_parser.set_defaults(func=command_generate)

    summary_parser = subcommands.add_parser("summary", help="show repository metadata summary")
    summary_parser.set_defaults(func=command_summary)

    keygen_parser = subcommands.add_parser("keygen", help="generate a Stage 2 repository HMAC signing key")
    keygen_parser.add_argument("--output", type=Path, default=Path("build/ki2/keys/stage2-v2-repo.hmac"))
    keygen_parser.add_argument("--force", action="store_true")
    keygen_parser.set_defaults(func=command_keygen)

    sign_parser = subcommands.add_parser("sign", help="sign repository metadata")
    sign_parser.add_argument("--key", type=Path, required=True)
    sign_parser.set_defaults(func=command_sign)

    verify_parser = subcommands.add_parser("verify", help="verify repository metadata signature")
    verify_parser.add_argument("--key", type=Path, required=True)
    verify_parser.set_defaults(func=command_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    resolve_paths(args)
    try:
        args.func(args)
    except (Ki2RepoError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
