#!/usr/bin/env python3
"""Fail closed until the GNOME 50 Wayland session is packaged for KIKI OS.

This is a minimum gate, not a substitute for dependency-closure and VM tests.
"""

import argparse
import hashlib
import json
from pathlib import Path

import ki2build
import ki2repo


SESSION_CORE = (
    "gnome-shell",
    "mutter",
    "gdm",
    "gnome-session",
    "gnome-desktop",
    "gnome-settings-daemon",
    "gjs",
    "gtk",
    "mesa",
    "pipewire",
    "wireplumber",
)


def check(recipes: set[str], packaged: set[str]) -> dict[str, object]:
    missing_recipes = sorted(set(SESSION_CORE) - recipes)
    missing_packages = sorted(set(SESSION_CORE) - packaged)
    return {
        "target": "GNOME 50 Wayland",
        "minimum_core_available": not missing_recipes and not missing_packages,
        "install_menu_enabled": False,
        "minimum_core": list(SESSION_CORE),
        "missing_recipes": missing_recipes,
        "missing_packages": missing_packages,
        "next_checks": [
            "full GNOME build-meta dependency closure",
            "signed package metadata and payload integrity",
            "GDM and GNOME Wayland session boot in an isolated VM",
        ],
    }


def audit_foundation(repo: Path, index: Path, data: dict) -> dict[str, object]:
    metadata_path = index.with_name("metadata.x86_64.json")
    key_path = repo / "build/ki2/keys/stage3-v3-repo.ed25519.pub"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    signature_valid = ki2repo.verify_metadata_file(metadata_path, key_path)
    index_hash_valid = hashlib.sha256(index.read_bytes()).hexdigest() == metadata["index"]["sha256"]
    profile = ki2build.load_profile(repo / "distro/profiles/gnome-foundation.toml")
    indexed = {item["name"]: item for item in data["packages"]}
    package_dir = index.parent.parent / "packages/x86_64"
    missing = []
    bad_hash = []
    for name in profile["packages"]:
        item = indexed.get(name)
        if item is None:
            missing.append(name)
            continue
        file = package_dir / item["file"]
        if not file.is_file():
            missing.append(name)
        elif ki2repo.file_sha256(file) != item["sha256"]:
            bad_hash.append(name)
    return {
        "package_count": len(profile["packages"]),
        "signature_valid": signature_valid,
        "index_hash_valid": index_hash_valid,
        "missing": missing,
        "bad_hash": bad_hash,
        "verified": signature_valid and index_hash_valid and not missing and not bad_hash,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--index", type=Path)
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    index = args.index or repo / "dist/ki2/signed-r20/repo/index.x86_64.json"
    recipes = set(ki2build.load_recipes(repo / "distro/recipes"))
    data = json.loads(index.read_text(encoding="utf-8"))
    if data.get("arch") != "x86_64" or not isinstance(data.get("packages"), list):
        parser.error("invalid x86_64 package index")
    packaged = {str(item["name"]) for item in data["packages"]}
    result = check(recipes, packaged)
    result["signed_foundation"] = audit_foundation(repo, index, data)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["minimum_core_available"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
