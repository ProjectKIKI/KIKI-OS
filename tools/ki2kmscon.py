#!/usr/bin/env python3
"""Build an isolated, pinned kmscon bootstrap runtime with Korean fonts.

Host ABI libraries remain private to kmscon; they must not replace OS libraries.
The source builds and output must be on a case-sensitive Linux filesystem.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

from ki2graphics import fetch, extract_tar, ldd_paths

SOURCES = {
    "libtsm": ("4.7.1", "40d7f11698f0ce87af8da67a3142ee9f02e2b5d914f8ad83aa080e052fe1ae2b"),
    "kmscon": ("10.0.3", "4a0552d3cd3ba16df4fcff61f2b1431650bcd9e7ecabc03625ce52345b9c95c5"),
}

NANUM_URL = "https://github.com/naver/nanumfont/releases/download/VER2.5/NanumGothicCoding-2.5.zip"
NANUM_SHA256 = "f4c9b1082cb36d793ccf75a331316c880ef9e4bc229408c22f9d2703b7619a3f"
NANUM_README_URL = "https://raw.githubusercontent.com/naver/nanumfont/master/README.md"
NANUM_README_SHA256 = "637918c95f747b1860f73cf7a759b0fd9bcde93c38fb4e5fa20ad2bf45395341"
OFL_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/nanumgothiccoding/OFL.txt"
OFL_SHA256 = "eeacf16032901d0ed0456876ec77b8f0fda6b3fecec7d972f8543eb602e6c30f"


def run(*args, env=None):
    subprocess.run(args, check=True, env=env)


def copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target, follow_symlinks=True)


def build(work, output):
    if output.exists():
        raise RuntimeError("Output already exists; choose a new output directory")
    work.mkdir(parents=True, exist_ok=True)
    prefix = work / "prefix"
    for name, (version, digest) in SOURCES.items():
        archive = work / (name + ".tar.gz")
        fetch(f"https://github.com/kmscon/{name}/archive/refs/tags/v{version}.tar.gz", digest, archive)
        source = work / (name + "-source")
        if not source.exists():
            extract_tar(archive, source)
        source = source / (name + "-" + version)
        builddir = work / (name + "-build")
        env = dict(os.environ, PKG_CONFIG_PATH=str(prefix / "lib/pkgconfig"))
        options = ["--prefix=/usr", "--libdir=lib", "--buildtype=release", "-Dtests=false"]
        if name == "libtsm":
            options[0] = "--prefix=" + str(prefix)
            options += ["-Dgtktsm=false"]
        else:
            options += ["--sysconfdir=/etc", "-Ddocs=disabled", "-Dlibseat=disabled",
                        "-Dvideo_drm2d=enabled", "-Dvideo_drm3d=disabled",
                        "-Drenderer_gltex=disabled", "-Dfont_freetype=enabled",
                        "-Dfont_pango=disabled", "-Dfont_unifont=disabled", "-Ddbus=disabled"]
        if not (builddir / "build.ninja").exists():
            run("meson", "setup", str(builddir), str(source), *options, env=env)
        run("meson", "compile", "-C", str(builddir), "-j2", env=env)
        if name == "kmscon":
            env["DESTDIR"] = str(work / "stage")
        run("meson", "install", "-C", str(builddir), env=env)

    private = output / "usr/lib/kiki-kmscon"
    stage = work / "stage"
    binary = stage / "usr/bin/kmscon"
    copy(binary, private / "kmscon")
    binaries = [binary, *sorted((stage / "usr/lib/kmscon").glob("*.so"))]
    host_files = set()
    for module in binaries[1:]:
        copy(module, output / "usr/lib/kmscon" / module.name)
    for item in binaries:
        for library in ldd_paths(item, library_path=prefix / "lib"):
            copy(library, private / "lib" / library.name)
            if not library.is_relative_to(work):
                host_files.add(str(library))
    # Keep the Noto fallback for glyphs missing from Nanum (notably Hanja).
    font = Path("/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc")
    copy(font, private / "fonts" / font.name)
    host_files.add(str(font))
    nanum_zip = work / "NanumGothicCoding-2.5.zip"
    fetch(NANUM_URL, NANUM_SHA256, nanum_zip)
    with zipfile.ZipFile(nanum_zip) as archive:
        for name in ("NanumGothicCoding.ttf", "NanumGothicCoding-Bold.ttf"):
            target = private / "fonts" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
    readme = work / "NanumGothicCoding-README.md"
    ofl = work / "NanumGothicCoding-OFL.txt"
    fetch(NANUM_README_URL, NANUM_README_SHA256, readme)
    fetch(OFL_URL, OFL_SHA256, ofl)
    copy(readme, output / "usr/share/licenses/kiki-kmscon/NanumGothicCoding-README.md")
    copy(ofl, output / "usr/share/licenses/kiki-kmscon/OFL-1.1.txt")
    shutil.copytree("/usr/share/X11/xkb", private / "xkb", symlinks=False)
    host_files.add("/usr/share/X11/xkb/rules/evdev")
    compose = Path("/usr/share/X11/locale/en_US.UTF-8/Compose")
    copy(compose, private / "Compose")
    host_files.add(str(compose))
    shutil.copytree(stage / "usr/share/terminfo", output / "usr/share/terminfo", dirs_exist_ok=True)

    repo = Path(__file__).resolve().parents[1]
    shutil.copytree(repo / "distro/sources/kiki-kmscon", output, dirs_exist_ok=True)
    (output / "usr/bin/kiki-kmscon").chmod(0o755)
    packages = set()
    for source in sorted(host_files):
        package = subprocess.check_output(["rpm", "-qf", "--qf", "%{NAME}", source], text=True).strip()
        packages.add(package)
    for package in sorted(packages):
        paths = subprocess.check_output(["rpm", "-ql", package], text=True).splitlines()
        for value in paths:
            path = Path(value)
            if value.startswith("/usr/share/licenses/") and path.is_file():
                copy(path, output / value.lstrip("/"))
    for name in SOURCES:
        source = work / (name + "-source") / (name + "-" + SOURCES[name][0])
        for path in source.glob("COPYING*"):
            copy(path, output / "usr/share/licenses" / name / path.name)
        for path in source.glob("LICENSE*"):
            if path.is_file():
                copy(path, output / "usr/share/licenses" / name / path.name)
            elif path.is_dir():
                shutil.copytree(path, output / "usr/share/licenses" / name / path.name, dirs_exist_ok=True)
    inventory = subprocess.check_output(["rpm", "-q", *sorted(packages)], text=True).splitlines()
    manifest = output / "usr/share/doc/kiki-kmscon/build.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"sources": SOURCES, "host_rpm_inventory": inventory,
                                   "runtime": "private host-ABI bootstrap"}, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.work.resolve(), args.output.resolve())
