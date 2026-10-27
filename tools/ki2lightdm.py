#!/usr/bin/env python3
"""Create an opt-in LightDM/GTK3 greeter payload against the existing X11 bootstrap."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess

import ki2graphics as graphics
from ki2x11 import same_file


BINARIES = (
    Path("/usr/sbin/lightdm"),
    Path("/usr/sbin/lightdm-gtk-greeter"),
    Path("/usr/bin/dm-tool"),
    Path("/usr/libexec/accounts-daemon"),
)
DATA = (
    Path("/usr/lib/tmpfiles.d/lightdm.conf"),
    Path("/usr/share/xgreeters/lightdm-gtk-greeter.desktop"),
    Path("/usr/share/dbus-1/system.d/org.freedesktop.DisplayManager.conf"),
    Path("/etc/dbus-1/system.d/org.freedesktop.Accounts.conf"),
    Path("/usr/lib/systemd/system/accounts-daemon.service"),
    Path("/usr/share/dbus-1/system-services/org.freedesktop.Accounts.service"),
    Path("/usr/share/icons/Adwaita/index.theme"),
    Path("/usr/share/themes/Adwaita/gtk-3.0"),
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy_elf(path, out):
    if not path.is_file():
        raise ValueError("missing host LightDM component: " + str(path))
    graphics.copy_path(path, out)
    for dependency in graphics.ldd_paths(path):
        # KIKI's native linux-pam package provides the target ABI and its
        # modules in /usr/lib/security. Do not silently mix host PAM into it.
        if dependency.name.startswith(("libpam.so", "libpam_misc.so")):
            continue
        graphics.copy_path(dependency, out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-rootfs", type=Path, required=True)
    parser.add_argument("--x11-rootfs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    base = args.base_rootfs.resolve(strict=True)
    x11 = args.x11_rootfs.resolve(strict=True)
    out = args.output.resolve()
    graphics_manifest = base / "usr/share/kiki-installer-gtk/runtime-manifest.json"
    x11_manifest = x11 / "usr/share/kiki-x11/runtime-manifest.json"
    if not graphics_manifest.is_file() or not x11_manifest.is_file():
        raise ValueError("requires the existing KIKI graphics and X11 bootstrap rootfs")
    x11_metadata = json.loads(x11_manifest.read_text())
    if x11_metadata["base_graphics_sha256"] != digest(graphics_manifest):
        raise ValueError("X11 package does not match the graphics rootfs")
    for package in ("lightdm", "lightdm-gtk", "lightdm-gobject", "accountsservice"):
        subprocess.run(["rpm", "-q", package], check=True, stdout=subprocess.DEVNULL)
    out.mkdir(parents=True, exist_ok=False)
    for binary in BINARIES:
        copy_elf(binary, out)
    library = Path("/usr/lib64/liblightdm-gobject-1.so.0")
    copy_elf(library.resolve(), out)
    graphics.copy_path(library, out)
    for path in DATA:
        if not path.exists():
            raise ValueError("missing host LightDM data: " + str(path))
        graphics.copy_path(path, out)
    # The r17 graphics payload already supplies the shared GLib schema cache.
    # Add only GTK3-specific XML; the opt-in enable command recompiles it.
    for schema in Path("/usr/share/glib-2.0/schemas").glob("org.gtk.*.xml"):
        graphics.copy_path(schema, out)
    for module in Path("/usr/lib64/gtk-3.0").rglob("*.so"):
        copy_elf(module, out)
    for package in ("lightdm", "lightdm-gtk"):
        for name in ("/usr/share/locale/ko/LC_MESSAGES/" + package + ".mo",):
            graphics.copy_path(Path(name), out)
    repo = Path(__file__).resolve().parents[1]
    shutil.copytree(repo / "distro/sources/kiki-lightdm", out, dirs_exist_ok=True, symlinks=True)
    for executable in ("kiki-lightdm-enable", "kiki-lightdm-session"):
        (out / "usr/bin" / executable).chmod(0o755)
    # Preserve every intermediate SONAME link and make links safe for the KI2
    # package extractor, which rejects absolute links.
    for link in list(out.rglob("*")):
        if not link.is_symlink():
            continue
        source = Path("/") / link.relative_to(out)
        seen = set()
        while source.is_symlink() and source not in seen:
            seen.add(source)
            target = Path(os.readlink(source))
            source = target if target.is_absolute() else source.parent / target
            graphics.copy_path(source, out)
    graphics.relativize_runtime_links(out)
    shared = []
    for path in sorted(out.rglob("*")):
        if path.is_dir() and not path.is_symlink():
            continue
        relative = path.relative_to(out)
        existing = next((root / relative for root in (base, x11)
                         if (root / relative).exists() or (root / relative).is_symlink()), None)
        if existing is not None:
            if not same_file(path, existing):
                raise ValueError("base/X11 file conflict (refuse overwrite): " + str(relative))
            shared.append(str(relative))
            path.unlink()
        elif not path.is_symlink():
            path.chmod(stat.S_IMODE(path.stat().st_mode) & ~0o6000)
    packages = graphics.copy_rpm_licenses(out)
    versions = subprocess.check_output(
        ["rpm", "-q", "--qf", "%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\\n", *packages], text=True
    ).splitlines()
    manifest = {
        "schema": "kiki-lightdm-bootstrap-v1", "bootstrap": "Rocky-9-host-abi",
        "base_graphics_sha256": digest(graphics_manifest), "x11_sha256": digest(x11_manifest),
        "host_packages": versions, "shared_base_files": shared,
        "limitations": ["Opt-in; default target unchanged", "GTK3 host ABI bootstrap",
                        "Requires native KIKI linux-pam", "Hyper-V VT/login not yet tested"],
        "files": {str(path.relative_to(out)): digest(path) for path in out.rglob("*")
                  if path.is_file() and not path.is_symlink()},
    }
    destination = out / "usr/share/kiki-lightdm/runtime-manifest.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(manifest, indent=2) + "\n")
    print("LightDM payload:", out, "files:", len(manifest["files"]), "shared:", len(shared))


if __name__ == "__main__":
    main()
