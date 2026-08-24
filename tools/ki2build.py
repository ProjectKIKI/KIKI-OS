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
import ast
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import stat
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
PACKAGE_FORMAT_REV = "ki2-package-format-v2"
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
    clean_rootfs: bool
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


def strip_yaml_comment(line: str) -> str:
    quote: str | None = None
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if quote == '"' and char == "\\":
            escaped = True
            continue
        if char in {"'", '"'}:
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
            continue
        if char == "#" and quote is None:
            return line[:index].rstrip()
    return line.rstrip()


def split_inline_yaml_list(value: str) -> list[Any]:
    inner = value[1:-1].strip()
    if not inner:
        return []
    result: list[str] = []
    quote: str | None = None
    escaped = False
    start = 0
    for index, char in enumerate(inner):
        if escaped:
            escaped = False
            continue
        if quote == '"' and char == "\\":
            escaped = True
            continue
        if char in {"'", '"'}:
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
            continue
        if char == "," and quote is None:
            result.append(inner[start:index].strip())
            start = index + 1
    result.append(inner[start:].strip())
    return [parse_yaml_scalar(item) for item in result if item]


def parse_yaml_scalar(value: str) -> Any:
    value = value.strip()
    if value == "":
        return None
    lowered = value.lower()
    if lowered in {"yes", "no", "on", "off"}:
        raise Ki2Error(f"ambiguous YAML boolean {value!r}; use true/false or quote the value")
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "~"}:
        return None
    if value.startswith("[") and value.endswith("]"):
        return split_inline_yaml_list(value)
    if value.startswith("{") and value.endswith("}"):
        raise Ki2Error("inline YAML maps are not supported in ki2 YAML files")
    if value[0:1] in {"'", '"'}:
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError) as exc:
            raise Ki2Error(f"invalid quoted YAML scalar {value!r}") from exc
    try:
        return int(value)
    except ValueError:
        return value


def split_yaml_key_value(text: str, origin: Path, lineno: int) -> tuple[str, str | None]:
    if ":" not in text:
        raise Ki2Error(f"{origin}:{lineno}: expected key: value")
    key, value = text.split(":", 1)
    key = key.strip()
    if not key:
        raise Ki2Error(f"{origin}:{lineno}: empty YAML key")
    return key, value.strip() if value.strip() else None


def read_yaml(path: Path) -> dict[str, Any]:
    lines: list[tuple[int, int, str]] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if "\t" in raw:
            raise Ki2Error(f"{path}:{lineno}: tabs are not allowed in ki2 YAML files")
        stripped = strip_yaml_comment(raw)
        if not stripped.strip():
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        if indent % 2 != 0:
            raise Ki2Error(f"{path}:{lineno}: indentation must use two-space steps")
        text = stripped.strip()
        if text.startswith(("---", "...")):
            continue
        if text.startswith(("&", "*")):
            raise Ki2Error(f"{path}:{lineno}: YAML anchors and aliases are not supported")
        lines.append((lineno, indent, text))

    if not lines:
        return {}

    def parse_value_or_child(index: int, indent: int, value: str | None) -> tuple[Any, int]:
        if value is not None:
            return parse_yaml_scalar(value), index
        if index < len(lines) and lines[index][1] > indent:
            return parse_block(index, lines[index][1])
        return {}, index

    def parse_mapping(index: int, indent: int) -> tuple[dict[str, Any], int]:
        result: dict[str, Any] = {}
        while index < len(lines):
            lineno, current_indent, text = lines[index]
            if current_indent < indent:
                break
            if current_indent > indent:
                raise Ki2Error(f"{path}:{lineno}: unexpected indentation")
            if text.startswith("- "):
                break
            key, value = split_yaml_key_value(text, path, lineno)
            index += 1
            result[key], index = parse_value_or_child(index, current_indent, value)
        return result, index

    def parse_sequence(index: int, indent: int) -> tuple[list[Any], int]:
        result: list[Any] = []
        while index < len(lines):
            lineno, current_indent, text = lines[index]
            if current_indent < indent:
                break
            if current_indent > indent:
                raise Ki2Error(f"{path}:{lineno}: unexpected indentation")
            if not text.startswith("-"):
                break
            item_text = text[1:].strip()
            index += 1
            if not item_text:
                if index < len(lines) and lines[index][1] > current_indent:
                    item, index = parse_block(index, lines[index][1])
                else:
                    item = None
            elif ":" in item_text and not item_text.startswith(("'", '"')):
                key, value = split_yaml_key_value(item_text, path, lineno)
                item: dict[str, Any] = {}
                item[key], index = parse_value_or_child(index, current_indent, value)
                if index < len(lines) and lines[index][1] > current_indent:
                    extra, index = parse_mapping(index, lines[index][1])
                    item.update(extra)
            else:
                item = parse_yaml_scalar(item_text)
                if index < len(lines) and lines[index][1] > current_indent:
                    raise Ki2Error(f"{path}:{lines[index][0]}: scalar list item cannot have children")
            result.append(item)
        return result, index

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        if lines[index][2].startswith("-"):
            return parse_sequence(index, indent)
        return parse_mapping(index, indent)

    data, index = parse_block(0, lines[0][1])
    if index != len(lines):
        lineno = lines[index][0]
        raise Ki2Error(f"{path}:{lineno}: could not parse YAML block")
    if not isinstance(data, dict):
        raise Ki2Error(f"{path}: top-level YAML document must be a mapping")
    return data


def read_structured_file(path: Path) -> dict[str, Any]:
    if path.suffix == ".toml":
        return read_toml(path)
    if path.suffix in {".yaml", ".yml"}:
        return read_yaml(path)
    raise Ki2Error(f"{path}: unsupported file extension")


def iter_config_files(root: Path) -> list[Path]:
    return sorted([*root.rglob("*.toml"), *root.rglob("*.yaml"), *root.rglob("*.yml")])


def stable_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def natural_version_key(value: Any) -> tuple[tuple[int, Any], ...]:
    parts: list[tuple[int, Any]] = []
    for part in re.split(r"([0-9]+)", str(value)):
        if not part:
            continue
        if part.isdigit():
            parts.append((0, int(part)))
        else:
            parts.append((1, part))
    return tuple(parts)


def package_manifest_sort_key(manifest: dict[str, Any], path: Path) -> tuple[Any, ...]:
    return (
        str(manifest.get("name", "")),
        natural_version_key(manifest.get("version", "")),
        natural_version_key(manifest.get("release", "")),
        path.name,
    )


def package_latest_sort_key(manifest: dict[str, Any], path: Path) -> tuple[Any, ...]:
    return (
        natural_version_key(manifest.get("version", "")),
        natural_version_key(manifest.get("release", "")),
        path.name,
    )


