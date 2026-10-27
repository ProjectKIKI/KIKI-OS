"""Create a fresh candidate from signed media with explicit package replacements."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import ki2build
import ki2media


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--package", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    baseline = args.baseline.resolve(strict=True)
    ki2media.verify_media(baseline, repo / "build/ki2/keys/stage3-v3-repo.ed25519.pub")
    replacements = {}
    for source in args.package:
        source = source.resolve(strict=True)
        manifest = ki2build.read_package_manifest(source)
        if manifest["name"] in replacements:
            raise ValueError("duplicate replacement")
        replacements[manifest["name"]] = (source, manifest)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    packages = out / "packages/x86_64"
    packages.mkdir(parents=True)
    manifests = {}
    for source in sorted((baseline / "kiki/packages/x86_64").glob("*.ki2")):
        manifest = ki2build.read_package_manifest(source)
        name = manifest["name"]
        if name in replacements:
            source, manifest = replacements.pop(name)
        target = packages / source.name
        shutil.copyfile(source, target)
        if ki2build.file_sha256(source) != ki2build.file_sha256(target):
            raise ValueError("package copy mismatch")
        manifests[name] = (target, manifest)
    if replacements:
        raise ValueError("replacement must name an existing baseline package")
    rootfs = out / "rootfs"
    rootfs.mkdir()
    subprocess.run(["tar", "-xzf", str(baseline / "kiki/rootfs.tar.gz"),
                    "--no-same-owner", "-C", str(rootfs)], check=True)
    state = json.loads((rootfs / "var/lib/ki2/installed.json").read_text())
    for source in args.package:
        ki2build.extract_package_rootfs(source.resolve(strict=True), rootfs)
    ki2build.write_rootfs_installed_state(rootfs, [manifests[n] for n in sorted(state["packages"])])
    (out / "candidate.json").write_text(json.dumps({
        "baseline": str(baseline),
        "replacements": [str(p) for p in args.package],
        "packages": [{"name": n, "file": path.name, "sha256": ki2build.file_sha256(path)}
                     for n, (path, _) in sorted(manifests.items())]}, indent=2) + "\n")
    print("Candidate packages:", len(manifests), flush=True)


if __name__ == "__main__":
    main()
