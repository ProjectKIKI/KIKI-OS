"""Build an opt-in X11 bootstrap payload without overwriting base graphics files."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import ki2graphics as graphics

BINARIES = ["Xvfb", "xinit", "xauth", "xterm", "xkbcomp", "xdpyinfo", "xwininfo", "xrandr"]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def same_file(left, right):
    if left.is_symlink() or right.is_symlink():
        return left.is_symlink() and right.is_symlink() and os.readlink(left) == os.readlink(right)
    return left.is_file() and right.is_file() and digest(left) == digest(right)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-rootfs", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    base = args.base_rootfs.resolve(strict=True)
    out = args.output.resolve()
    if not (base / "usr/share/kiki-installer-gtk/runtime-manifest.json").is_file():
        raise ValueError("requires the existing KIKI graphics bootstrap rootfs")
    out.mkdir(parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parents[1]
    for name in BINARIES:
        source = Path("/usr/bin") / name
        if not source.is_file():
            raise ValueError("missing host package for " + name)
        graphics.copy_path(source, out)
        result = subprocess.run(["ldd", str(source)], capture_output=True, text=True, check=True)
        if "not found" in result.stdout:
            raise ValueError("missing ABI dependency: " + name)
        graphics.copy_abi_closure(source, out)
    graphics.copy_path(Path("/usr/libexec/Xorg"), out)
    graphics.copy_abi_closure(Path("/usr/libexec/Xorg"), out)
    modules = Path("/usr/lib64/xorg/modules")
    graphics.copy_path(modules, out)
    for module in modules.rglob("*.so"):
        graphics.copy_abi_closure(module, out)
    for path in ["/usr/share/X11/xorg.conf.d", "/usr/share/X11/fonts", "/usr/share/X11/locale",
                 "/usr/share/X11/app-defaults/XTerm", "/usr/share/X11/app-defaults/XTerm-color"]:
        graphics.copy_path(Path(path), out)
    for path in Path("/usr/share/terminfo/x").glob("xterm*"):
        # Terminal descriptions are data, not an ELF ABI. Keep the native
        # ncurses package's descriptions instead of replacing them with RPM data.
        if not (base / path.relative_to("/")).exists():
            graphics.copy_path(path, out)
    # Preserve intermediate SONAME links (e.g. libXaw.so.7 -> libXaw7.so.7).
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
    packages = graphics.copy_rpm_licenses(out)
    for package in packages:
        for path in Path("/usr/share/doc", package).glob("COPYING*"):
            graphics.copy_path(path, out, Path("usr/share/licenses") / package / path.name)
    shutil.copytree(repo / "distro/sources/kiki-x11", out, dirs_exist_ok=True, symlinks=True)
    for name in ["Xorg", "kiki-startx", "kiki-x11-check"]:
        (out / "usr/bin" / name).chmod(0o755)
    graphics.relativize_runtime_links(out)
    shared = []
    for path in sorted(out.rglob("*")):
        if path.is_dir() and not path.is_symlink():
            continue
        relative = path.relative_to(out)
        existing = base / relative
        if existing.exists() or existing.is_symlink():
            if not same_file(path, existing):
                raise ValueError("base file conflict (refuse overwrite): " + str(relative))
            shared.append({"path": str(relative), "sha256": digest(existing) if not existing.is_symlink() else None,
                           "link": os.readlink(existing) if existing.is_symlink() else None})
            path.unlink()
        elif not path.is_symlink():
            path.chmod(stat.S_IMODE(path.stat().st_mode) & ~0o6000)
    versions = subprocess.check_output(["rpm", "-q", "--qf", "%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n",
                                        *packages], text=True).splitlines()
    manifest = {
        "schema": "kiki-x11-bootstrap-v1", "bootstrap": "Rocky-9-host-abi",
        "base_graphics_sha256": digest(base / "usr/share/kiki-installer-gtk/runtime-manifest.json"),
        "host_packages": versions, "shared_base_files": shared,
        "files": {str(f.relative_to(out)): digest(f) for f in out.rglob("*") if f.is_file() and not f.is_symlink()},
        "limitations": ["No desktop or display manager", "No Xwayland", "No setuid wrapper", "Opt-in local TTY session"],
    }
    dest = out / "usr/share/kiki-x11/runtime-manifest.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(manifest, indent=2) + "\n")
    print("X11 payload:", out, "files:", len(manifest["files"]), "shared:", len(shared))


if __name__ == "__main__":
    main()
