#!/usr/bin/env python3
"""Refresh the signed-repo AI console payload with the Korean input candidate."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace

import ki2build


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    baseline = args.baseline.resolve(strict=True)
    binary = args.binary.resolve(strict=True)
    output = args.output.resolve()
    if output.exists():
        parser.error(f"refusing to overwrite {output}")
    previous = ki2build.read_package_manifest(baseline)
    recipe = ki2build.load_recipes(repo / "distro/recipes")["kiki-ai-console"]
    if previous["name"] != recipe.name or int(previous["release"]) >= int(recipe.release):
        parser.error("baseline is not an older AI console package")
    with tempfile.TemporaryDirectory(prefix="kiki-ai-console-ko-") as temporary:
        root = Path(temporary)
        ki2build.extract_package_rootfs(baseline, root)
        shutil.copy2(binary, root / "usr/bin/kiki-ai-console")
        service = "etc/systemd/system/kiki-ai-console-kmscon@.service"
        doc = "usr/share/doc/kiki-ai-console/README.ko.md"
        for relative in (service, doc):
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(repo / "distro/sources/kiki-ai-console" / relative, destination)
        files = ki2build.package_file_manifest(root)
        digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
        output.parent.mkdir(parents=True, exist_ok=True)
        ki2build.create_package(SimpleNamespace(arch="x86_64"), recipe, root, output, digest, {})
    updated = ki2build.read_package_manifest(output)
    if updated["release"] != recipe.release or updated["name"] != recipe.name:
        raise ValueError("candidate package manifest mismatch")
    print(f"Created {output} ({output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
