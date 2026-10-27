#!/usr/bin/env python3
"""Package a locally prepared KI2 payload for isolated candidate testing."""

import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import ki2build


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--payload", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    payload = args.payload.resolve(strict=True)
    output = args.output.resolve()
    if output.exists():
        parser.error(f"refusing to overwrite {output}")
    recipe = ki2build.load_recipes(repo / "distro/recipes")[args.name]
    files = ki2build.package_file_manifest(payload)
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    ki2build.create_package(SimpleNamespace(arch="x86_64"), recipe, payload,
                            output, digest, {})
    manifest = ki2build.read_package_manifest(output)
    if manifest["name"] != args.name or manifest["release"] != recipe.release:
        raise ValueError("candidate package manifest mismatch")
    print(f"Created {output} ({output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
