#!/usr/bin/env python3
"""Recipe-driven build orchestration for the early KIKI/ki2 distribution.

This is intentionally small. It does not try to be Yocto, Buildroot, or Nix.
It gives KIKI a reproducible spine:

  recipe catalog -> dependency plan -> cached build key -> .ki2 packages
  -> repository index -> rootfs assembly

The real compilation commands live in recipes. The orchestrator decides what
needs to run, keeps package artifacts, and can dry-run every destructive step.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.9-3.10 on common builder distros.
    import tomli as tomllib  # type: ignore[no-redef]


PIN_PLACEHOLDERS = {"", "TODO", "UNPINNED", "REPLACE_ME"}
DEFAULT_TOOLCHAIN_ID = "host-bootstrap-v0"
UTC = dt.timezone.utc


class Ki2Error(RuntimeError):
    pass


@dataclass(frozen=True)
class Recipe:
    name: str
    version: str
    release: str
    summary: str
    license: str
    tier: str
    architectures: tuple[str, ...]
    source: dict[str, Any]
    dependencies: dict[str, list[str]]
    build: dict[str, Any]
    origin: Path
    digest: str

    @property
    def package_id(self) -> str:
        return f"{self.name}-{self.version}-{self.release}"

    def supports_arch(self, arch: str) -> bool:
        return "all" in self.architectures or arch in self.architectures


@dataclass
class BuildContext:
    repo_root: Path
    recipe_dir: Path
    build_dir: Path
    packages_dir: Path
    repo_dir: Path
    source_cache: Path
    rootfs_dir: Path | None
    arch: str
    jobs: int
    toolchain_id: str
    dry_run: bool
    allow_unpinned: bool
    verbose: bool


@dataclass
class BuildRecord:
    key: str
    output: str
    built_at: str
    recipe_digest: str
    dependencies: dict[str, str] = field(default_factory=dict)


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def stable_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_dependencies(raw: dict[str, Any], origin: Path, name: str) -> dict[str, list[str]]:
    source = raw.get("dependencies", {})
    if not isinstance(source, dict):
        raise Ki2Error(f"{origin}: {name} dependencies must be a table")

    dependencies: dict[str, list[str]] = {}
    for group in ("build", "runtime"):
        values = source.get(group, [])
        if not isinstance(values, list):
            raise Ki2Error(f"{origin}: {name} dependencies.{group} must be a list")

        seen: set[str] = set()
        normalized: list[str] = []
        for value in values:
            if not isinstance(value, str):
                raise Ki2Error(f"{origin}: {name} dependencies.{group} entries must be strings")
            dep = value.strip()
            if not dep or dep in seen:
                continue
            if dep == name:
                raise Ki2Error(f"{origin}: {name} cannot depend on itself")
            seen.add(dep)
            normalized.append(dep)
        dependencies[group] = normalized
    return dependencies


def normalize_recipe(raw: dict[str, Any], origin: Path) -> Recipe:
    required = ["name", "version", "summary", "license"]
    missing = [key for key in required if not raw.get(key)]
    if missing:
        raise Ki2Error(f"{origin}: recipe missing required field(s): {', '.join(missing)}")

    release = str(raw.get("release", "1"))
    architectures = tuple(raw.get("architectures", ["x86_64"]))
    if not architectures:
        raise Ki2Error(f"{origin}: recipe {raw['name']} has no architectures")

    dependencies = normalize_dependencies(raw, origin, raw["name"])

    build = raw.get("build", {})
    build.setdefault("system", "gnu")
    source = raw.get("source", {"type": "url"})
    source.setdefault("type", "url")

    digest_input = {
        "name": raw["name"],
        "version": str(raw["version"]),
        "release": release,
        "summary": raw["summary"],
        "license": raw["license"],
        "tier": raw.get("tier", "base"),
        "architectures": list(architectures),
        "source": source,
        "dependencies": dependencies,
        "build": build,
    }

    return Recipe(
        name=raw["name"],
        version=str(raw["version"]),
        release=release,
        summary=raw["summary"],
        license=raw["license"],
        tier=raw.get("tier", "base"),
        architectures=architectures,
        source=source,
        dependencies=dependencies,
        build=build,
        origin=origin,
        digest=stable_hash(digest_input),
    )


def load_recipes(recipe_dir: Path) -> dict[str, Recipe]:
    recipes: dict[str, Recipe] = {}
    if not recipe_dir.exists():
        raise Ki2Error(f"recipe directory not found: {recipe_dir}")

    for path in sorted(recipe_dir.rglob("*.toml")):
        data = read_toml(path)
        raw_recipes: list[dict[str, Any]]
        if "recipe" in data:
            raw_recipes = data["recipe"]
        elif "package" in data:
            raw_recipes = [data["package"]]
        else:
            raise Ki2Error(f"{path}: expected [[recipe]] or [package]")

        for raw in raw_recipes:
            recipe = normalize_recipe(raw, path)
            if recipe.name in recipes:
                raise Ki2Error(
                    f"duplicate recipe {recipe.name!r}: {recipes[recipe.name].origin} and {path}"
                )
            recipes[recipe.name] = recipe
    return recipes


def load_profile(path: Path) -> dict[str, Any]:
    data = read_toml(path)
    if "profile" not in data:
        raise Ki2Error(f"{path}: expected [profile]")
    profile = data["profile"]
    if not profile.get("name"):
        raise Ki2Error(f"{path}: profile.name is required")
    if not profile.get("packages"):
        raise Ki2Error(f"{path}: profile.packages is required")
    return profile


def validate_recipes(
    recipes: dict[str, Recipe],
    arch: str,
    profile: dict[str, Any] | None,
    max_packages: int | None,
) -> list[str]:
    warnings: list[str] = []
    if max_packages is not None and len(recipes) > max_packages:
        raise Ki2Error(f"recipe catalog has {len(recipes)} packages; limit is {max_packages}")

    for recipe in recipes.values():
        if not recipe.supports_arch(arch):
            warnings.append(f"{recipe.name}: does not support arch {arch}")
        for group, deps in recipe.dependencies.items():
            for dep in deps:
                if dep not in recipes:
                    raise Ki2Error(f"{recipe.name}: unknown {group} dependency {dep!r}")
        if recipe.source.get("type") == "url":
            sha = str(recipe.source.get("sha256", ""))
            if sha in PIN_PLACEHOLDERS:
                warnings.append(f"{recipe.name}: source sha256 is not pinned yet")

    if profile:
        for package in profile["packages"]:
            if package not in recipes:
                raise Ki2Error(f"profile {profile['name']}: unknown package {package!r}")
    return warnings


def dependency_closure(
    recipes: dict[str, Recipe],
    roots: list[str],
    arch: str,
    include_build_deps: bool,
) -> list[str]:
    seen: set[str] = set()
    visiting: set[str] = set()
    ordered: list[str] = []

    def visit(name: str) -> None:
        if name in seen:
            return
        if name in visiting:
            raise Ki2Error(f"dependency cycle includes {name}")
        if name not in recipes:
            raise Ki2Error(f"unknown package {name!r}")
        recipe = recipes[name]
        if not recipe.supports_arch(arch):
            raise Ki2Error(f"{name} does not support architecture {arch}")

        visiting.add(name)
        deps = list(recipe.dependencies.get("runtime", []))
        if include_build_deps:
            deps.extend(recipe.dependencies.get("build", []))
        for dep in deps:
            visit(dep)
        visiting.remove(name)
        seen.add(name)
        ordered.append(name)

    for root in roots:
        visit(root)
    return ordered


def state_path(ctx: BuildContext) -> Path:
    return ctx.build_dir / ctx.arch / "build-state.json"


def load_state(ctx: BuildContext) -> dict[str, BuildRecord]:
    path = state_path(ctx)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {name: BuildRecord(**record) for name, record in data.items()}


def save_state(ctx: BuildContext, state: dict[str, BuildRecord]) -> None:
    path = state_path(ctx)
    path.parent.mkdir(parents=True, exist_ok=True)
    serializable = {name: record.__dict__ for name, record in sorted(state.items())}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(serializable, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def build_key(recipe: Recipe, ctx: BuildContext, dep_keys: dict[str, str]) -> str:
    return stable_hash(
        {
            "schema": "ki2-build-key-v1",
            "recipe": recipe.digest,
            "arch": ctx.arch,
            "toolchain": ctx.toolchain_id,
            "deps": dep_keys,
        }
    )


def package_filename(recipe: Recipe, arch: str) -> str:
    return f"{recipe.name}-{recipe.version}-{recipe.release}.{arch}.ki2"


def package_path(ctx: BuildContext, recipe: Recipe) -> Path:
    return ctx.packages_dir / ctx.arch / package_filename(recipe, ctx.arch)


def sysroot_path(ctx: BuildContext) -> Path:
    return ctx.build_dir / ctx.arch / "sysroot"


def dependency_names(recipe: Recipe) -> list[str]:
    return sorted(set(recipe.dependencies.get("runtime", []) + recipe.dependencies.get("build", [])))


def record_output_path(ctx: BuildContext, record: BuildRecord) -> Path:
    path = Path(record.output)
    return path if path.is_absolute() else ctx.repo_root / path


def make_build_record(
    ctx: BuildContext,
    recipe: Recipe,
    output: Path,
    key: str,
    dep_keys: dict[str, str],
) -> BuildRecord:
    output_ref = output.relative_to(ctx.repo_root) if output.is_relative_to(ctx.repo_root) else output
    return BuildRecord(
        key=key,
        output=str(output_ref),
        built_at=dt.datetime.now(UTC).isoformat(),
        recipe_digest=recipe.digest,
        dependencies=dep_keys,
    )


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def command_env(ctx: BuildContext, recipe: Recipe, work: Path, source: Path, build: Path, dest: Path) -> dict[str, str]:
    target = target_triple(ctx.arch)
    sysroot = sysroot_path(ctx)
    return {
        "KI2_ARCH": ctx.arch,
        "KI2_BUILD_TRIPLE": "x86_64-kiki-linux-gnu",
        "KI2_TARGET_TRIPLE": target,
        "KI2_PACKAGE": recipe.name,
        "KI2_VERSION": recipe.version,
        "KI2_RELEASE": recipe.release,
        "KI2_WORK": str(work),
        "KI2_SOURCE_DIR": str(source),
        "KI2_BUILD_DIR": str(build),
        "KI2_DESTDIR": str(dest),
        "KI2_SYSROOT": str(sysroot),
        "KI2_JOBS": str(ctx.jobs),
        "KI2_PREFIX": "/usr",
        "PKG_CONFIG_SYSROOT_DIR": str(sysroot),
        "PKG_CONFIG_LIBDIR": os.pathsep.join(
            [
                str(sysroot / "usr" / "lib" / "pkgconfig"),
                str(sysroot / "usr" / "lib64" / "pkgconfig"),
                str(sysroot / "usr" / "share" / "pkgconfig"),
                str(sysroot / "lib" / "pkgconfig"),
                str(sysroot / "lib64" / "pkgconfig"),
            ]
        ),
    }


def target_triple(arch: str) -> str:
    mapping = {
        "x86_64": "x86_64-kiki-linux-gnu",
        "aarch64": "aarch64-kiki-linux-gnu",
    }
    return mapping.get(arch, f"{arch}-kiki-linux-gnu")


def format_command(command: str, env: dict[str, str]) -> str:
    result = command
    for key, value in env.items():
        result = result.replace("${" + key + "}", value)
    return result


def default_commands(recipe: Recipe, env: dict[str, str]) -> list[str]:
    system = recipe.build.get("system", "gnu")
    options = " ".join(recipe.build.get("configure_options", []))
    source = shell_quote(env["KI2_SOURCE_DIR"])
    build = shell_quote(env["KI2_BUILD_DIR"])
    dest = shell_quote(env["KI2_DESTDIR"])
    jobs = shell_quote(env["KI2_JOBS"])

    if system == "gnu":
        return [
            f"cd {source} && ./configure --prefix=/usr {options}".strip(),
            f"make -C {source} -j{jobs}",
            f"make -C {source} DESTDIR={dest} install",
        ]
    if system == "meson":
        return [
            f"meson setup {build}/meson {source} --prefix=/usr --libdir=lib --buildtype=release {options}".strip(),
            f"ninja -C {build}/meson -j{jobs}",
            f"DESTDIR={dest} ninja -C {build}/meson install",
        ]
    if system == "cmake":
        return [
            f"cmake -S {source} -B {build}/cmake -DCMAKE_INSTALL_PREFIX=/usr {options}".strip(),
            f"cmake --build {build}/cmake --parallel {jobs}",
            f"DESTDIR={dest} cmake --install {build}/cmake",
        ]
    if system == "make":
        return [
            f"make -C {source} -j{jobs}",
            f"make -C {source} DESTDIR={dest} PREFIX=/usr install",
        ]
    if system == "kernel":
        commands = [
            f"make -C {source} O={build}/kernel defconfig",
            f"make -C {source} O={build}/kernel -j{jobs}",
            f"mkdir -p {dest}/boot && cp {build}/kernel/arch/x86/boot/bzImage {dest}/boot/vmlinuz-kiki",
            f"make -C {source} O={build}/kernel INSTALL_MOD_PATH={dest} modules_install",
        ]
        if recipe.build.get("strip_module_build_links", False):
            commands.append(f"find {dest}/lib/modules -type l \\( -name build -o -name source \\) -delete")
        return commands
    if system in {"copy", "virtual"}:
        return []
    raise Ki2Error(f"{recipe.name}: unknown build.system {system!r}")


def recipe_commands(recipe: Recipe, env: dict[str, str]) -> list[str]:
    explicit: list[str] = []
    for key in ("prepare", "configure", "compile", "install"):
        values = recipe.build.get(key)
        if values:
            explicit.extend(values)
    if explicit:
        return [format_command(command, env) for command in explicit]
    return default_commands(recipe, env)


def fetch_source(ctx: BuildContext, recipe: Recipe, work: Path) -> Path:
    source = recipe.source
    source_type = source.get("type", "url")
    source_dir = work / "source"

    if source_type == "virtual":
        source_dir.mkdir(parents=True, exist_ok=True)
        return source_dir

    if source_type == "local":
        rel = Path(source["path"])
        local = rel if rel.is_absolute() else ctx.repo_root / rel
        if not local.exists():
            raise Ki2Error(f"{recipe.name}: local source path not found: {local}")
        if ctx.dry_run:
            print(f"[source] {recipe.name}: {local}")
            return source_dir
        if source_dir.exists():
            shutil.rmtree(source_dir)
        if local.is_dir():
            shutil.copytree(local, source_dir)
        else:
            source_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(local, source_dir / local.name)
        return source_dir

    if source_type != "url":
        raise Ki2Error(f"{recipe.name}: unsupported source.type {source_type!r}")

    url = source.get("url")
    if not url:
        raise Ki2Error(f"{recipe.name}: source.url is required")
    sha = str(source.get("sha256", ""))
    filename = source.get("file") or Path(url).name
    ctx.source_cache.mkdir(parents=True, exist_ok=True)
    archive = ctx.source_cache / filename

    if ctx.dry_run:
        print(f"[fetch] {recipe.name}: {url} -> {archive}")
        return source_dir

    if not archive.exists():
        print(f"[fetch] {recipe.name}: {url}")
        urllib.request.urlretrieve(url, archive)

    actual_sha = file_sha256(archive)
    if sha in PIN_PLACEHOLDERS:
        if not ctx.allow_unpinned:
            raise Ki2Error(
                f"{recipe.name}: source sha256 is not pinned; rerun with --allow-unpinned "
                f"after reviewing {actual_sha}"
            )
        print(f"[warn] {recipe.name}: using unpinned source sha256 {actual_sha}")
    elif actual_sha != sha:
        raise Ki2Error(f"{recipe.name}: sha256 mismatch: got {actual_sha}, want {sha}")

    if tarfile.is_tarfile(archive):
        extract_archive(archive, source_dir)
    else:
        if source_dir.exists():
            shutil.rmtree(source_dir)
        source_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(archive, source_dir / archive.name)
    children = [child for child in source_dir.iterdir()]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return source_dir


def extract_archive(archive: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    if tarfile.is_tarfile(archive):
        with tarfile.open(archive) as tar:
            tar.extractall(target, filter="data")
        return
    raise Ki2Error(f"unsupported archive format: {archive}")


def run_shell(command: str, env: dict[str, str], cwd: Path, dry_run: bool) -> None:
    print("+ " + command)
    if dry_run:
        return
    merged_env = os.environ.copy()
    merged_env.update(env)
    subprocess.run(command, shell=True, cwd=cwd, env=merged_env, check=True)


def copy_source_to_dest(source_dir: Path, destdir: Path) -> None:
    for child in source_dir.iterdir():
        target = destdir / child.name
        if child.is_dir():
            shutil.copytree(child, target, dirs_exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, target)


def create_package(ctx: BuildContext, recipe: Recipe, destdir: Path, output: Path, key: str, dep_keys: dict[str, str]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    dependencies = {
        "build": recipe.dependencies.get("build", []),
        "runtime": recipe.dependencies.get("runtime", []),
    }
    manifest = {
        "schema": "ki2-package-v1",
        "name": recipe.name,
        "version": recipe.version,
        "release": recipe.release,
        "arch": ctx.arch,
        "summary": recipe.summary,
        "license": recipe.license,
        "tier": recipe.tier,
        "dependencies": dependencies,
        "runtime_dependencies": recipe.dependencies.get("runtime", []),
        "build_key": key,
        "recipe_digest": recipe.digest,
        "dependency_keys": dep_keys,
        "built_at": dt.datetime.now(UTC).isoformat(),
    }

    tmp = output.with_suffix(".ki2.tmp")
    if tmp.exists():
        tmp.unlink()
    with tarfile.open(tmp, "w:gz") as tar:
        manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
        manifest_file = tempfile.SpooledTemporaryFile()
        manifest_file.write(manifest_bytes)
        manifest_file.seek(0)
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest_bytes)
        info.mode = 0o644
        tar.addfile(info, manifest_file)
        manifest_file.close()

        if destdir.exists():
            for path in sorted(destdir.rglob("*")):
                rel = path.relative_to(destdir).as_posix()
                arcname = "rootfs/" + rel
                info = tar.gettarinfo(str(path), arcname=arcname)
                if path.is_dir():
                    info.mode = 0o755
                    tar.addfile(info)
                    continue
                if rel.startswith(("bin/", "sbin/", "usr/bin/", "usr/sbin/", "usr/local/bin/")):
                    info.mode = 0o755
                else:
                    info.mode = 0o644
                with path.open("rb") as handle:
                    tar.addfile(info, handle)
    tmp.replace(output)


def extract_package_rootfs(package: Path, target: Path) -> None:
    with tarfile.open(package, "r:gz") as tar:
        for member in tar.getmembers():
            if not member.name.startswith("rootfs/"):
                continue
            rel = member.name.removeprefix("rootfs/")
            if not rel:
                continue
            member.name = rel
            if member.linkname.startswith("rootfs/"):
                member.linkname = member.linkname.removeprefix("rootfs/")
            tar.extract(member, target, filter="data")


def read_package_manifest(path: Path) -> dict[str, Any]:
    with tarfile.open(path, "r:gz") as tar:
        member = tar.getmember("manifest.json")
        handle = tar.extractfile(member)
        if handle is None:
            raise Ki2Error(f"{path}: manifest.json is not readable")
        return json.loads(handle.read().decode("utf-8"))


def dependency_package_path(
    ctx: BuildContext,
    recipes: dict[str, Recipe],
    state: dict[str, BuildRecord],
    name: str,
) -> Path:
    record = state.get(name)
    if record and record.output:
        output = record_output_path(ctx, record)
        if output.exists():
            return output

    recipe = recipes[name]
    output = package_path(ctx, recipe)
    if output.exists():
        return output
    raise Ki2Error(f"{name}: dependency package artifact is missing; build it before dependents")


def package_artifact_by_name(ctx: BuildContext, name: str) -> Path | None:
    matches: list[Path] = []
    for path in sorted((ctx.packages_dir / ctx.arch).glob(f"{name}-*.{ctx.arch}.ki2")):
        manifest = read_package_manifest(path)
        if manifest.get("name") == name:
            matches.append(path)
    return matches[-1] if matches else None


def prepare_sysroot(
    ctx: BuildContext,
    recipe: Recipe,
    recipes: dict[str, Recipe],
    state: dict[str, BuildRecord],
) -> None:
    sysroot = sysroot_path(ctx)
    if sysroot.exists():
        shutil.rmtree(sysroot)
    sysroot.mkdir(parents=True, exist_ok=True)

    deps = dependency_closure(recipes, dependency_names(recipe), ctx.arch, include_build_deps=True)
    if not deps:
        return

    for dep in deps:
        package = dependency_package_path(ctx, recipes, state, dep)
        if ctx.verbose:
            print(f"[sysroot] {recipe.name}: {package.name}")
        extract_package_rootfs(package, sysroot)


def build_recipes(ctx: BuildContext, recipes: dict[str, Recipe], ordered: list[str]) -> None:
    state = load_state(ctx)

    for name in ordered:
        recipe = recipes[name]
        dep_keys: dict[str, str] = {}
        for dep in dependency_names(recipe):
            dep_keys[dep] = state.get(dep, BuildRecord(recipes[dep].digest, "", "", recipes[dep].digest)).key

        key = build_key(recipe, ctx, dep_keys)
        output = package_path(ctx, recipe)
        record = state.get(name)
        if record and record.key == key and output.exists():
            print(f"[skip] {name}: cache hit {key[:12]}")
            continue
        if output.exists():
            manifest = read_package_manifest(output)
            if manifest.get("build_key") == key:
                print(f"[skip] {name}: artifact cache hit {key[:12]}")
                state[name] = make_build_record(ctx, recipe, output, key, dep_keys)
                save_state(ctx, state)
                continue

        print(f"[build] {name} {recipe.version}-{recipe.release} ({ctx.arch}) key={key[:12]}")
        if ctx.dry_run:
            work = ctx.build_dir / ctx.arch / "work" / name
            env = command_env(ctx, recipe, work, work / "source", work / "build", work / "dest")
            _ = fetch_source(ctx, recipe, work)
            for command in recipe_commands(recipe, env):
                print("+ " + command)
            print(f"[package] {output}")
            continue

        work = ctx.build_dir / ctx.arch / "work" / name
        if work.exists():
            shutil.rmtree(work)
        build_dir = work / "build"
        destdir = work / "dest"
        build_dir.mkdir(parents=True, exist_ok=True)
        destdir.mkdir(parents=True, exist_ok=True)

        prepare_sysroot(ctx, recipe, recipes, state)
        source_dir = fetch_source(ctx, recipe, work)
        env = command_env(ctx, recipe, work, source_dir, build_dir, destdir)

        commands = recipe_commands(recipe, env)
        if recipe.build.get("system") == "copy" and not commands:
            copy_source_to_dest(source_dir, destdir)
        else:
            for command in commands:
                run_shell(command, env, work, dry_run=False)

        create_package(ctx, recipe, destdir, output, key, dep_keys)
        state[name] = make_build_record(ctx, recipe, output, key, dep_keys)
        save_state(ctx, state)


def write_repo_index(ctx: BuildContext) -> None:
    packages_root = ctx.packages_dir / ctx.arch
    packages: list[dict[str, Any]] = []
    if packages_root.exists():
        for path in sorted(packages_root.glob("*.ki2")):
            manifest = read_package_manifest(path)
            dependencies = manifest.get(
                "dependencies",
                {"build": [], "runtime": manifest.get("runtime_dependencies", [])},
            )
            packages.append(
                {
                    "name": manifest["name"],
                    "version": manifest["version"],
                    "release": manifest["release"],
                    "arch": manifest["arch"],
                    "file": path.name,
                    "size": path.stat().st_size,
                    "sha256": file_sha256(path),
                    "summary": manifest.get("summary", ""),
                    "dependencies": dependencies,
                    "runtime_dependencies": dependencies.get("runtime", []),
                }
            )

    index = {
        "schema": "ki2-repository-v1",
        "arch": ctx.arch,
        "created_at": dt.datetime.now(UTC).isoformat(),
        "packages": packages,
    }
    ctx.repo_dir.mkdir(parents=True, exist_ok=True)
    out = ctx.repo_dir / f"index.{ctx.arch}.json"
    out.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[repo] wrote {out} ({len(packages)} packages)")


def assemble_rootfs(ctx: BuildContext, ordered: list[str]) -> None:
    if ctx.rootfs_dir is None:
        raise Ki2Error("--rootfs-dir is required for rootfs assembly")
    if ctx.dry_run:
        print(f"[rootfs] would assemble {ctx.rootfs_dir}")
    else:
        ctx.rootfs_dir.mkdir(parents=True, exist_ok=True)

    missing: list[str] = []
    for name in ordered:
        package = package_artifact_by_name(ctx, name)
        if package is None:
            missing.append(name)
            continue
        print(f"[rootfs] {package.name}")
        if ctx.dry_run:
            continue
        extract_package_rootfs(package, ctx.rootfs_dir)

    if missing:
        raise Ki2Error("missing package artifacts: " + ", ".join(missing))


def command_list(args: argparse.Namespace) -> None:
    recipes = load_recipes(args.recipe_dir)
    for recipe in sorted(recipes.values(), key=lambda item: (item.tier, item.name)):
        print(f"{recipe.name:18} {recipe.version:12} {recipe.tier:10} {recipe.summary}")


def command_validate(args: argparse.Namespace) -> None:
    recipes = load_recipes(args.recipe_dir)
    profile = load_profile(args.profile) if args.profile else None
    warnings = validate_recipes(recipes, args.arch, profile, args.max_packages)
    print(f"validated {len(recipes)} recipes")
    for warning in warnings:
        print(f"warning: {warning}")


def command_plan(args: argparse.Namespace) -> None:
    recipes = load_recipes(args.recipe_dir)
    profile = load_profile(args.profile)
    ordered = dependency_closure(recipes, list(profile["packages"]), args.arch, args.include_build_deps)
    mode = "build" if args.include_build_deps else "runtime"
    print(f"profile: {profile['name']} ({mode} plan, {len(ordered)} packages)")
    for index, name in enumerate(ordered, start=1):
        recipe = recipes[name]
        print(f"{index:02d}. {recipe.name} {recipe.version}-{recipe.release} [{recipe.tier}]")


def make_context(args: argparse.Namespace) -> BuildContext:
    return BuildContext(
        repo_root=args.repo_root,
        recipe_dir=args.recipe_dir,
        build_dir=args.build_dir,
        packages_dir=args.packages_dir,
        repo_dir=args.repo_dir,
        source_cache=args.source_cache,
        rootfs_dir=args.rootfs_dir,
        arch=args.arch,
        jobs=args.jobs,
        toolchain_id=args.toolchain_id,
        dry_run=args.dry_run,
        allow_unpinned=args.allow_unpinned,
        verbose=args.verbose,
    )


def command_build(args: argparse.Namespace) -> None:
    recipes = load_recipes(args.recipe_dir)
    profile = load_profile(args.profile)
    validate_recipes(recipes, args.arch, profile, None)
    ordered = dependency_closure(recipes, list(profile["packages"]), args.arch, include_build_deps=True)
    build_recipes(make_context(args), recipes, ordered)


def command_repo_index(args: argparse.Namespace) -> None:
    write_repo_index(make_context(args))


def command_rootfs(args: argparse.Namespace) -> None:
    recipes = load_recipes(args.recipe_dir)
    profile = load_profile(args.profile)
    ordered = dependency_closure(recipes, list(profile["packages"]), args.arch, include_build_deps=False)
    assemble_rootfs(make_context(args), ordered)


def add_common_options(parser: argparse.ArgumentParser) -> None:
    root = default_repo_root()
    parser.add_argument("--repo-root", type=Path, default=root)
    parser.add_argument("--recipe-dir", type=Path, default=None)
    parser.add_argument("--arch", default="x86_64")
    parser.add_argument("--jobs", type=int, default=max(os.cpu_count() or 2, 2))
    parser.add_argument("--toolchain-id", default=DEFAULT_TOOLCHAIN_ID)
    parser.add_argument("--verbose", action="store_true")


def add_build_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--build-dir", type=Path, default=None)
    parser.add_argument("--packages-dir", type=Path, default=None)
    parser.add_argument("--repo-dir", type=Path, default=None)
    parser.add_argument("--source-cache", type=Path, default=None)
    parser.add_argument("--rootfs-dir", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-unpinned", action="store_true")


def resolve_common_paths(args: argparse.Namespace) -> None:
    args.repo_root = args.repo_root.resolve()
    if args.recipe_dir is None:
        args.recipe_dir = args.repo_root / "distro" / "recipes"
    else:
        args.recipe_dir = resolve_under_root(args.repo_root, args.recipe_dir)
    for attr, default in {
        "build_dir": args.repo_root / "build" / "ki2",
        "packages_dir": args.repo_root / "dist" / "ki2" / "packages",
        "repo_dir": args.repo_root / "dist" / "ki2" / "repo",
        "source_cache": args.repo_root / "dist" / "sources",
    }.items():
        if hasattr(args, attr):
            value = getattr(args, attr)
            setattr(args, attr, resolve_under_root(args.repo_root, value) if value else default)
    if hasattr(args, "rootfs_dir") and args.rootfs_dir is not None:
        args.rootfs_dir = resolve_under_root(args.repo_root, args.rootfs_dir)
    if hasattr(args, "profile") and args.profile is not None:
        args.profile = resolve_under_root(args.repo_root, args.profile)


def resolve_under_root(root: Path, value: Path) -> Path:
    return value.resolve() if value.is_absolute() else (root / value).resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and assemble early KIKI ki2 packages")
    add_common_options(parser)
    subcommands = parser.add_subparsers(dest="command", required=True)

    list_parser = subcommands.add_parser("list", help="list known recipes")
    list_parser.set_defaults(func=command_list)

    validate_parser = subcommands.add_parser("validate", help="validate recipe catalog")
    validate_parser.add_argument("--profile", type=Path)
    validate_parser.add_argument("--max-packages", type=int, default=40)
    validate_parser.set_defaults(func=command_validate)

    plan_parser = subcommands.add_parser("plan", help="print a dependency-ordered package plan")
    plan_parser.add_argument("--profile", type=Path, required=True)
    plan_parser.add_argument("--include-build-deps", action="store_true")
    plan_parser.set_defaults(func=command_plan)

    build_parser_cmd = subcommands.add_parser("build", help="build packages for a profile")
    build_parser_cmd.add_argument("--profile", type=Path, required=True)
    add_build_paths(build_parser_cmd)
    build_parser_cmd.set_defaults(func=command_build)

    repo_parser = subcommands.add_parser("repo-index", help="generate a ki2 repository index")
    add_build_paths(repo_parser)
    repo_parser.set_defaults(func=command_repo_index)

    rootfs_parser = subcommands.add_parser("rootfs", help="assemble a rootfs from built packages")
    rootfs_parser.add_argument("--profile", type=Path, required=True)
    add_build_paths(rootfs_parser)
    rootfs_parser.set_defaults(func=command_rootfs)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    resolve_common_paths(args)
    try:
        args.func(args)
    except Ki2Error as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
