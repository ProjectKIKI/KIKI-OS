#!/usr/bin/env python3
"""Stage an isolated Rocky host-ABI Podman bootstrap for KIKI OS.

This is rootful-only and intentionally refuses to overwrite KIKI base files.
It is not a native Podman build or a substitute for a KIKI boot test.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess

import ki2graphics as graphics


BINARIES = [
    Path("/usr/bin/podman"),
    Path("/usr/lib/systemd/system-generators/podman-system-generator"),
    Path("/usr/libexec/podman/catatonit"),
    Path("/usr/libexec/podman/quadlet"),
    Path("/usr/libexec/podman/rootlessport"),
    Path("/usr/libexec/podman/netavark"),
    Path("/usr/libexec/podman/aardvark-dns"),
]
DATA = [
    Path("/usr/share/containers/containers.conf"),
    Path("/usr/share/containers/seccomp.json"),
    Path("/usr/share/containers/mounts.conf"),
    Path("/etc/containers/policy.json"),
    Path("/etc/containers/storage.conf"),
]
REQUIRED_PACKAGES = ["podman", "netavark", "aardvark-dns", "containers-common"]
PRIVATE_BIN = Path("usr/libexec/kiki-podman/bin")
PRIVATE_LIB = Path("usr/lib/kiki-podman/lib")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def same(left: Path, right: Path) -> bool:
    if left.is_symlink() or right.is_symlink():
        return left.is_symlink() and right.is_symlink() and os.readlink(left) == os.readlink(right)
    return left.is_file() and right.is_file() and sha256(left) == sha256(right)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-rootfs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    base = args.base_rootfs.resolve(strict=True)
    out = args.output.resolve()
    if out.exists():
        raise ValueError(f"output already exists; refusing overwrite: {out}")
    if not (base / "usr/share/kiki-installer-gtk/runtime-manifest.json").is_file():
        raise ValueError("requires the validated KIKI host-ABI base rootfs")
    versions = subprocess.check_output(
        ["rpm", "-q", "--qf", "%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n", *REQUIRED_PACKAGES],
        text=True,
    ).splitlines()
    if not any(value.startswith("podman-5.8.2-") for value in versions):
        raise ValueError("expected the reviewed Rocky 9 Podman 5.8.2 host package")
    host_libraries: set[Path] = set()
    for binary in BINARIES:
        if not binary.is_file():
            raise ValueError(f"missing Podman helper: {binary}")
    for file in DATA:
        if not file.is_file():
            raise ValueError(f"missing Podman configuration: {file}")
    out.mkdir(parents=True)
    for binary in BINARIES:
        target = out / PRIVATE_BIN / ("system-generator" if binary.name == "podman-system-generator" else binary.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(binary.resolve(), target)
        probe = subprocess.run(["ldd", str(binary)], capture_output=True, text=True)
        if "not a dynamic executable" not in (probe.stdout + probe.stderr):
            if probe.returncode != 0 or "not found" in probe.stdout:
                raise ValueError(f"unresolved ABI dependency: {binary}: {probe.stdout + probe.stderr}")
            for library in graphics.ldd_paths(binary):
                staged = out / PRIVATE_LIB / library.name
                staged.parent.mkdir(parents=True, exist_ok=True)
                actual = library.resolve()
                host_libraries.add(actual)
                if staged.exists() and not same(staged, actual):
                    raise ValueError(f"inconsistent private library: {library.name}")
                if not staged.exists():
                    shutil.copy2(actual, staged)
            wrapper = out / binary.relative_to("/")
            wrapper.parent.mkdir(parents=True, exist_ok=True)
            wrapper.write_text(
                "#!/usr/bin/bash\n"
                f"exec /lib64/ld-linux-x86-64.so.2 --library-path /{PRIVATE_LIB} /{PRIVATE_BIN}/{target.name} \"$@\"\n",
                encoding="utf-8",
            )
            wrapper.chmod(0o755)
        else:
            wrapper = out / binary.relative_to("/")
            graphics.copy_path(binary.resolve(), out, binary.relative_to("/"))
    for file in DATA:
        graphics.copy_path(file, out)
    # Do not inherit Rocky's insecureAcceptAnything default or Red Hat key paths.
    (out / "etc/containers/policy.json").write_text(
        json.dumps({"default": [{"type": "reject"}]}, indent=2) + "\n",
        encoding="utf-8",
    )
    # Keep registry policy explicit, rather than inheriting Rocky's short-name aliases.
    registry = out / "etc/containers/registries.conf"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text("unqualified-search-registries = []\n", encoding="utf-8")
    repo = Path(__file__).resolve().parents[1]
    shutil.copytree(repo / "distro/sources/kiki-podman", out, dirs_exist_ok=True, symlinks=True)
    (out / "usr/bin/kiki-podman-check").chmod(0o755)
    packages = []
    library_owners = subprocess.check_output(
        ["rpm", "-qf", "--qf", "%{NAME}\n", *map(str, sorted(host_libraries))], text=True
    ).splitlines()
    for package in sorted(set(REQUIRED_PACKAGES + library_owners)):
        result = subprocess.run(["rpm", "-ql", package], text=True, capture_output=True, check=True)
        for line in result.stdout.splitlines():
            source = Path(line)
            if line.startswith("/usr/share/licenses/") and source.is_file():
                relative = source.relative_to("/usr/share/licenses")
                graphics.copy_path(source, out,
                                   Path("usr/share/licenses/kiki-podman-bootstrap") / relative)
        packages.append(package)
    shared = []
    for path in sorted(out.rglob("*")):
        if path.is_dir() and not path.is_symlink():
            continue
        relative = path.relative_to(out)
        existing = base / relative
        if existing.exists() or existing.is_symlink():
            if relative.as_posix().startswith(("etc/containers/", "usr/lib/systemd/system-generators/")):
                raise ValueError(f"base configuration conflict: {relative}")
            # Identical files may be owned by the base. Private libraries never
            # overwrite system SONAMEs, but conflicts elsewhere are rejected.
            if same(path, existing):
                shared.append(str(relative))
            else:
                raise ValueError(f"base file conflict: {relative}")
            path.unlink()
        elif not path.is_symlink():
            path.chmod(stat.S_IMODE(path.stat().st_mode) & ~0o6000)
    manifest = {
        "schema": "kiki-podman-bootstrap-v1",
        "bootstrap": "Rocky-9-host-abi",
        "host_packages": versions,
        "copied_package_licenses": packages,
        "shared_base_paths": shared,
        "limitations": [
            "rootful-only; no setuid newuidmap/newgidmap",
            "not boot-tested on KIKI OS",
            "host ABI bootstrap, not native KIKI build",
            "private Rocky library closure; KIKI glibc compatibility requires target test",
        ],
        "files": {
            str(path.relative_to(out)): sha256(path)
            for path in out.rglob("*") if path.is_file() and not path.is_symlink()
        },
    }
    target = out / "usr/share/kiki-podman/bootstrap-manifest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Podman bootstrap: {out}; {len(manifest['files'])} files; {len(shared)} base paths shared")


if __name__ == "__main__":
    main()
