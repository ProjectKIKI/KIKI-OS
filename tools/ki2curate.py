#!/usr/bin/env python3
"""Select the newest KI2 artifacts from a signed ISO, local builds and add-ons."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import ki2repo
import ki2build


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inventory(folder, source):
    result = []
    for path in sorted(folder.glob("*.ki2")):
        manifest = ki2repo.read_package_manifest(path)
        result.append({"source": source, "file": path.name, "name": manifest["name"],
                       "version": str(manifest["version"]), "release": str(manifest["release"]),
                       "arch": manifest["arch"], "size": path.stat().st_size})
    return result


def release_key(entry):
    return (ki2repo.natural_key(entry["version"]), ki2repo.natural_key(entry["release"]))


def choose_latest(candidates, pinned_versions=None):
    pinned_versions = pinned_versions or {}
    priorities = {"main": 0, "addon": 1, "iso": 2}
    selected = {}
    for entry in candidates:
        if entry["arch"] != "x86_64":
            raise ValueError("unexpected package architecture: " + entry["file"])
        if entry["name"] in pinned_versions and entry["version"] != pinned_versions[entry["name"]]:
            continue
        current = selected.get(entry["name"])
        if current is None or (release_key(entry), priorities[entry["source"]], entry["file"]) > (
                release_key(current), priorities[current["source"]], current["file"]):
            selected[entry["name"]] = entry
    absent = set(pinned_versions) - set(selected)
    if absent:
        raise ValueError("pinned packages missing: " + ", ".join(sorted(absent)))
    obsolete_main = sorted(entry["file"] for entry in candidates if entry["source"] == "main"
                           and (entry["name"] in pinned_versions
                                and entry["version"] != pinned_versions[entry["name"]]
                                or release_key(entry) < release_key(selected[entry["name"]])))
    return [selected[name] for name in sorted(selected)], obsolete_main


def make_plan(args):
    if not ki2repo.verify_metadata_file(args.iso_metadata, args.public_key):
        raise ValueError("ISO metadata signature is invalid")
    metadata = json.loads(args.iso_metadata.read_text())
    if sha256(args.iso_index) != metadata["index"]["sha256"]:
        raise ValueError("ISO index does not match signed metadata")
    signed_index = json.loads(args.iso_index.read_text())
    candidates = inventory(args.main_packages, "main") + inventory(args.addon_packages, "addon")
    candidates.extend({"source": "iso", "file": entry["file"], "name": entry["name"],
                       "version": str(entry["version"]), "release": str(entry["release"]),
                       "arch": entry["arch"], "size": entry["size"], "sha256": entry["sha256"]}
                      for entry in signed_index["packages"])
    recipes = ki2build.load_recipes(Path(__file__).resolve().parents[1] / "distro/recipes")
    pins = {name: recipes[name].version for name in ("linux", "linux-headers")}
    selected, obsolete_main = choose_latest(candidates, pins)
    report = {"schema": "ki2-curation-v1", "iso_index_sha256": sha256(args.iso_index),
              "candidate_count": len(candidates), "selected": selected, "obsolete_main": obsolete_main,
              "pinned_versions": pins,
              "main_packages": str(args.main_packages), "addon_packages": str(args.addon_packages)}
    args.plan.parent.mkdir(parents=True, exist_ok=True)
    if args.plan.exists():
        raise ValueError("plan already exists: " + str(args.plan))
    args.plan.write_text(json.dumps(report, indent=2) + "\n")
    print("Selected", len(selected), "packages; old main artifacts:", len(obsolete_main), "plan:", args.plan)


def stage(args):
    report = json.loads(args.plan.read_text())
    if report["schema"] != "ki2-curation-v1":
        raise ValueError("invalid curation plan")
    if args.output.exists():
        raise ValueError("stage target already exists: " + str(args.output))
    args.output.mkdir(parents=True)
    missing_iso = []
    for entry in report["selected"]:
        destination = args.output / entry["file"]
        if entry["source"] == "iso":
            local = args.main_packages / entry["file"]
            if local.is_file() and sha256(local) == entry["sha256"]:
                shutil.copy2(local, destination)
            else:
                missing_iso.append((entry, destination))
        else:
            source_dir = args.main_packages if entry["source"] == "main" else args.addon_packages
            source = source_dir / entry["file"]
            if not source.is_file():
                raise ValueError("selected package missing: " + str(source))
            shutil.copy2(source, destination)
    if missing_iso:
        command = ["xorriso", "-osirrox", "on", "-indev", str(args.iso)]
        for entry, destination in missing_iso:
            command.extend(["-extract", "/kiki/packages/x86_64/" + entry["file"], str(destination)])
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
    checksums = {}
    for entry in report["selected"]:
        path = args.output / entry["file"]
        actual = sha256(path)
        if entry["source"] == "iso" and actual != entry["sha256"]:
            raise ValueError("ISO package hash mismatch: " + entry["file"])
        checksums[entry["file"]] = actual
    print("Staged", len(checksums), "packages; extracted from ISO:", len(missing_iso),
          "total bytes:", sum((args.output / name).stat().st_size for name in checksums))


def archive(args):
    report = json.loads(args.plan.read_text())
    if report["schema"] != "ki2-curation-v1":
        raise ValueError("invalid curation plan")
    if args.archive_dir.exists():
        raise ValueError("archive target already exists: " + str(args.archive_dir))
    old = report["obsolete_main"]
    for name in old:
        if Path(name).name != name or not (args.main_packages / name).is_file():
            raise ValueError("obsolete package path is not safe: " + name)
    args.archive_dir.mkdir(parents=True)
    for name in old:
        (args.main_packages / name).rename(args.archive_dir / name)
    print("Removed", len(old), "old packages from the active directory; recoverable at", args.archive_dir)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "stage", "archive"))
    parser.add_argument("--main-packages", type=Path, required=True)
    parser.add_argument("--addon-packages", type=Path, required=True)
    parser.add_argument("--iso-index", type=Path)
    parser.add_argument("--iso-metadata", type=Path)
    parser.add_argument("--public-key", type=Path)
    parser.add_argument("--iso", type=Path)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--archive-dir", type=Path)
    args = parser.parse_args()
    if args.mode == "plan":
        if not all((args.iso_index, args.iso_metadata, args.public_key)):
            parser.error("plan requires --iso-index, --iso-metadata, and --public-key")
        make_plan(args)
    elif args.mode == "stage":
        if args.iso is None or args.output is None:
            parser.error("stage requires --iso and --output")
        stage(args)
    else:
        if args.archive_dir is None:
            parser.error("archive requires --archive-dir")
        archive(args)


if __name__ == "__main__":
    main()
