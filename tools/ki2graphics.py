#!/usr/bin/env python3
"""Build the host-bootstrapped GTK/Wayland installer runtime.

Stage 3 deliberately keeps the native KIKI package graph small.  This helper
pins and builds the kiosk compositor, compiles the GTK frontend, and copies the
host graphics ABI closure into one auditable package payload.  It is a
bootstrap boundary, not the long-term replacement for native GTK recipes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path


WLROOTS_VERSION = "0.16.2"
WLROOTS_URL = (
    "https://gitlab.freedesktop.org/wlroots/wlroots/-/releases/0.16.2/"
    "downloads/wlroots-0.16.2.tar.gz"
)
WLROOTS_SHA256 = "83e9a11605f23d4bf781ab1947089483d9ec3f7e9ba65398e0609593b77d44aa"
CAGE_VERSION = "0.1.5"
CAGE_URL = "https://github.com/cage-kiosk/cage/releases/download/v0.1.5/cage-0.1.5.tar.gz"
CAGE_SHA256 = "ece0312e559289df0238289ea6c60e9fed32d27fe3ae8a8f83eeff26ddc239e1"
SEATD_VERSION = "0.9.3"
SEATD_URL = f"https://git.sr.ht/~kennylevinsen/seatd/archive/{SEATD_VERSION}.tar.gz"
SEATD_SHA256 = "302564d54d8e28191fadfd734f2675ecb0c9e0615a58011b89ef15dfa4dbaa96"

CORE_GLIBC = {
    "ld-linux-x86-64.so.2",
    "libanl.so.1",
    "libc.so.6",
    "libdl.so.2",
    "libm.so.6",
    "libnss_compat.so.2",
    "libnss_dns.so.2",
    "libnss_files.so.2",
    "libnss_hesiod.so.2",
    "libpthread.so.0",
    "libresolv.so.2",
    "librt.so.1",
    "libthread_db.so.1",
    "libutil.so.1",
}


class GraphicsError(RuntimeError):
    pass


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, env=env, check=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_commands(names: list[str]) -> None:
    missing = [name for name in names if shutil.which(name) is None]
    if missing:
        raise GraphicsError("missing host commands: " + ", ".join(missing))


def require_pkgconfig(names: list[str]) -> None:
    missing = [name for name in names if subprocess.run(
        ["pkg-config", "--exists", name], check=False
    ).returncode != 0]
    if missing:
        raise GraphicsError(
            "missing host development packages for: " + ", ".join(missing)
        )


def fetch(url: str, expected: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        print(f"[download] {url}", flush=True)
        with urllib.request.urlopen(url) as response, destination.open("wb") as output:
            shutil.copyfileobj(response, output)
    actual = sha256(destination)
    if actual != expected:
        raise GraphicsError(
            f"source checksum mismatch: {destination} expected={expected} actual={actual}"
        )


def extract_tar(archive: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    with tarfile.open(archive, "r:gz") as bundle:
        root = destination.resolve()
        for member in bundle.getmembers():
            target = (destination / member.name).resolve()
            if target != root and root not in target.parents:
                raise GraphicsError(f"unsafe archive member: {member.name}")
        bundle.extractall(destination)


def copy_path(source: Path, rootfs: Path, destination: Path | None = None) -> None:
    if not source.exists() and not source.is_symlink():
        return
    rel = destination if destination is not None else Path(str(source).lstrip("/"))
    target = rootfs / rel
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True, symlinks=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        target.unlink()
    if source.is_symlink():
        target.symlink_to(os.readlink(source))
        resolved = source.resolve()
        sibling = target.parent / resolved.name
        if not sibling.exists():
            shutil.copy2(resolved, sibling)
    else:
        shutil.copy2(source, target)


def ldd_paths(binary: Path, *, library_path: Path | None = None) -> list[Path]:
    env = os.environ.copy()
    if library_path:
        env["LD_LIBRARY_PATH"] = str(library_path)
    result = subprocess.run(
        ["ldd", str(binary)], text=True, capture_output=True, check=False, env=env
    )
    if result.returncode != 0:
        raise GraphicsError(f"ldd failed for {binary}: {(result.stdout + result.stderr).strip()}")
    paths: set[Path] = set()
    for line in result.stdout.splitlines():
        match = re.search(r"(?:=>\s+)?(/[^\s]+)", line)
        if match:
            path = Path(match.group(1))
            if path.name not in CORE_GLIBC and not path.name.startswith("ld-linux-"):
                paths.add(path)
    return sorted(paths)


def copy_abi_closure(binary: Path, rootfs: Path, *, library_path: Path | None = None) -> None:
    for dependency in ldd_paths(binary, library_path=library_path):
        if library_path is not None and dependency.is_relative_to(library_path):
            copy_path(dependency, rootfs, Path("usr/lib64") / dependency.name)
        else:
            copy_path(dependency, rootfs)


def copy_rpm_licenses(rootfs: Path) -> list[str]:
    host_paths: list[str] = []
    for path in rootfs.rglob("*"):
        if path.is_dir():
            continue
        candidate = Path("/") / path.relative_to(rootfs)
        if candidate.exists() or candidate.is_symlink():
            host_paths.append(str(candidate))
    packages: set[str] = set()
    # Keep each invocation small enough for conservative ARG_MAX environments.
    for start in range(0, len(host_paths), 128):
        result = subprocess.run(
            ["rpm", "-qf", "--qf", "%{NAME}\\n", *host_paths[start : start + 128]],
            text=True,
            capture_output=True,
            check=False,
        )
        packages.update(
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip() and " " not in line.strip()
        )
    for package in sorted(packages):
        result = subprocess.run(["rpm", "-ql", package], text=True, capture_output=True, check=True)
        for line in result.stdout.splitlines():
            license_path = Path(line)
            if line.startswith("/usr/share/licenses/") and license_path.is_file():
                copy_path(license_path, rootfs)
    return sorted(packages)


def build_runtime(repo_root: Path, output: Path, sources: Path, work: Path, jobs: int) -> None:
    require_commands(["cc", "meson", "ninja", "pkg-config", "wayland-scanner"])
    require_pkgconfig([
        "gtk4", "libdrm", "libinput", "libseat", "wayland-client",
        "wayland-server", "wayland-protocols", "xkbcommon", "gbm", "egl", "glesv2",
    ])

    wlroots_archive = sources / f"wlroots-{WLROOTS_VERSION}.tar.gz"
    cage_archive = sources / f"cage-{CAGE_VERSION}.tar.gz"
    seatd_archive = sources / f"seatd-{SEATD_VERSION}.tar.gz"
    fetch(WLROOTS_URL, WLROOTS_SHA256, wlroots_archive)
    fetch(CAGE_URL, CAGE_SHA256, cage_archive)
    fetch(SEATD_URL, SEATD_SHA256, seatd_archive)

    if work.exists():
        shutil.rmtree(work)
    if output.exists():
        shutil.rmtree(output)
    work.mkdir(parents=True)
    output.mkdir(parents=True)

    extract_tar(wlroots_archive, work / "wlroots-source")
    extract_tar(cage_archive, work / "cage-source")
    extract_tar(seatd_archive, work / "seatd-source")
    wlroots_source = next((work / "wlroots-source").iterdir())
    cage_source = next((work / "cage-source").iterdir())
    seatd_source = next((work / "seatd-source").iterdir())
    stage = work / "stage"
    seatd_build = work / "seatd-build"
    wlroots_build = work / "wlroots-build"
    cage_build = work / "cage-build"

    # The distribution libseat package is built without its embedded backend.
    # PID 1 in the installer initramfs has neither logind nor a seatd daemon, so
    # forcing LIBSEAT_BACKEND=builtin used to make Cage exit immediately.  Build
    # the small, self-contained upstream backend into this bootstrap boundary.
    run([
        "meson", "setup", str(seatd_build), str(seatd_source),
        "--prefix=/usr", "--libdir=lib64", "--buildtype=release",
        "-Dlibseat-logind=disabled", "-Dlibseat-seatd=disabled",
        "-Dlibseat-builtin=enabled", "-Dserver=disabled",
        "-Dexamples=disabled", "-Dman-pages=disabled",
    ])
    run(["meson", "compile", "-C", str(seatd_build), "-j", str(jobs)])
    run(["meson", "install", "-C", str(seatd_build), "--destdir", str(stage)])

    graphics_env = os.environ.copy()
    graphics_env["PKG_CONFIG_PATH"] = str(stage / "usr/lib64/pkgconfig")
    graphics_env["CFLAGS"] = f"-I{stage / 'usr/include'}"
    graphics_env["LDFLAGS"] = (
        f"-L{stage / 'usr/lib64'} -Wl,-rpath-link,{stage / 'usr/lib64'}"
    )

    run([
        "meson", "setup", str(wlroots_build), str(wlroots_source),
        "--prefix=/usr", "--libdir=lib64", "--buildtype=release",
        "-Dexamples=false", "-Dxwayland=disabled", "-Dbackends=drm,libinput",
        "-Drenderers=gles2", "-Dallocators=gbm",
    ], env=graphics_env)
    run(["meson", "compile", "-C", str(wlroots_build), "-j", str(jobs)], env=graphics_env)
    run(["meson", "install", "-C", str(wlroots_build), "--destdir", str(stage)], env=graphics_env)

    cage_env = graphics_env.copy()
    run([
        "meson", "setup", str(cage_build), str(cage_source),
        "--prefix=/usr", "--libdir=lib64", "--buildtype=release",
        "-Dxwayland=false", "-Dman-pages=disabled",
    ], env=cage_env)
    run(["meson", "compile", "-C", str(cage_build), "-j", str(jobs)], env=cage_env)
    run(["meson", "install", "-C", str(cage_build), "--destdir", str(stage)], env=cage_env)

    gtk_cflags = subprocess.check_output(["pkg-config", "--cflags", "gtk4"], text=True).split()
    gtk_libs = subprocess.check_output(["pkg-config", "--libs", "gtk4"], text=True).split()
    gtk_binary = stage / "usr/bin/kiki-installer-gtk"
    gtk_binary.parent.mkdir(parents=True, exist_ok=True)
    run([
        "cc", "-O2", "-pipe", "-Wall", "-Wextra", "-Werror", *gtk_cflags,
        "-o", str(gtk_binary), str(repo_root / "cmd/kiki-installer-gtk/main.c"), *gtk_libs,
    ])
    copy_path(
        repo_root / "cmd/kiki-installer-gtk/style.css",
        stage,
        Path("usr/share/kiki-installer-gtk/style.css"),
    )

    copy_path(stage / "usr/bin/cage", output, Path("usr/bin/cage"))
    copy_path(gtk_binary, output, Path("usr/bin/kiki-installer-gtk"))
    copy_path(
        stage / "usr/share/kiki-installer-gtk/style.css",
        output,
        Path("usr/share/kiki-installer-gtk/style.css"),
    )
    for library in sorted((stage / "usr/lib64").glob("libwlroots.so*")):
        copy_path(library, output, Path("usr/lib64") / library.name)
    for library in sorted((stage / "usr/lib64").glob("libseat.so*")):
        copy_path(library, output, Path("usr/lib64") / library.name)

    libdir = stage / "usr/lib64"
    copy_abi_closure(stage / "usr/bin/cage", output, library_path=libdir)
    copy_abi_closure(gtk_binary, output)
    for library in sorted(libdir.glob("libwlroots.so*")):
        if library.is_file():
            copy_abi_closure(library, output)

    # Runtime-loaded graphics modules are not visible to ldd on the executables.
    for pattern in (
        "/usr/lib64/dri/*_dri.so", "/usr/lib64/libEGL_mesa.so*",
        "/usr/lib64/libgbm.so*", "/usr/lib64/libGLESv2.so*",
    ):
        for module in sorted(Path("/").glob(pattern.lstrip("/"))):
            copy_path(module, output)
            if module.is_file():
                copy_abi_closure(module, output)

    for asset in (
        Path("/usr/share/glvnd/egl_vendor.d"),
        Path("/usr/share/X11/xkb"),
        Path("/usr/share/glib-2.0/schemas/gschemas.compiled"),
        Path("/usr/lib64/gdk-pixbuf-2.0/2.10.0/loaders"),
        Path("/usr/lib64/gdk-pixbuf-2.0/2.10.0/loaders.cache"),
        Path("/etc/fonts"),
        Path("/usr/share/fontconfig"),
        Path("/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc"),
        Path("/usr/lib/udev"),
    ):
        copy_path(asset, output)

    # libinput relies on udev's ID_INPUT tags.  mdev only creates device nodes,
    # so ship the small udev manager/client pair and run them before Cage.
    for udev_binary in (
        Path("/usr/lib/systemd/systemd-udevd"),
        Path("/usr/bin/udevadm"),
    ):
        copy_path(udev_binary, output)
        copy_abi_closure(udev_binary, output)

    license_dir = output / "usr/share/licenses/kiki-installer-gtk"
    license_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cage_source / "LICENSE", license_dir / "Cage-LICENSE")
    shutil.copy2(wlroots_source / "LICENSE", license_dir / "wlroots-LICENSE")
    shutil.copy2(seatd_source / "LICENSE", license_dir / "seatd-LICENSE")
    runtime_packages = copy_rpm_licenses(output)

    # The pixbuf loader modules also need their private ABI closure.
    loader_dir = Path("/usr/lib64/gdk-pixbuf-2.0/2.10.0/loaders")
    if loader_dir.is_dir():
        for loader in loader_dir.glob("*.so"):
            copy_abi_closure(loader, output)

    # A transitive host module may have copied the distribution libseat into
    # /lib64 after the custom copy above.  The dynamic loader searches /lib64
    # first, so make both standard locations resolve to the builtin-enabled ABI.
    for library in sorted((stage / "usr/lib64").glob("libseat.so*")):
        copy_path(library, output, Path("lib64") / library.name)

    manifest_dir = output / "usr/share/kiki-installer-gtk"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    files = [path for path in output.rglob("*") if path.is_file() and not path.is_symlink()]
    manifest = {
        "schema": "kiki-graphics-runtime-v1",
        "bootstrap": "host-abi",
        "cage": {"version": CAGE_VERSION, "url": CAGE_URL, "sha256": CAGE_SHA256},
        "wlroots": {"version": WLROOTS_VERSION, "url": WLROOTS_URL, "sha256": WLROOTS_SHA256},
        "seatd": {
            "version": SEATD_VERSION,
            "url": SEATD_URL,
            "sha256": SEATD_SHA256,
            "builtin_backend": True,
        },
        "gtk": subprocess.check_output(["pkg-config", "--modversion", "gtk4"], text=True).strip(),
        "font": "NotoSansCJK-Regular.ttc (OFL-1.1)",
        "host_runtime_packages": runtime_packages,
        "licenses": "/usr/share/licenses",
        "files": len(files),
        "bytes": sum(path.stat().st_size for path in files),
    }
    (manifest_dir / "runtime-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"[graphics] prepared {manifest['files']} files ({manifest['bytes']} bytes): {output}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("command", choices=("doctor", "prepare"))
    result.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    result.add_argument("--output", type=Path)
    result.add_argument("--sources", type=Path)
    result.add_argument("--work", type=Path)
    result.add_argument("--jobs", type=int, default=max(1, min(4, os.cpu_count() or 1)))
    return result


def main() -> int:
    args = parser().parse_args()
    repo_root = args.repo_root.resolve()
    output = (args.output or repo_root / "build/ki2/host-graphics/rootfs").resolve()
    sources = (args.sources or repo_root / "dist/sources").resolve()
    # Meson creates and removes thousands of tiny files.  Keep that transient
    # tree on the native Linux filesystem; only the final rootfs is persisted.
    work = (args.work or Path("/tmp/kiki-graphics-bootstrap-work")).resolve()
    try:
        require_commands(["cc", "meson", "ninja", "pkg-config", "wayland-scanner"])
        require_pkgconfig(["gtk4", "libdrm", "libinput", "libseat", "wayland-server", "xkbcommon", "gbm"])
        font = Path("/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc")
        if not font.is_file():
            raise GraphicsError(f"Korean installer font is missing: {font}")
        if args.command == "doctor":
            print("graphics bootstrap dependencies: OK")
            return 0
        build_runtime(repo_root, output, sources, work, max(1, args.jobs))
        return 0
    except (GraphicsError, OSError, subprocess.CalledProcessError) as exc:
        print(f"ki2graphics: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