def string_list(value: Any, *, field: str, recipe: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        raise Ki2Error(f"{recipe}: build.{field} must be a string or a list of strings")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise Ki2Error(f"{recipe}: build.{field} entries must be strings")
        if item:
            result.append(item)
    return result


def repo_relative_path(repo_root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else repo_root / path


def build_file_inputs(ctx: BuildContext, recipe: Recipe, field: str) -> list[dict[str, str]]:
    inputs: list[dict[str, str]] = []
    for value in string_list(recipe.build.get(field), field=field, recipe=recipe.name):
        path = repo_relative_path(ctx.repo_root, value)
        if not path.exists():
            raise Ki2Error(f"{recipe.name}: build.{field} file not found: {path}")
        inputs.append(
            {
                "field": field,
                "path": str(path.relative_to(ctx.repo_root) if path.is_relative_to(ctx.repo_root) else path),
                "sha256": file_sha256(path),
            }
        )
    return inputs


def local_source_inputs(ctx: BuildContext, recipe: Recipe) -> list[dict[str, str]]:
    source = recipe.source
    if source.get("type") != "local":
        return []
    raw_path = source.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise Ki2Error(f"{recipe.name}: local source requires source.path")
    source_path = repo_relative_path(ctx.repo_root, raw_path)
    if not source_path.exists():
        raise Ki2Error(f"{recipe.name}: local source path not found: {source_path}")

    def display_path(path: Path) -> str:
        return str(path.relative_to(ctx.repo_root) if path.is_relative_to(ctx.repo_root) else path)

    inputs: list[dict[str, str]] = []

    def append_path_inputs(path_root: Path, field: str) -> None:
        candidates = [path_root] if path_root.is_file() else sorted(path_root.rglob("*"))
        for path in candidates:
            if path.is_dir():
                continue
            item: dict[str, str] = {
                "field": field,
                "path": display_path(path),
            }
            if path.is_symlink():
                item["symlink"] = os.readlink(path)
            elif path.is_file():
                item["sha256"] = file_sha256(path)
            else:
                continue
            inputs.append(item)

    append_path_inputs(source_path, "source")

    extra_paths = source.get("inputs", [])
    if not isinstance(extra_paths, list) or not all(isinstance(value, str) and value for value in extra_paths):
        raise Ki2Error(f"{recipe.name}: local source.inputs must be a list of non-empty paths")
    for value in extra_paths:
        extra_path = repo_relative_path(ctx.repo_root, value)
        if not extra_path.exists():
            raise Ki2Error(f"{recipe.name}: local source input not found: {extra_path}")
        append_path_inputs(extra_path, "source-input")
    return inputs


def host_file_entries(recipe: Recipe) -> list[dict[str, Any]]:
    value = recipe.build.get("host_files", [])
    if value is None:
        return []
    if isinstance(value, str):
        return [{"source": value}]
    if not isinstance(value, list):
        raise Ki2Error(f"{recipe.name}: build.host_files must be a list")

    entries: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, str):
            entries.append({"source": item})
        elif isinstance(item, dict):
            entries.append(item)
        else:
            raise Ki2Error(f"{recipe.name}: build.host_files entries must be strings or mappings")
    return entries


def host_source_path(ctx: BuildContext, value: Any, *, recipe: str) -> Path:
    if not isinstance(value, str) or not value:
        raise Ki2Error(f"{recipe}: build.host_files entry requires source")
    path = Path(value)
    return path if path.is_absolute() else ctx.repo_root / path


def display_input_path(ctx: BuildContext, path: Path) -> str:
    return str(path.relative_to(ctx.repo_root) if path.is_relative_to(ctx.repo_root) else path)


def ldd_dependencies(path: Path, *, recipe: str) -> list[Path]:
    try:
        result = subprocess.run(["ldd", str(path)], text=True, capture_output=True, check=False)
    except FileNotFoundError as exc:
        raise Ki2Error(f"{recipe}: ldd is required when include_ldd is true") from exc

    output = (result.stdout or "") + "\n" + (result.stderr or "")
    if result.returncode != 0 and "not a dynamic executable" in output:
        return []
    if result.returncode != 0:
        raise Ki2Error(f"{recipe}: ldd failed for {path}: {output.strip()}")

    deps: list[Path] = []
    seen: set[Path] = set()
    for raw in output.splitlines():
        line = raw.strip()
        if not line or "linux-vdso" in line or "not found" in line:
            continue
        candidate = ""
        if "=>" in line:
            candidate = line.split("=>", 1)[1].strip().split(" ", 1)[0]
        else:
            first = line.split(" ", 1)[0]
            if first.startswith("/"):
                candidate = first
        if not candidate.startswith("/"):
            continue
        dep = Path(candidate)
        if dep.exists() and dep not in seen:
            seen.add(dep)
            deps.append(dep)
    return deps


HOST_LDD_CORE_RUNTIME_NAMES = {
    "ld-linux-aarch64.so.1",
    "ld-linux-x86-64.so.2",
    "ld-linux.so.2",
    "libanl.so.1",
    "libc.so.6",
    "libc_malloc_debug.so.0",
    "libcrypt.so.1",
    "libcrypt.so.2",
    "libdl.so.2",
    "libm.so.6",
    "libmvec.so.1",
    "libnsl.so.1",
    "libnss_compat.so.2",
    "libnss_db.so.2",
    "libnss_dns.so.2",
    "libnss_files.so.2",
    "libnss_hesiod.so.2",
    "libpthread.so.0",
    "libresolv.so.2",
    "librt.so.1",
    "libthread_db.so.1",
    "libutil.so.1",
}


def should_copy_host_ldd_dependency(path: Path) -> bool:
    """Keep host-file payloads from replacing KIKI's core ABI runtime."""

    name = path.name
    if name in HOST_LDD_CORE_RUNTIME_NAMES:
        return False
    if name.startswith("ld-linux-"):
        return False
    return True


def host_file_inputs(ctx: BuildContext, recipe: Recipe) -> list[dict[str, str]]:
    inputs: list[dict[str, str]] = []
    for entry in host_file_entries(recipe):
        source = host_source_path(ctx, entry.get("source"), recipe=recipe.name)
        optional = bool(entry.get("optional", False))
        if not source.exists():
            if optional:
                inputs.append({"field": "host_files", "path": str(source), "optional": "missing"})
                continue
            raise Ki2Error(f"{recipe.name}: host file not found: {source}")

        def add_file(path: Path, label: str = "host_files") -> None:
            item: dict[str, str] = {
                "field": label,
                "path": display_input_path(ctx, path),
            }
            if path.is_symlink():
                item["symlink"] = os.readlink(path)
            if path.is_file():
                item["sha256"] = file_sha256(path)
            inputs.append(item)

        if source.is_dir():
            inputs.append({"field": "host_files", "path": display_input_path(ctx, source), "type": "dir"})
            for path in sorted(source.rglob("*")):
                if path.is_dir():
                    continue
                add_file(path)
        else:
            add_file(source)
            if bool(entry.get("include_ldd", False)):
                for dep in ldd_dependencies(source, recipe=recipe.name):
                    if not should_copy_host_ldd_dependency(dep):
                        continue
                    add_file(dep, "host_ldd")
    return inputs


def normalize_dependencies(raw: dict[str, Any], origin: Path, name: str) -> dict[str, list[str]]:
    if "dependencies" in raw and "depends" in raw:
        raise Ki2Error(f"{origin}: {name} must use dependencies or depends, not both")
    source = raw.get("dependencies", raw.get("depends", {}))
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
    raw_architectures = raw.get("architectures", raw.get("arches", raw.get("arch", ["x86_64"])))
    if isinstance(raw_architectures, str):
        raw_architectures = [raw_architectures]
    architectures = tuple(raw_architectures)
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

    for path in iter_config_files(recipe_dir):
        data = read_structured_file(path)
        raw_recipes: list[dict[str, Any]]
        if "recipes" in data:
            raw_recipes = data["recipes"]
        elif "recipe" in data:
            raw_recipes = data["recipe"]
        elif "package" in data:
            raw_recipes = [data["package"]]
        else:
            raise Ki2Error(f"{path}: expected recipes, [[recipe]], or [package]")
        if not isinstance(raw_recipes, list):
            raise Ki2Error(f"{path}: recipes must be a list")

        for raw in raw_recipes:
            if not isinstance(raw, dict):
                raise Ki2Error(f"{path}: recipe entries must be mappings")
            recipe = normalize_recipe(raw, path)
            if recipe.name in recipes:
                raise Ki2Error(
                    f"duplicate recipe {recipe.name!r}: {recipes[recipe.name].origin} and {path}"
                )
            recipes[recipe.name] = recipe
    return recipes


def load_profile(path: Path) -> dict[str, Any]:
    data = read_structured_file(path)
    if "profile" in data:
        profile = data["profile"]
    elif {"name", "packages"}.issubset(data):
        profile = data
    else:
        raise Ki2Error(f"{path}: expected profile mapping")
    if not isinstance(profile, dict):
        raise Ki2Error(f"{path}: profile must be a mapping")
    if not profile.get("name"):
        raise Ki2Error(f"{path}: profile.name is required")
    if not profile.get("packages"):
        raise Ki2Error(f"{path}: profile.packages is required")
    if not isinstance(profile["packages"], list) or not all(isinstance(item, str) for item in profile["packages"]):
        raise Ki2Error(f"{path}: profile.packages must be a list of package names")
    return profile


def validate_recipes(
    recipes: dict[str, Recipe],
    arch: str,
    profile: dict[str, Any] | None,
    max_packages: int | None,
) -> list[str]:
    warnings: list[str] = []
    if max_packages is not None and profile is None and len(recipes) > max_packages:
        raise Ki2Error(f"recipe catalog has {len(recipes)} packages; limit is {max_packages}")

    for recipe in recipes.values():
        if not recipe.supports_arch(arch):
            warnings.append(f"{recipe.name}: does not support arch {arch}")
        for group, deps in recipe.dependencies.items():
            for dep in deps:
                if dep not in recipes:
                    raise Ki2Error(f"{recipe.name}: unknown {group} dependency {dep!r}")
        sysroot_exclude = string_list(
            recipe.build.get("sysroot_exclude"),
            field="sysroot_exclude",
            recipe=recipe.name,
        )
        if recipe.build.get("skip_sysroot", False) and sysroot_exclude:
            raise Ki2Error(f"{recipe.name}: build.skip_sysroot and build.sysroot_exclude cannot be combined")
        for excluded in sysroot_exclude:
            if excluded not in recipes:
                raise Ki2Error(f"{recipe.name}: unknown sysroot exclusion {excluded!r}")
        if recipe.source.get("type") == "url":
            sha = str(recipe.source.get("sha256", ""))
            if sha in PIN_PLACEHOLDERS:
                warnings.append(f"{recipe.name}: source sha256 is not pinned yet")

    if profile:
        for package in profile["packages"]:
            if package not in recipes:
                raise Ki2Error(f"profile {profile['name']}: unknown package {package!r}")
        if max_packages is not None:
            plan = dependency_closure(recipes, list(profile["packages"]), arch, include_build_deps=False)
            if len(plan) > max_packages:
                raise Ki2Error(
                    f"profile {profile['name']} has {len(plan)} runtime packages; limit is {max_packages}"
                )
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
    extra_inputs: list[dict[str, str]] = []
    extra_inputs.extend(build_file_inputs(ctx, recipe, "config_fragments"))
    extra_inputs.extend(build_file_inputs(ctx, recipe, "patches"))
    extra_inputs.extend(local_source_inputs(ctx, recipe))
    extra_inputs.extend(host_file_inputs(ctx, recipe))
    return stable_hash(
        {
            "schema": "ki2-build-key-v1",
            "package_format": PACKAGE_FORMAT_REV,
            "recipe": recipe.digest,
            "arch": ctx.arch,
            "toolchain": ctx.toolchain_id,
            "deps": dep_keys,
            "extra_inputs": extra_inputs,
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
    env = {
        "KI2_ARCH": ctx.arch,
        "KI2_BUILD_TRIPLE": "x86_64-kiki-linux-gnu",
        "KI2_TARGET_TRIPLE": target,
        "KI2_PACKAGE": recipe.name,
        "KI2_REPO_ROOT": str(ctx.repo_root),
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
        "KI2_SYSROOT_CPPFLAGS": f"-I{sysroot / 'usr' / 'include'} -I{sysroot / 'include'}",
        "KI2_SYSROOT_LDFLAGS": " ".join(
            [
                f"-L{sysroot / 'usr' / 'lib'}",
                f"-L{sysroot / 'usr' / 'lib64'}",
                f"-L{sysroot / 'lib'}",
                f"-L{sysroot / 'lib64'}",
                f"-Wl,-rpath-link,{sysroot / 'usr' / 'lib'}",
                f"-Wl,-rpath-link,{sysroot / 'usr' / 'lib64'}",
                f"-Wl,-rpath-link,{sysroot / 'lib'}",
                f"-Wl,-rpath-link,{sysroot / 'lib64'}",
            ]
        ),
        "KI2_SYSROOT_LIBRARY_PATH": os.pathsep.join(
            [
                str(sysroot / "usr" / "lib"),
                str(sysroot / "usr" / "lib64"),
                str(sysroot / "lib"),
                str(sysroot / "lib64"),
            ]
        ),
        "KI2_SYSROOT_C_INCLUDE_PATH": os.pathsep.join(
            [
                str(sysroot / "usr" / "include"),
                str(sysroot / "include"),
            ]
        ),
    }
    extra_env = recipe.build.get("env", {})
    if extra_env:
        if not isinstance(extra_env, dict):
            raise Ki2Error(f"{recipe.name}: build.env must be a table")
        for key, value in extra_env.items():
            if not isinstance(key, str) or not key:
                raise Ki2Error(f"{recipe.name}: build.env keys must be non-empty strings")
            if not isinstance(value, str):
                raise Ki2Error(f"{recipe.name}: build.env.{key} must be a string")
            env[key] = format_command(value, env)
    return env


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
    options = " ".join(format_command(str(option), env) for option in recipe.build.get("configure_options", []))
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
        fragments = string_list(recipe.build.get("config_fragments"), field="config_fragments", recipe=recipe.name)
        commands = [
            f"make -C {source} O={build}/kernel defconfig",
        ]
        if fragments:
            repo_root = Path(env["KI2_REPO_ROOT"])
            quoted_fragments = " ".join(
                shell_quote(str(repo_relative_path(repo_root, fragment))) for fragment in fragments
            )
            commands.extend(
                [
                    f"cd {source} && ./scripts/kconfig/merge_config.sh -m -O {build}/kernel {build}/kernel/.config {quoted_fragments}",
                    f"make -C {source} O={build}/kernel olddefconfig",
                ]
            )
        commands.extend(
            [
                f"make -C {source} O={build}/kernel -j{jobs}",
                f"mkdir -p {dest}/boot && cp {build}/kernel/arch/x86/boot/bzImage {dest}/boot/vmlinuz-kiki",
                f"make -C {source} O={build}/kernel INSTALL_MOD_PATH={dest} modules_install",
            ]
        )
        if recipe.build.get("strip_module_build_links", False):
            commands.append(f"find {dest}/lib/modules -type l \\( -name build -o -name source \\) -delete")
        return commands
    if system in {"copy", "virtual"}:
        return []
    if system == "stage2-stub":
        return [f"# stage2-stub payload for {recipe.name}"]
    if system == "host-files":
        return [f"# host-files payload for {recipe.name}"]
    raise Ki2Error(f"{recipe.name}: unknown build.system {system!r}")


def recipe_commands(recipe: Recipe, env: dict[str, str]) -> list[str]:
    explicit: list[str] = []
    for key in ("commands", "prepare", "configure", "compile", "install"):
        values = recipe.build.get(key)
        if values:
            explicit.extend(values)
    if explicit:
        return [format_command(command, env) for command in explicit]
    return default_commands(recipe, env)


def recipe_patch_strip(recipe: Recipe) -> int:
    raw = recipe.build.get("patch_strip", 1)
    try:
        strip = int(raw)
    except (TypeError, ValueError) as exc:
        raise Ki2Error(f"{recipe.name}: build.patch_strip must be a non-negative integer") from exc
    if strip < 0:
        raise Ki2Error(f"{recipe.name}: build.patch_strip must be a non-negative integer")
    return strip


def recipe_patch_commands(ctx: BuildContext, recipe: Recipe, source_dir: Path) -> list[str]:
    strip = recipe_patch_strip(recipe)
    commands: list[str] = []
    for value in string_list(recipe.build.get("patches"), field="patches", recipe=recipe.name):
        patch = repo_relative_path(ctx.repo_root, value)
        if not patch.exists():
            raise Ki2Error(f"{recipe.name}: patch file not found: {patch}")
        commands.append(f"patch -d {shell_quote(str(source_dir))} -p{strip} -i {shell_quote(str(patch))}")
    return commands


def fetch_url_to_cache(ctx: BuildContext, recipe: Recipe, source: dict[str, Any], label: str) -> Path:
    url = source.get("url")
    if not url:
        raise Ki2Error(f"{recipe.name}: source.{label}.url is required")
    sha = str(source.get("sha256", ""))
    filename = source.get("file") or Path(str(url)).name
    ctx.source_cache.mkdir(parents=True, exist_ok=True)
    archive = ctx.source_cache / str(filename)

    if ctx.dry_run:
        print(f"[fetch] {recipe.name}: {url} -> {archive}")
        return archive

    if not archive.exists():
        print(f"[fetch] {recipe.name}: {url}")
        urllib.request.urlretrieve(str(url), archive)

    actual_sha = file_sha256(archive)
    if sha in PIN_PLACEHOLDERS:
        if not ctx.allow_unpinned:
            raise Ki2Error(
                f"{recipe.name}: source {label} sha256 is not pinned; rerun with --allow-unpinned "
                f"after reviewing {actual_sha}"
            )
        print(f"[warn] {recipe.name}: using unpinned source {label} sha256 {actual_sha}")
    elif actual_sha != sha:
        raise Ki2Error(f"{recipe.name}: source {label} sha256 mismatch: got {actual_sha}, want {sha}")
    return archive


def merge_source_payload(archive: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    if tarfile.is_tarfile(archive):
        with tempfile.TemporaryDirectory(prefix="ki2-extra-source-") as tmp:
            extracted = Path(tmp) / "source"
            extract_archive(archive, extracted)
            for child in extracted.iterdir():
                destination = target / child.name
                if child.is_dir():
                    shutil.copytree(child, destination, dirs_exist_ok=True)
                else:
                    shutil.copy2(child, destination)
        return
    shutil.copy2(archive, target / archive.name)


def source_extra_entries(recipe: Recipe) -> list[dict[str, Any]]:
    extra = recipe.source.get("extra", [])
    if extra is None:
        return []
    if not isinstance(extra, list) or not all(isinstance(item, dict) for item in extra):
        raise Ki2Error(f"{recipe.name}: source.extra must be a list of mappings")
    return extra


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
            remove_tree(source_dir)
        if local.is_dir():
            shutil.copytree(local, source_dir)
        else:
            source_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(local, source_dir / local.name)
        return source_dir

    if source_type != "url":
        raise Ki2Error(f"{recipe.name}: unsupported source.type {source_type!r}")

    archive = fetch_url_to_cache(ctx, recipe, source, "url")

    if ctx.dry_run:
        for index, extra_source in enumerate(source_extra_entries(recipe), start=1):
            fetch_url_to_cache(ctx, recipe, extra_source, f"extra[{index}]")
        return source_dir

    if tarfile.is_tarfile(archive):
        extract_archive(archive, source_dir)
    else:
        if source_dir.exists():
            remove_tree(source_dir)
        source_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(archive, source_dir / archive.name)

    for index, extra_source in enumerate(source_extra_entries(recipe), start=1):
        extra_archive = fetch_url_to_cache(ctx, recipe, extra_source, f"extra[{index}]")
        merge_source_payload(extra_archive, source_dir)

    children = [child for child in source_dir.iterdir()]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return source_dir


def extract_archive(archive: Path, target: Path) -> None:
    if target.exists():
        remove_tree(target)
    target.mkdir(parents=True, exist_ok=True)
    if tarfile.is_tarfile(archive):
        with tarfile.open(archive) as tar:
            try:
                tar.extractall(target, filter="data")
            except TypeError:
                tar.extractall(target)
        return
    raise Ki2Error(f"unsupported archive format: {archive}")


def run_shell(command: str, env: dict[str, str], cwd: Path, dry_run: bool) -> None:
    print("+ " + command)
    if dry_run:
        return
    merged_env = os.environ.copy()
    merged_env.update(env)
    subprocess.run(command, shell=True, cwd=cwd, env=merged_env, check=True)


SOURCE_COPY_IGNORE_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
SOURCE_COPY_IGNORE_SUFFIXES = (".pyc", ".pyo")


def should_ignore_source_copy_entry(name: str) -> bool:
    return name in SOURCE_COPY_IGNORE_NAMES or name.endswith(SOURCE_COPY_IGNORE_SUFFIXES)


def copy_source_ignore(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if should_ignore_source_copy_entry(name)}


def copy_source_to_dest(source_dir: Path, destdir: Path) -> None:
    for child in source_dir.iterdir():
        if should_ignore_source_copy_entry(child.name):
            continue
        target = destdir / child.name
        if child.is_dir():
            shutil.copytree(child, target, dirs_exist_ok=True, ignore=copy_source_ignore)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, target)


def parse_file_mode(value: Any, default: int = 0o644) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return default
        try:
            return int(text, 8)
        except ValueError as exc:
            raise Ki2Error(f"invalid file mode {value!r}") from exc
    raise Ki2Error(f"invalid file mode {value!r}")


def rootfs_relative_path(value: str, *, field: str, recipe: str) -> Path:
    if not value:
        raise Ki2Error(f"{recipe}: {field} path is empty")
    rel = Path(value.strip("/"))
    if rel.is_absolute() or ".." in rel.parts or str(rel) in {"", "."}:
        raise Ki2Error(f"{recipe}: unsafe {field} path {value!r}")
    return rel


def stage2_stub_list(value: Any, *, field: str, recipe: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, str):
        return [{"name": value}]
    if not isinstance(value, list):
        raise Ki2Error(f"{recipe}: build.stub.{field} must be a list")
    result: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, str):
            result.append({"name": item})
        elif isinstance(item, dict):
            result.append(item)
        else:
            raise Ki2Error(f"{recipe}: build.stub.{field} entries must be strings or mappings")
    return result


def stage2_stub_string_list(value: Any, *, field: str, recipe: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise Ki2Error(f"{recipe}: build.stub.{field} must be a string or a list of strings")
    return [item for item in value if item]


def write_rootfs_text(destdir: Path, path: str, content: str, mode: int, *, field: str, recipe: str) -> None:
    target = destdir / rootfs_relative_path(path, field=field, recipe=recipe)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    target.chmod(mode)


def stage2_stub_script(recipe: Recipe, command_name: str, message: str | None = None) -> str:
    detail = message or (
        f"KIKI Stage 2 placeholder: {recipe.name} provides {command_name}, "
        "but the source-backed binary is not bundled yet."
    )
    return (
        "#!/bin/sh\n"
        "case \"${1:-}\" in\n"
        "  --version|-v|version)\n"
        f"    echo \"{command_name} {recipe.version}-{recipe.release} (KIKI Stage 2 placeholder)\"\n"
        "    exit 0\n"
        "    ;;\n"
        "esac\n"
        "cat >&2 <<'EOF'\n"
        f"{detail}\n"
        "This package reserves filesystem paths, dependencies, and service wiring for Stage 2 testing.\n"
        f"Rebuild {recipe.name} from upstream source before production use.\n"
        "EOF\n"
        "exit 69\n"
    )


def stage2_stub_service(recipe: Recipe, entry: dict[str, Any]) -> str:
    name = str(entry.get("name") or f"{recipe.name}.service")
    description = str(entry.get("description") or f"KIKI Stage 2 placeholder for {recipe.name}")
    condition_path = str(entry.get("condition_path") or "")
    exec_start = str(entry.get("exec_start") or condition_path or f"/usr/bin/{recipe.name}")
    service_type = str(entry.get("type") or "simple")
    wanted_by = str(entry.get("wanted_by") or "multi-user.target")
    after = stage2_stub_string_list(entry.get("after"), field=f"services.{name}.after", recipe=recipe.name)
    wants = stage2_stub_string_list(entry.get("wants"), field=f"services.{name}.wants", recipe=recipe.name)
    environment = stage2_stub_string_list(entry.get("environment"), field=f"services.{name}.environment", recipe=recipe.name)
    environment_files = stage2_stub_string_list(entry.get("environment_files"), field=f"services.{name}.environment_files", recipe=recipe.name)

    lines = [
        "[Unit]",
        f"Description={description}",
        f"Documentation=file:/usr/share/doc/kiki-stage2/{recipe.name}.txt",
    ]
    if condition_path:
        lines.append(f"ConditionPathExists={condition_path}")
    if after:
        lines.append("After=" + " ".join(after))
    if wants:
        lines.append("Wants=" + " ".join(wants))
    lines.extend(
        [
            "",
            "[Service]",
            f"Type={service_type}",
        ]
    )
    for value in environment:
        lines.append(f"Environment={value}")
    for value in environment_files:
        lines.append(f"EnvironmentFile={value}")
    lines.extend(
        [
            f"ExecStart={exec_start}",
            "",
            "[Install]",
            f"WantedBy={wanted_by}",
            "",
        ]
    )
    return "\n".join(lines)


def stage2_stub_file_content(entry: dict[str, Any], *, recipe: str) -> str:
    if "content" in entry:
        return str(entry.get("content") or "")
    if "lines" in entry:
        lines = entry["lines"]
        if not isinstance(lines, list) or not all(isinstance(item, str) for item in lines):
            raise Ki2Error(f"{recipe}: build.stub.files.lines must be a list of strings")
        return "\n".join(lines) + "\n"
    return ""


def install_stage2_stub(ctx: BuildContext, recipe: Recipe, destdir: Path) -> None:
    stub = recipe.build.get("stub", {})
    if stub is None:
        stub = {}
    if not isinstance(stub, dict):
        raise Ki2Error(f"{recipe.name}: build.stub must be a mapping")

    binaries = stage2_stub_list(stub.get("binaries"), field="binaries", recipe=recipe.name)
    services = stage2_stub_list(stub.get("services"), field="services", recipe=recipe.name)
    files = stage2_stub_list(stub.get("files"), field="files", recipe=recipe.name)
    directories = stage2_stub_string_list(stub.get("directories"), field="directories", recipe=recipe.name)

    for directory in directories:
        target = destdir / rootfs_relative_path(directory, field="directories", recipe=recipe.name)
        target.mkdir(parents=True, exist_ok=True)

    for entry in binaries:
        name = str(entry.get("name") or "")
        if not name:
            raise Ki2Error(f"{recipe.name}: build.stub.binaries entry requires name")
        path = str(entry.get("path") or f"/usr/bin/{name}")
        mode = parse_file_mode(entry.get("mode"), default=0o755)
        message = entry.get("message")
        write_rootfs_text(
            destdir,
            path,
            stage2_stub_script(recipe, name, str(message) if message else None),
            mode,
            field="binaries",
            recipe=recipe.name,
        )

    for entry in services:
        name = str(entry.get("name") or "")
        if not name:
            raise Ki2Error(f"{recipe.name}: build.stub.services entry requires name")
        write_rootfs_text(
            destdir,
            f"/usr/lib/systemd/system/{name}",
            stage2_stub_service(recipe, entry),
            0o644,
            field="services",
            recipe=recipe.name,
        )

    for entry in files:
        path = str(entry.get("path") or "")
        if not path:
            raise Ki2Error(f"{recipe.name}: build.stub.files entry requires path")
        content = stage2_stub_file_content(entry, recipe=recipe.name)
        write_rootfs_text(
            destdir,
            path,
            content,
            parse_file_mode(entry.get("mode"), default=0o644),
            field="files",
            recipe=recipe.name,
        )

    note = (
        f"{recipe.name} {recipe.version}-{recipe.release}\n"
        "\n"
        "This is a KIKI Stage 2 packaging placeholder.\n"
        "It is installable so dependency, repository, service, and installer flows can be tested.\n"
        "It is not a production source-backed binary package yet.\n"
    )
    write_rootfs_text(destdir, f"/usr/share/doc/kiki-stage2/{recipe.name}.txt", note, 0o644, field="note", recipe=recipe.name)
    metadata = {
        "schema": "kiki-stage2-placeholder-v1",
        "package": recipe.name,
        "version": recipe.version,
        "release": recipe.release,
        "arch": ctx.arch,
        "binaries": binaries,
        "services": services,
        "files": files,
    }
    write_rootfs_text(
        destdir,
        f"/usr/share/kiki/stage2/{recipe.name}.json",
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        0o644,
        field="metadata",
        recipe=recipe.name,
    )


def install_stage2_support_files(recipe: Recipe, destdir: Path) -> None:
    stub = recipe.build.get("stub", {})
    if stub is None:
        stub = {}
    if not isinstance(stub, dict):
        raise Ki2Error(f"{recipe.name}: build.stub must be a mapping")

    services = stage2_stub_list(stub.get("services"), field="services", recipe=recipe.name)
    files = stage2_stub_list(stub.get("files"), field="files", recipe=recipe.name)
    directories = stage2_stub_string_list(stub.get("directories"), field="directories", recipe=recipe.name)

    for directory in directories:
        target = destdir / rootfs_relative_path(directory, field="directories", recipe=recipe.name)
        target.mkdir(parents=True, exist_ok=True)

    for entry in services:
        name = str(entry.get("name") or "")
        if not name:
            raise Ki2Error(f"{recipe.name}: build.stub.services entry requires name")
        write_rootfs_text(
            destdir,
            f"/usr/lib/systemd/system/{name}",
            stage2_stub_service(recipe, entry),
            0o644,
            field="services",
            recipe=recipe.name,
        )

    for entry in files:
        path = str(entry.get("path") or "")
        if not path:
            raise Ki2Error(f"{recipe.name}: build.stub.files entry requires path")
        content = stage2_stub_file_content(entry, recipe=recipe.name)
        write_rootfs_text(
            destdir,
            path,
            content,
            parse_file_mode(entry.get("mode"), default=0o644),
            field="files",
            recipe=recipe.name,
        )


def host_file_destination(entry: dict[str, Any], source: Path, *, recipe: str) -> str:
    destination = entry.get("destination", entry.get("dest"))
    if destination is None:
        destination = str(source)
    if not isinstance(destination, str) or not destination:
        raise Ki2Error(f"{recipe}: build.host_files.destination must be a non-empty string")
    return destination


def copy_host_file(source: Path, destdir: Path, destination: str, mode: int | None, *, recipe: str) -> None:
    target = destdir / rootfs_relative_path(destination, field="host_files.destination", recipe=recipe)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target, follow_symlinks=True)
    if mode is not None:
        target.chmod(mode)


def install_host_files(ctx: BuildContext, recipe: Recipe, destdir: Path) -> None:
    for entry in host_file_entries(recipe):
        source = host_source_path(ctx, entry.get("source"), recipe=recipe.name)
        optional = bool(entry.get("optional", False))
        if not source.exists():
            if optional:
                continue
            raise Ki2Error(f"{recipe.name}: host file not found: {source}")

        destination = host_file_destination(entry, source, recipe=recipe.name)
        mode = parse_file_mode(entry.get("mode"), default=-1)
        chmod_mode = None if mode < 0 else mode

        if source.is_dir():
            if not bool(entry.get("recursive", False)):
                raise Ki2Error(f"{recipe.name}: directory host file requires recursive: true: {source}")
            target = destdir / rootfs_relative_path(destination, field="host_files.destination", recipe=recipe.name)
            shutil.copytree(source, target, dirs_exist_ok=True, symlinks=False)
        else:
            copy_host_file(source, destdir, destination, chmod_mode, recipe=recipe.name)
            if bool(entry.get("include_ldd", False)):
                for dep in ldd_dependencies(source, recipe=recipe.name):
                    if not should_copy_host_ldd_dependency(dep):
                        continue
                    copy_host_file(dep, destdir, str(dep), None, recipe=recipe.name)

    install_stage2_support_files(recipe, destdir)


def remove_tree(path: Path) -> None:
    def make_writable_and_retry(function: Any, target: str, _exc_info: Any) -> None:
        os.chmod(target, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        function(target)

    shutil.rmtree(path, onerror=make_writable_and_retry)


def package_file_manifest(destdir: Path) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    if not destdir.exists():
        return files
    for path in sorted(destdir.rglob("*")):
        rel = path.relative_to(destdir).as_posix()
        mode = package_entry_mode(rel, path)
        info: dict[str, Any] = {
            "path": "/" + rel,
            "mode": oct(mode),
        }
        if path.is_symlink():
            info["type"] = "symlink"
            info["target"] = os.readlink(path)
        elif path.is_dir():
            info["type"] = "dir"
        else:
            info["type"] = "file"
            info["size"] = path.stat().st_size
            info["sha256"] = file_sha256(path)
        files.append(info)
    return files


def package_entry_mode(rel: str, path: Path) -> int:
    if path.is_symlink():
        return 0o777
    if rel in {"tmp", "var/tmp"}:
        return 0o1777
    if rel in {"etc/shadow", "etc/gshadow"}:
        return 0o600
    if rel == "root" or rel.startswith("root/"):
        return 0o700 if path.is_dir() else 0o600
    if rel in {
        "lib64/ld-linux-x86-64.so.2",
        "lib/ld-linux-x86-64.so.2",
        "lib/ld-linux.so.2",
        "usr/lib64/ld-linux-x86-64.so.2",
    }:
        return 0o755
    if rel == "etc/sudoers.d":
        return 0o750
    if rel == "etc/sudoers" or rel.startswith("etc/sudoers.d/"):
        return 0o440
    if rel == "usr/bin/sudo":
        return 0o4755
    if path.is_dir():
        mode = stat.S_IMODE(path.stat().st_mode)
        return mode if mode & 0o7000 else 0o755
    if rel.startswith(("etc/", "usr/etc/")):
        return 0o644
    if rel.startswith(("etc/systemd/system/", "usr/lib/systemd/system/", "lib/systemd/system/")):
        return 0o644
    if rel.startswith(("usr/lib/tmpfiles.d/", "lib/tmpfiles.d/")):
        return 0o644
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o7000:
        return mode
    if rel.startswith(("bin/", "sbin/", "usr/bin/", "usr/sbin/", "usr/local/bin/")):
        return 0o755
    if rel.startswith(("usr/libexec/", "libexec/", "usr/lib/systemd/", "lib/systemd/")) and mode & 0o111:
        return 0o755
    return 0o644


def normalize_tar_owner(info: tarfile.TarInfo) -> None:
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"


def create_package(ctx: BuildContext, recipe: Recipe, destdir: Path, output: Path, key: str, dep_keys: dict[str, str]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    dependencies = {
        "build": recipe.dependencies.get("build", []),
        "runtime": recipe.dependencies.get("runtime", []),
    }
    files = package_file_manifest(destdir)
    regular_file_count = sum(1 for item in files if item.get("type") != "dir")
    manifest = {
        "schema": "ki2-package-v1",
        "package_format": PACKAGE_FORMAT_REV,
        "name": recipe.name,
        "version": recipe.version,
        "release": recipe.release,
        "arch": ctx.arch,
        "summary": recipe.summary,
        "license": recipe.license,
        "tier": recipe.tier,
        "dependencies": dependencies,
        "runtime_dependencies": recipe.dependencies.get("runtime", []),
        "payload": {
            "rootfs_prefix": "rootfs/",
            "contains_os_tree": True,
            "file_count": regular_file_count,
            "entry_count": len(files),
        },
        "files": files,
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
        normalize_tar_owner(info)
        tar.addfile(info, manifest_file)
        manifest_file.close()

        if destdir.exists():
            for path in sorted(destdir.rglob("*")):
                rel = path.relative_to(destdir).as_posix()
                arcname = "rootfs/" + rel
                info = tar.gettarinfo(str(path), arcname=arcname)
                info.mode = package_entry_mode(rel, path)
                normalize_tar_owner(info)
                if path.is_dir():
                    tar.addfile(info)
                    continue
                if path.is_symlink():
                    tar.addfile(info)
                    continue
                with path.open("rb") as handle:
                    tar.addfile(info, handle)
    tmp.replace(output)


def prepare_rootfs_member_target(target: Path, rel: str, member: tarfile.TarInfo) -> None:
    path = target / rel
    if member.isdir():
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            path.unlink()
        return
    if path.is_dir() and not path.is_symlink():
        raise Ki2Error(f"package entry {rel}: cannot replace an existing directory")
    if path.exists() or path.is_symlink():
        path.unlink()


def extract_package_rootfs(package: Path, target: Path) -> None:
    with tarfile.open(package, "r:gz") as tar:
        for member in tar.getmembers():
            if not member.name.startswith("rootfs/"):
                continue
            rel = member.name.removeprefix("rootfs/")
            if not rel:
                continue
            prepare_rootfs_member_target(target, rel, member)
            mode = member.mode
            member.name = rel
            if member.linkname.startswith("rootfs/"):
                member.linkname = member.linkname.removeprefix("rootfs/")
            tar.extract(member, target, filter="data")
            extracted = target / rel
            if not extracted.is_symlink():
                os.chmod(extracted, mode)


def package_manifest_files(manifest: dict[str, Any]) -> list[str]:
    files = manifest.get("files", [])
    if not isinstance(files, list):
        return []
    paths: list[str] = []
    for entry in files:
        if not isinstance(entry, dict):
            continue
        path = str(entry.get("path") or "")
        if path:
            paths.append(path)
    return sorted(paths)


def write_rootfs_installed_state(rootfs: Path, packages: list[tuple[Path, dict[str, Any]]]) -> None:
    state_dir = rootfs / "var" / "lib" / "ki2"
    state_dir.mkdir(parents=True, exist_ok=True)
    records: dict[str, Any] = {}
    installed_at = dt.datetime.now(UTC).isoformat()
    for package_path, manifest in packages:
        name = str(manifest.get("name") or package_path.name)
        records[name] = {
            "name": name,
            "version": str(manifest.get("version") or ""),
            "release": str(manifest.get("release") or ""),
            "arch": str(manifest.get("arch") or ""),
            "file": package_path.name,
            "sha256": file_sha256(package_path),
            "summary": str(manifest.get("summary") or ""),
            "dependencies": manifest.get("dependencies", {}),
            "repository": {"name": "rootfs-assembly", "url": ""},
            "installed_at": installed_at,
            "files": package_manifest_files(manifest),
        }
    installed = {
        "schema": "ki2-installed-v1",
        "created_at": installed_at,
        "packages": records,
    }
    (state_dir / "installed.json").write_text(json.dumps(installed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    installed_list = "\n".join(sorted(records))
    (state_dir / "installed.list").write_text(installed_list + ("\n" if installed_list else ""), encoding="utf-8")


def systemd_unit_path(rootfs: Path, unit: str) -> Path | None:
    candidates = [
        rootfs / "etc" / "systemd" / "system" / unit,
        rootfs / "usr" / "lib" / "systemd" / "system" / unit,
        rootfs / "lib" / "systemd" / "system" / unit,
    ]
    if "@" in unit:
        prefix, suffix = unit.split("@", 1)
        if "." in suffix:
            template = f"{prefix}@.{suffix.rsplit('.', 1)[1]}"
            candidates.extend(
                [
                    rootfs / "etc" / "systemd" / "system" / template,
                    rootfs / "usr" / "lib" / "systemd" / "system" / template,
                    rootfs / "lib" / "systemd" / "system" / template,
                ]
            )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def systemd_install_fields(unit_file: Path) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {"WantedBy": [], "Alias": [], "Also": []}
    section = ""
    for raw in unit_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section == "Install" and line.startswith("WantedBy="):
            fields["WantedBy"].extend(item for item in line.removeprefix("WantedBy=").split() if item)
        elif section == "Install" and line.startswith("Alias="):
            fields["Alias"].extend(item for item in line.removeprefix("Alias=").split() if item)
        elif section == "Install" and line.startswith("Also="):
            fields["Also"].extend(item for item in line.removeprefix("Also=").split() if item)
    return fields


def systemd_wanted_by(unit_file: Path, unit: str) -> list[str]:
    wanted = systemd_install_fields(unit_file)["WantedBy"]
    if wanted:
        return wanted
    if unit.startswith("getty@"):
        return ["getty.target"]
    if unit.endswith(".service"):
        return ["multi-user.target"]
    return []


def relative_symlink_target(link: Path, target: Path) -> str:
    return os.path.relpath(target, start=link.parent).replace(os.sep, "/")


def enable_systemd_units(rootfs: Path, units: list[str], seen: set[str] | None = None) -> None:
    if seen is None:
        seen = set()
    for unit in units:
        if unit in seen:
            continue
        seen.add(unit)
        unit_file = systemd_unit_path(rootfs, unit)
        if unit_file is None:
            print(f"[rootfs] warning: systemd unit not found for enable: {unit}")
            continue
        install_fields = systemd_install_fields(unit_file)
        for target in systemd_wanted_by(unit_file, unit):
            wants_dir = rootfs / "etc" / "systemd" / "system" / f"{target}.wants"
            wants_dir.mkdir(parents=True, exist_ok=True)
            link = wants_dir / unit
            if link.exists() or link.is_symlink():
                continue
            try:
                link.symlink_to(relative_symlink_target(link, unit_file))
            except OSError:
                shutil.copy2(unit_file, link)
            print(f"[rootfs] enable {unit} -> {target}")
        for alias in install_fields["Alias"]:
            alias_link = rootfs / "etc" / "systemd" / "system" / alias
            alias_link.parent.mkdir(parents=True, exist_ok=True)
            if alias_link.exists() or alias_link.is_symlink():
                continue
            try:
                alias_link.symlink_to(relative_symlink_target(alias_link, unit_file))
            except OSError:
                shutil.copy2(unit_file, alias_link)
            print(f"[rootfs] alias {alias} -> {unit}")
        if install_fields["Also"]:
            enable_systemd_units(rootfs, install_fields["Also"], seen)


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
    matches: list[tuple[tuple[Any, ...], Path]] = []
    for path in sorted((ctx.packages_dir / ctx.arch).glob(f"{name}-*.{ctx.arch}.ki2")):
        manifest = read_package_manifest(path)
        if manifest.get("name") == name:
            matches.append((package_latest_sort_key(manifest, path), path))
    return max(matches, key=lambda item: item[0])[1] if matches else None


def package_artifact_for_recipe(ctx: BuildContext, recipe: Recipe) -> Path | None:
    output = package_path(ctx, recipe)
    if output.exists():
        return output
    return package_artifact_by_name(ctx, recipe.name)


def prepare_sysroot(
    ctx: BuildContext,
    recipe: Recipe,
    recipes: dict[str, Recipe],
    state: dict[str, BuildRecord],
) -> None:
    sysroot = sysroot_path(ctx)
    if sysroot.exists():
        remove_tree(sysroot)
    sysroot.mkdir(parents=True, exist_ok=True)

    deps = dependency_closure(recipes, dependency_names(recipe), ctx.arch, include_build_deps=True)
    if not deps:
        return

    excluded_roots = string_list(
        recipe.build.get("sysroot_exclude"),
        field="sysroot_exclude",
        recipe=recipe.name,
    )
    excluded = set(
        dependency_closure(recipes, excluded_roots, ctx.arch, include_build_deps=True)
    )

    for dep in deps:
        if dep in excluded:
            if ctx.verbose:
                print(f"[sysroot] {recipe.name}: host bootstrap excludes {dep}")
            continue
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
            source_dir = fetch_source(ctx, recipe, work)
            env = command_env(ctx, recipe, work, source_dir, work / "build", work / "dest")
            for command in recipe_patch_commands(ctx, recipe, source_dir):
                print("+ " + command)
            for command in recipe_commands(recipe, env):
                print("+ " + command)
            print(f"[package] {output}")
            continue

        work = ctx.build_dir / ctx.arch / "work" / name
        if work.exists():
            remove_tree(work)
        build_dir = work / "build"
        destdir = work / "dest"
        build_dir.mkdir(parents=True, exist_ok=True)
        destdir.mkdir(parents=True, exist_ok=True)

        skip_sysroot = recipe.build.get("skip_sysroot", False)
        if not isinstance(skip_sysroot, bool):
            raise Ki2Error(f"{recipe.name}: build.skip_sysroot must be boolean")
        if recipe.build.get("system") != "host-files" and not skip_sysroot:
            prepare_sysroot(ctx, recipe, recipes, state)
        source_dir = fetch_source(ctx, recipe, work)
        env = command_env(ctx, recipe, work, source_dir, build_dir, destdir)

        for command in recipe_patch_commands(ctx, recipe, source_dir):
            run_shell(command, env, work, dry_run=False)

        commands = recipe_commands(recipe, env)
        if recipe.build.get("system") == "copy" and not commands:
            copy_source_to_dest(source_dir, destdir)
        elif recipe.build.get("system") == "stage2-stub":
            install_stage2_stub(ctx, recipe, destdir)
        elif recipe.build.get("system") == "host-files":
            install_host_files(ctx, recipe, destdir)
        else:
            for command in commands:
                run_shell(command, env, work, dry_run=False)
            if recipe.build.get("stub"):
                install_stage2_support_files(recipe, destdir)

        create_package(ctx, recipe, destdir, output, key, dep_keys)
        state[name] = make_build_record(ctx, recipe, output, key, dep_keys)
        save_state(ctx, state)


def write_repo_index(ctx: BuildContext) -> None:
    packages_root = ctx.packages_dir / ctx.arch
    packages: list[dict[str, Any]] = []
    current_files: set[str] = set()
    if ctx.recipe_dir.exists():
        recipes = load_recipes(ctx.recipe_dir)
        current_files = {
            package_filename(recipe, ctx.arch)
            for recipe in recipes.values()
            if recipe.supports_arch(ctx.arch)
        }
    if packages_root.exists():
        for path in sorted(packages_root.glob("*.ki2")):
            if current_files and path.name not in current_files:
                continue
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
                    "file_count": manifest.get("payload", {}).get("file_count", len(manifest.get("files", []))),
                }
            )
    packages.sort(key=lambda item: package_manifest_sort_key(item, Path(str(item.get("file", "")))))

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


def assemble_rootfs(ctx: BuildContext, recipes: dict[str, Recipe], ordered: list[str], profile: dict[str, Any] | None = None) -> None:
    if ctx.rootfs_dir is None:
        raise Ki2Error("--rootfs-dir is required for rootfs assembly")
    if ctx.clean_rootfs and ctx.rootfs_dir.exists() and not ctx.dry_run:
        shutil.rmtree(ctx.rootfs_dir)
    if ctx.dry_run:
        print(f"[rootfs] would assemble {ctx.rootfs_dir}")
    else:
        ctx.rootfs_dir.mkdir(parents=True, exist_ok=True)

    missing: list[str] = []
    installed_packages: list[tuple[Path, dict[str, Any]]] = []
    for name in ordered:
        package = package_artifact_for_recipe(ctx, recipes[name])
        if package is None:
            missing.append(name)
            continue
        print(f"[rootfs] {package.name}")
        if ctx.dry_run:
            continue
        manifest = read_package_manifest(package)
        extract_package_rootfs(package, ctx.rootfs_dir)
        installed_packages.append((package, manifest))

    if missing:
        raise Ki2Error("missing package artifacts: " + ", ".join(missing))

    services = profile.get("services", {}) if profile else {}
    if isinstance(services, dict):
        enable = services.get("enable", [])
        if isinstance(enable, list) and not ctx.dry_run:
            enable_systemd_units(ctx.rootfs_dir, [unit for unit in enable if isinstance(unit, str)])
    if not ctx.dry_run:
        write_rootfs_installed_state(ctx.rootfs_dir, installed_packages)


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
        clean_rootfs=getattr(args, "clean_rootfs", False),
        allow_unpinned=args.allow_unpinned,
        verbose=args.verbose,
    )


def command_build(args: argparse.Namespace) -> None:
    recipes = load_recipes(args.recipe_dir)
    profile = load_profile(args.profile)
    validate_recipes(recipes, args.arch, profile, None)
    ordered = dependency_closure(recipes, list(profile["packages"]), args.arch, include_build_deps=True)
    if args.only:
        requested = set(args.only)
        unknown = requested - set(recipes)
        if unknown:
            raise Ki2Error(f"unknown --only package(s): {', '.join(sorted(unknown))}")
        outside_profile = requested - set(ordered)
        if outside_profile:
            raise Ki2Error(f"--only package(s) are not in the selected profile closure: {', '.join(sorted(outside_profile))}")
        ordered = [name for name in ordered if name in requested]
    build_recipes(make_context(args), recipes, ordered)


def command_repo_index(args: argparse.Namespace) -> None:
    write_repo_index(make_context(args))


def command_rootfs(args: argparse.Namespace) -> None:
    recipes = load_recipes(args.recipe_dir)
    profile = load_profile(args.profile)
    ordered = dependency_closure(recipes, list(profile["packages"]), args.arch, include_build_deps=False)
    assemble_rootfs(make_context(args), recipes, ordered, profile)


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
    parser.add_argument("--clean-rootfs", action="store_true", help="remove --rootfs-dir before assembling a rootfs")
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
    build_parser_cmd.add_argument("--only", nargs="+", default=[], help="build only these packages from the selected profile closure")
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
