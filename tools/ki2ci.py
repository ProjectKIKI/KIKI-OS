#!/usr/bin/env python3
"""Small CI/web build console for KIKI OS.

The daemon intentionally uses only Python's standard library so a fresh Rocky
builder can run it before the distribution build environment is mature.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import random
import shutil
import subprocess
import sys
import threading
import urllib.parse
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable


UTC = dt.timezone.utc
DEFAULT_TOOLCHAIN_ID = "host-bootstrap-v0"
JOB_STATUSES = {"pending", "running", "succeeded", "failed"}


@dataclass(frozen=True)
class CiConfig:
    repo_root: Path
    artifact_root: Path
    arch: str
    jobs: int
    toolchain_id: str
    publish_dir: Path


@dataclass(frozen=True)
class Step:
    name: str
    command: list[str]
    allow_failure: bool = False


class CiError(RuntimeError):
    pass


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def now() -> str:
    return dt.datetime.now(UTC).isoformat()


def python_cmd(config: CiConfig, *args: str) -> list[str]:
    return [sys.executable, *args]


def ki2build_cmd(config: CiConfig, *args: str) -> list[str]:
    return python_cmd(
        config,
        "tools/ki2build.py",
        "--repo-root",
        str(config.repo_root),
        "--arch",
        config.arch,
        "--jobs",
        str(config.jobs),
        "--toolchain-id",
        config.toolchain_id,
        *args,
    )


def ki2iso_cmd(config: CiConfig, profile: str) -> list[str]:
    return python_cmd(
        config,
        "tools/ki2iso.py",
        "--repo-root",
        str(config.repo_root),
        "--arch",
        config.arch,
        "--profile",
        profile,
    )


def ki2bootiso_cmd(config: CiConfig, profile: str, *, mode: str = "smoke") -> list[str]:
    return python_cmd(
        config,
        "tools/ki2bootiso.py",
        "--repo-root",
        str(config.repo_root),
        "--arch",
        config.arch,
        "--profile",
        profile,
        "--mode",
        mode,
    )


def ki2publish_cmd(config: CiConfig) -> list[str]:
    return python_cmd(
        config,
        "tools/ki2publish.py",
        "--repo-root",
        str(config.repo_root),
        "--arch",
        config.arch,
        "--target",
        str(config.publish_dir),
    )


def base_smoke_steps(config: CiConfig) -> list[Step]:
    return [
        Step("Go unit tests", ["go", "test", "./cmd/...", "./internal/..."]),
        Step(
            "Python syntax checks",
            python_cmd(
                config,
                "-m",
                "py_compile",
                "tools/ki2build.py",
                "tools/ki2bootiso.py",
                "tools/ki2ci.py",
                "tools/ki2iso.py",
                "tools/ki2publish.py",
                "tools/test_ki2build.py",
                "tools/test_ki2bootiso.py",
                "tools/test_ki2ci.py",
                "tools/test_ki2iso.py",
                "tools/test_ki2publish.py",
            ),
        ),
        Step("ki2build unit tests", python_cmd(config, "tools/test_ki2build.py")),
        Step(
            "Core seed profile validation",
            ki2build_cmd(
                config,
                "validate",
                "--profile",
                "distro/profiles/world.toml",
                "--max-packages",
                "64",
            ),
        ),
        Step(
            "minimal-systemd runtime plan",
            ki2build_cmd(config, "plan", "--profile", "distro/profiles/minimal-systemd.toml"),
        ),
        Step(
            "kiki-kube-node YAML runtime plan",
            ki2build_cmd(config, "plan", "--profile", "distro/profiles/kiki-kube-node.yaml"),
        ),
    ]


def bootstrap_steps(config: CiConfig) -> list[Step]:
    rootfs = config.repo_root / "dist" / "rootfs" / "bootstrap-stage1"
    return [
        Step(
            "Build bootstrap-stage1 packages",
            ki2build_cmd(config, "build", "--profile", "distro/profiles/bootstrap-stage1.toml"),
        ),
        Step("Write package repository index", ki2build_cmd(config, "repo-index")),
        Step(
            "Assemble bootstrap-stage1 rootfs",
            ki2build_cmd(
                config,
                "rootfs",
                "--profile",
                "distro/profiles/bootstrap-stage1.toml",
                "--rootfs-dir",
                str(rootfs),
            ),
        ),
    ]


def minimal_systemd_steps(config: CiConfig) -> list[Step]:
    rootfs = config.repo_root / "dist" / "rootfs" / "minimal-systemd"
    return [
        Step(
            "Build minimal-systemd packages",
            ki2build_cmd(
                config,
                "build",
                "--profile",
                "distro/profiles/minimal-systemd.toml",
                "--allow-unpinned",
            ),
        ),
        Step("Write package repository index", ki2build_cmd(config, "repo-index")),
        Step(
            "Assemble minimal-systemd rootfs",
            ki2build_cmd(
                config,
                "rootfs",
                "--profile",
                "distro/profiles/minimal-systemd.toml",
                "--rootfs-dir",
                str(rootfs),
            ),
        ),
    ]


def iso_steps(config: CiConfig) -> list[Step]:
    return [
        Step("Write package repository index", ki2build_cmd(config, "repo-index")),
        *bootstrap_steps(config)[2:],
        Step("Create bootstrap-stage1 ISO", ki2iso_cmd(config, "bootstrap-stage1")),
    ]


def boot_iso_steps(config: CiConfig) -> list[Step]:
    return [
        Step("Write package repository index", ki2build_cmd(config, "repo-index")),
        *bootstrap_steps(config)[2:],
        Step("Create bootstrap-stage1 bootable ISO", ki2bootiso_cmd(config, "bootstrap-stage1")),
    ]


def installer_iso_steps(config: CiConfig) -> list[Step]:
    return [
        Step("Write package repository index", ki2build_cmd(config, "repo-index")),
        *bootstrap_steps(config)[2:],
        Step(
            "Create bootstrap-stage1 installer ISO",
            ki2bootiso_cmd(config, "bootstrap-stage1", mode="installer"),
        ),
    ]


def security_steps(config: CiConfig) -> list[Step]:
    return [
        Step("Security audit", python_cmd(config, "tools/ki2ci.py", "security-audit", "--repo-root", str(config.repo_root))),
    ]


def publish_steps(config: CiConfig) -> list[Step]:
    return [
        Step("Publish build artifacts", ki2publish_cmd(config)),
    ]


def pipeline_steps(config: CiConfig, name: str) -> list[Step]:
    pipelines: dict[str, Callable[[CiConfig], list[Step]]] = {
        "smoke": base_smoke_steps,
        "bootstrap": lambda cfg: [*base_smoke_steps(cfg), *bootstrap_steps(cfg)],
        "minimal-systemd": lambda cfg: [*base_smoke_steps(cfg), *minimal_systemd_steps(cfg)],
        "security": security_steps,
        "iso": lambda cfg: [*base_smoke_steps(cfg), *iso_steps(cfg)],
        "bootiso": lambda cfg: [*base_smoke_steps(cfg), *boot_iso_steps(cfg)],
        "installer-iso": lambda cfg: [*base_smoke_steps(cfg), *installer_iso_steps(cfg)],
        "publish": publish_steps,
        "release": lambda cfg: [
            *base_smoke_steps(cfg),
            *bootstrap_steps(cfg),
            *security_steps(cfg),
            *iso_steps(cfg),
            *boot_iso_steps(cfg),
            *installer_iso_steps(cfg),
            *publish_steps(cfg),
        ],
    }
    if name not in pipelines:
        raise CiError(f"unknown pipeline {name!r}")
    return pipelines[name](config)


def pipeline_names() -> list[str]:
    return [
        "smoke",
        "bootstrap",
        "minimal-systemd",
        "security",
        "iso",
        "bootiso",
        "installer-iso",
        "publish",
        "release",
    ]


class JobStore:
    def __init__(self, root: Path):
        self.root = root
        self.jobs_dir = root / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def create(self, pipeline: str) -> dict[str, Any]:
        job_id = dt.datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + f"-{random.randrange(1000, 9999)}"
        job_dir = self.jobs_dir / job_id
        job_dir.mkdir()
        job = {
            "id": job_id,
            "pipeline": pipeline,
            "status": "pending",
            "created_at": now(),
            "started_at": None,
            "finished_at": None,
            "exit_code": None,
            "steps": [],
        }
        self.write(job)
        (job_dir / "log.txt").write_text("", encoding="utf-8")
        return job

    def path(self, job_id: str) -> Path:
        return self.jobs_dir / job_id / "metadata.json"

    def log_path(self, job_id: str) -> Path:
        return self.jobs_dir / job_id / "log.txt"

    def read(self, job_id: str) -> dict[str, Any]:
        path = self.path(job_id)
        if not path.exists():
            raise KeyError(job_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def write(self, job: dict[str, Any]) -> None:
        path = self.path(job["id"])
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(job, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)

    def list(self) -> list[dict[str, Any]]:
        jobs = []
        for path in sorted(self.jobs_dir.glob("*/metadata.json"), reverse=True):
            try:
                jobs.append(json.loads(path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
        return jobs


def append_log(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8", errors="replace") as handle:
        handle.write(text)


def run_step(config: CiConfig, step: Step, log_path: Path) -> int:
    append_log(log_path, f"\n==> {step.name}\n")
    append_log(log_path, "+ " + " ".join(step.command) + "\n")
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        step.command,
        cwd=config.repo_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        append_log(log_path, line)
    proc.wait()
    append_log(log_path, f"<== {step.name} exit={proc.returncode}\n")
    return proc.returncode


def run_job(config: CiConfig, store: JobStore, job_id: str, build_lock: threading.Lock | None = None) -> None:
    job = store.read(job_id)
    log_path = store.log_path(job_id)
    steps = pipeline_steps(config, job["pipeline"])

    lock = build_lock or threading.Lock()
    with lock:
        job["status"] = "running"
        job["started_at"] = now()
        job["steps"] = []
        store.write(job)

        exit_code = 0
        for step in steps:
            step_meta = {"name": step.name, "status": "running", "started_at": now(), "finished_at": None, "exit_code": None}
            job["steps"].append(step_meta)
            store.write(job)
            code = run_step(config, step, log_path)
            step_meta["finished_at"] = now()
            step_meta["exit_code"] = code
            step_meta["status"] = "succeeded" if code == 0 else "failed"
            store.write(job)
            if code != 0 and not step.allow_failure:
                exit_code = code
                break

        job["exit_code"] = exit_code
        job["finished_at"] = now()
        job["status"] = "succeeded" if exit_code == 0 else "failed"
        store.write(job)


def load_ki2build_module(repo_root: Path):
    sys.path.insert(0, str(repo_root / "tools"))
    import ki2build  # type: ignore[import-not-found]

    return ki2build


def shell_script_paths(repo_root: Path) -> list[Path]:
    paths: list[Path] = []
    for root in ("distro", "tools", "deploy"):
        base = repo_root / root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix == ".sh":
                paths.append(path)
                continue
            try:
                first = path.read_text(encoding="utf-8", errors="ignore").splitlines()[:1]
            except OSError:
                continue
            if first and first[0].startswith(("#!/bin/sh", "#!/usr/bin/env sh", "#!/bin/bash", "#!/usr/bin/env bash")):
                paths.append(path)
    return sorted(set(paths))


def security_audit(repo_root: Path, *, strict_pins: bool = False) -> int:
    errors: list[str] = []
    warnings: list[str] = []

    print("KIKI security audit")
    print("===================")

    try:
        ki2build = load_ki2build_module(repo_root)
        recipes = ki2build.load_recipes(repo_root / "distro" / "recipes")
        unpinned = []
        for recipe in recipes.values():
            if recipe.source.get("type") == "url" and str(recipe.source.get("sha256", "")) in ki2build.PIN_PLACEHOLDERS:
                unpinned.append(recipe.name)
        if unpinned:
            message = f"unpinned source hashes: {', '.join(sorted(unpinned))}"
            if strict_pins:
                errors.append(message)
            else:
                warnings.append(message)
        print(f"recipes: {len(recipes)}")
    except Exception as exc:  # noqa: BLE001 - audit should report every failure.
        errors.append(f"recipe audit failed: {exc}")

    bash = shutil.which("bash")
    scripts = shell_script_paths(repo_root)
    print(f"shell scripts: {len(scripts)}")
    if bash:
        for script in scripts:
            proc = subprocess.run([bash, "-n", str(script)], cwd=repo_root, text=True, capture_output=True)
            if proc.returncode != 0:
                errors.append(f"shell syntax failed: {script.relative_to(repo_root)}\n{proc.stderr}")
    elif scripts:
        warnings.append("bash is not installed; shell syntax audit skipped")

    optional_tools = [
        "shellcheck",
        "gosec",
        "govulncheck",
        "trivy",
        "grype",
        "syft",
        "bandit",
        "pip-audit",
        "xorriso",
        "grub-mkrescue",
        "grub2-mkrescue",
        "gcc",
    ]
    present = [tool for tool in optional_tools if shutil.which(tool)]
    missing = [tool for tool in optional_tools if not shutil.which(tool)]
    print("optional scanners present:", ", ".join(present) if present else "(none)")
    if missing:
        warnings.append("optional scanners missing: " + ", ".join(missing))

    package_root = repo_root / "dist" / "ki2" / "packages"
    if package_root.exists():
        manifests = list(package_root.rglob("*.ki2"))
        print(f"package artifacts: {len(manifests)}")
    else:
        warnings.append("no package artifact directory yet")

    for warning in warnings:
        print("warning:", warning)
    for error in errors:
        print("error:", error)
    return 1 if errors else 0


def relative_path(repo_root: Path, path: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return str(path)


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def scanner_inventory() -> dict[str, list[str]]:
    tools = [
        "shellcheck",
        "gosec",
        "govulncheck",
        "trivy",
        "grype",
        "syft",
        "bandit",
        "pip-audit",
        "xorriso",
        "grub-mkrescue",
        "grub2-mkrescue",
        "gcc",
    ]
    return {
        "present": [tool for tool in tools if shutil.which(tool)],
        "missing": [tool for tool in tools if not shutil.which(tool)],
    }


def package_artifacts(config: CiConfig) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    package_root = config.repo_root / "dist" / "ki2" / "packages" / config.arch
    if not package_root.exists():
        return artifacts

    ki2build = load_ki2build_module(config.repo_root)
    for path in sorted(package_root.glob("*.ki2")):
        try:
            manifest = ki2build.read_package_manifest(path)
        except Exception:  # noqa: BLE001 - bad package artifacts should not break dashboard.
            continue
        name = manifest.get("name")
        if not name:
            continue
        artifacts[str(name)] = {
            "path": relative_path(config.repo_root, path),
            "size": path.stat().st_size,
            "size_display": format_size(path.stat().st_size),
            "build_key": manifest.get("build_key", ""),
            "built_at": manifest.get("built_at", ""),
            "file_count": manifest.get("payload", {}).get("file_count", len(manifest.get("files", []))),
        }
    return artifacts


def collect_packages(config: CiConfig) -> list[dict[str, Any]]:
    ki2build = load_ki2build_module(config.repo_root)
    recipes = ki2build.load_recipes(config.repo_root / "distro" / "recipes")
    artifacts = package_artifacts(config)
    packages = []
    for recipe in sorted(recipes.values(), key=lambda item: (item.tier, item.name)):
        source_type = recipe.source.get("type", "")
        sha = str(recipe.source.get("sha256", ""))
        pinned = source_type != "url" or sha not in ki2build.PIN_PLACEHOLDERS
        artifact = artifacts.get(recipe.name)
        packages.append(
            {
                "name": recipe.name,
                "version": recipe.version,
                "release": recipe.release,
                "tier": recipe.tier,
                "summary": recipe.summary,
                "license": recipe.license,
                "source_type": source_type,
                "pinned": pinned,
                "runtime_dependencies": recipe.dependencies.get("runtime", []),
                "build_dependencies": recipe.dependencies.get("build", []),
                "artifact": artifact,
                "built": artifact is not None,
            }
        )
    return packages


def collect_profiles(config: CiConfig) -> list[dict[str, Any]]:
    ki2build = load_ki2build_module(config.repo_root)
    recipes = ki2build.load_recipes(config.repo_root / "distro" / "recipes")
    profiles = []
    profile_root = config.repo_root / "distro" / "profiles"
    profile_paths = sorted([*profile_root.glob("*.toml"), *profile_root.glob("*.yaml"), *profile_root.glob("*.yml")])
    for path in profile_paths:
        profile = ki2build.load_profile(path)
        roots = list(profile.get("packages", []))
        runtime_plan = ki2build.dependency_closure(recipes, roots, config.arch, include_build_deps=False)
        build_plan = ki2build.dependency_closure(recipes, roots, config.arch, include_build_deps=True)
        profiles.append(
            {
                "name": profile["name"],
                "description": profile.get("description", ""),
                "path": relative_path(config.repo_root, path),
                "roots": roots,
                "runtime_count": len(runtime_plan),
                "build_count": len(build_plan),
                "runtime_plan": runtime_plan,
                "build_plan": build_plan,
            }
        )
    return profiles


def collect_artifacts(config: CiConfig) -> dict[str, Any]:
    package_root = config.repo_root / "dist" / "ki2" / "packages" / config.arch
    rootfs_root = config.repo_root / "dist" / "rootfs"
    iso_root = config.repo_root / "dist" / "iso"
    repo_index = config.repo_root / "dist" / "ki2" / "repo" / f"index.{config.arch}.json"
    publish_manifest = config.publish_dir / "manifest.json"

    packages = []
    if package_root.exists():
        for path in sorted(package_root.glob("*.ki2")):
            packages.append(
                {
                    "name": path.name,
                    "path": relative_path(config.repo_root, path),
                    "size": path.stat().st_size,
                    "size_display": format_size(path.stat().st_size),
                    "modified": dt.datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
                }
            )

    rootfs = []
    if rootfs_root.exists():
        for path in sorted(rootfs_root.iterdir()):
            if path.is_dir():
                rootfs.append({"name": path.name, "path": relative_path(config.repo_root, path)})

    isos = []
    disk_images = []
    if iso_root.exists():
        for path in sorted(iso_root.glob("*.iso")):
            isos.append(
                {
                    "name": path.name,
                    "path": relative_path(config.repo_root, path),
                    "size": path.stat().st_size,
                    "size_display": format_size(path.stat().st_size),
                    "modified": dt.datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
                }
            )
        for pattern in ("*.img", "*.vhdx"):
            for path in sorted(iso_root.glob(pattern)):
                disk_images.append(
                    {
                        "name": path.name,
                        "path": relative_path(config.repo_root, path),
                        "size": path.stat().st_size,
                        "size_display": format_size(path.stat().st_size),
                        "modified": dt.datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
                    }
                )

    index = read_json(repo_index)
    return {
        "packages": packages,
        "package_count": len(packages),
        "rootfs": rootfs,
        "isos": isos,
        "disk_images": disk_images,
        "repo_index": relative_path(config.repo_root, repo_index) if repo_index.exists() else None,
        "repo_package_count": len(index.get("packages", [])) if index else 0,
        "publish_dir": str(config.publish_dir),
        "publish_manifest": str(publish_manifest) if publish_manifest.exists() else None,
    }


def collect_security(config: CiConfig) -> dict[str, Any]:
    packages = collect_packages(config)
    unpinned = [pkg["name"] for pkg in packages if not pkg["pinned"]]
    inventory = scanner_inventory()
    return {
        "unpinned_sources": unpinned,
        "unpinned_count": len(unpinned),
        "scanners_present": inventory["present"],
        "scanners_missing": inventory["missing"],
        "shell_scripts": [relative_path(config.repo_root, path) for path in shell_script_paths(config.repo_root)],
    }


def collect_overview(config: CiConfig, store: JobStore) -> dict[str, Any]:
    jobs = store.list()
    status_counts = {status: 0 for status in JOB_STATUSES}
    for job in jobs:
        status_counts[job.get("status", "pending")] = status_counts.get(job.get("status", "pending"), 0) + 1
    packages = collect_packages(config)
    profiles = collect_profiles(config)
    artifacts = collect_artifacts(config)
    security = collect_security(config)
    return {
        "jobs": jobs[:8],
        "job_counts": status_counts,
        "package_count": len(packages),
        "built_package_count": sum(1 for pkg in packages if pkg["built"]),
        "profile_count": len(profiles),
        "artifact_package_count": artifacts["package_count"],
        "iso_count": len(artifacts["isos"]),
        "security": security,
        "config": {
            "arch": config.arch,
            "jobs": config.jobs,
            "toolchain_id": config.toolchain_id,
            "repo_root": str(config.repo_root),
            "artifact_root": str(config.artifact_root),
            "publish_dir": str(config.publish_dir),
        },
    }


def html_escape(value: Any) -> str:
    return html.escape(str(value))


def nav(active: str) -> str:
    items = [
        ("/", "Dashboard"),
        ("/jobs", "Jobs"),
        ("/packages", "Packages"),
        ("/profiles", "Profiles"),
        ("/artifacts", "Artifacts"),
        ("/security", "Security"),
        ("/deploy", "Deploy"),
    ]
    return "<nav>" + "".join(
        f"<a class='{('active' if key == active else '')}' href='{href}'>{label}</a>" for href, label in items for key in [href]
    ) + "</nav>"


def metric(label: str, value: Any, tone: str = "") -> str:
    return f"<div class='metric {tone}'><div class='metric-value'>{html_escape(value)}</div><div class='metric-label'>{html_escape(label)}</div></div>"


def render_page(title: str, body: str, *, active: str = "/") -> bytes:
    css = """
body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f4f6f8;color:#1f252e}
header{background:#20242c;color:white;padding:18px 28px}
header h1{margin:0;font-size:22px;letter-spacing:0}
nav{display:flex;gap:4px;flex-wrap:wrap;background:#2a303a;padding:0 24px}
nav a{color:#dce3ee;text-decoration:none;padding:12px 13px;border-bottom:3px solid transparent}
nav a.active{color:white;border-bottom-color:#65a30d}
main{padding:24px;max-width:1280px;margin:auto}
h2{font-size:18px;margin:0 0 12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
.bar{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}
button,.button{border:0;background:#1f5fbf;color:white;padding:9px 12px;border-radius:6px;cursor:pointer;text-decoration:none;display:inline-block}
button.secondary,.button.secondary{background:#475467}
.panel{background:white;border:1px solid #d9dee7;border-radius:8px;padding:16px;margin:14px 0}
.metric{background:white;border:1px solid #d9dee7;border-radius:8px;padding:14px;min-height:72px}
.metric-value{font-size:26px;font-weight:700;line-height:1.1}.metric-label{color:#667085;margin-top:5px;font-size:13px}
table{width:100%;border-collapse:collapse;background:white}
th,td{border-bottom:1px solid #e5e8ef;text-align:left;padding:10px;vertical-align:top}
th{font-size:12px;text-transform:uppercase;color:#667085;background:#fafbfc}
.status{font-weight:700}.succeeded{color:#16703a}.failed{color:#b42318}.running{color:#985a00}.pending{color:#4d5968}
.pill{display:inline-block;border:1px solid #d0d5dd;border-radius:999px;padding:2px 8px;margin:1px 3px 1px 0;background:#f9fafb;font-size:12px}
.bad{color:#b42318}.good{color:#16703a}.muted{color:#667085}
pre{white-space:pre-wrap;background:#10141b;color:#e8edf4;padding:14px;border-radius:8px;overflow:auto;max-height:70vh}
small{color:#667085}
"""
    return f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title><style>{css}</style></head><body><header><h1>{html.escape(title)}</h1></header>{nav(active)}<main>{body}</main></body></html>".encode("utf-8")


class BuildServer:
    def __init__(self, config: CiConfig):
        self.config = config
        self.store = JobStore(config.artifact_root)
        self.lock = threading.Lock()

    def submit(self, pipeline: str) -> dict[str, Any]:
        if pipeline not in pipeline_names():
            raise CiError(f"unknown pipeline {pipeline!r}")
        job = self.store.create(pipeline)
        thread = threading.Thread(target=run_job, args=(self.config, self.store, job["id"], self.lock), daemon=True)
        thread.start()
        return job


def make_handler(server: BuildServer):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/":
                self.send_html(self.dashboard_page())
                return
            if parsed.path == "/jobs":
                self.send_html(self.jobs_page())
                return
            if parsed.path == "/packages":
                self.send_html(self.packages_page())
                return
            if parsed.path == "/profiles":
                self.send_html(self.profiles_page())
                return
            if parsed.path == "/artifacts":
                self.send_html(self.artifacts_page())
                return
            if parsed.path == "/security":
                self.send_html(self.security_page())
                return
            if parsed.path == "/deploy":
                self.send_html(self.deploy_page())
                return
            if parsed.path == "/api/jobs":
                self.send_json(server.store.list())
                return
            if parsed.path == "/api/overview":
                self.send_json(collect_overview(server.config, server.store))
                return
            if parsed.path == "/api/packages":
                self.send_json(collect_packages(server.config))
                return
            if parsed.path == "/api/profiles":
                self.send_json(collect_profiles(server.config))
                return
            if parsed.path == "/api/artifacts":
                self.send_json(collect_artifacts(server.config))
                return
            if parsed.path == "/api/security":
                self.send_json(collect_security(server.config))
                return
            if parsed.path.startswith("/jobs/"):
                job_id = parsed.path.removeprefix("/jobs/")
                try:
                    self.send_html(self.job_page(job_id))
                except KeyError:
                    self.send_error(HTTPStatus.NOT_FOUND, "job not found")
                return
            if parsed.path.startswith("/api/jobs/"):
                job_id = parsed.path.removeprefix("/api/jobs/")
                try:
                    self.send_json(server.store.read(job_id))
                except KeyError:
                    self.send_error(HTTPStatus.NOT_FOUND, "job not found")
                return
            self.send_error(HTTPStatus.NOT_FOUND, "not found")

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/jobs":
                self.send_error(HTTPStatus.NOT_FOUND, "not found")
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            data = urllib.parse.parse_qs(body)
            pipeline = data.get("pipeline", [""])[0]
            try:
                job = server.submit(pipeline)
            except CiError as exc:
                self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", f"/jobs/{job['id']}")
            self.end_headers()

        def send_json(self, data: Any) -> None:
            body = json.dumps(data, indent=2, sort_keys=True).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_html(self, body: bytes) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def pipeline_forms(self) -> str:
            forms = "".join(
                f"<form method='post' action='/jobs'><input type='hidden' name='pipeline' value='{name}'><button>{name}</button></form>"
                for name in pipeline_names()
            )
            return f"<div class='bar'>{forms}</div>"

        def jobs_table(self, limit: int | None = None) -> str:
            rows = []
            jobs = server.store.list()
            if limit is not None:
                jobs = jobs[:limit]
            for job in jobs:
                status = html.escape(job["status"])
                rows.append(
                    "<tr>"
                    f"<td><a href='/jobs/{html.escape(job['id'])}'>{html.escape(job['id'])}</a></td>"
                    f"<td>{html.escape(job['pipeline'])}</td>"
                    f"<td class='status {status}'>{status}</td>"
                    f"<td><small>{html.escape(str(job.get('created_at')))}</small></td>"
                    "</tr>"
                )
            if not rows:
                rows.append("<tr><td colspan='4' class='muted'>No jobs yet</td></tr>")
            return "<table><tr><th>Job</th><th>Pipeline</th><th>Status</th><th>Created</th></tr>" + "".join(rows) + "</table>"

        def dashboard_page(self) -> bytes:
            overview = collect_overview(server.config, server.store)
            security = overview["security"]
            body = (
                "<div class='grid'>"
                + metric("Packages", overview["package_count"])
                + metric("Built", f"{overview['built_package_count']}/{overview['package_count']}")
                + metric("Profiles", overview["profile_count"])
                + metric("ISOs", overview["iso_count"])
                + metric("Unpinned", security["unpinned_count"], "bad" if security["unpinned_count"] else "good")
                + "</div>"
                + "<div class='panel'><h2>Pipelines</h2>"
                + self.pipeline_forms()
                + "</div>"
                + "<div class='panel'><h2>Recent Jobs</h2>"
                + self.jobs_table(limit=8)
                + "</div>"
                + "<div class='panel'><h2>Builder</h2>"
                + "<table>"
                + f"<tr><th>Arch</th><td>{html_escape(overview['config']['arch'])}</td></tr>"
                + f"<tr><th>Jobs</th><td>{html_escape(overview['config']['jobs'])}</td></tr>"
                + f"<tr><th>Toolchain</th><td>{html_escape(overview['config']['toolchain_id'])}</td></tr>"
                + f"<tr><th>Repo Root</th><td>{html_escape(overview['config']['repo_root'])}</td></tr>"
                + f"<tr><th>Publish Dir</th><td>{html_escape(overview['config']['publish_dir'])}</td></tr>"
                + "</table></div>"
            )
            return render_page("KIKI Operations Dashboard", body, active="/")

        def jobs_page(self) -> bytes:
            body = "<div class='panel'><h2>Run Pipeline</h2>" + self.pipeline_forms() + "</div><div class='panel'><h2>Jobs</h2>" + self.jobs_table() + "</div>"
            return render_page("KIKI Jobs", body, active="/jobs")

        def packages_page(self) -> bytes:
            rows = []
            for pkg in collect_packages(server.config):
                runtime = "".join(f"<span class='pill'>{html_escape(dep)}</span>" for dep in pkg["runtime_dependencies"]) or "<span class='muted'>none</span>"
                build = "".join(f"<span class='pill'>{html_escape(dep)}</span>" for dep in pkg["build_dependencies"]) or "<span class='muted'>none</span>"
                pin = "<span class='good'>pinned</span>" if pkg["pinned"] else "<span class='bad'>unpinned</span>"
                artifact = pkg["artifact"]["size_display"] if pkg["artifact"] else "<span class='muted'>missing</span>"
                file_count = str(pkg["artifact"]["file_count"]) if pkg["artifact"] else "<span class='muted'>n/a</span>"
                rows.append(
                    "<tr>"
                    f"<td><b>{html_escape(pkg['name'])}</b><br><small>{html_escape(pkg['summary'])}</small></td>"
                    f"<td>{html_escape(pkg['version'])}-{html_escape(pkg['release'])}</td>"
                    f"<td>{html_escape(pkg['tier'])}</td>"
                    f"<td>{runtime}</td>"
                    f"<td>{build}</td>"
                    f"<td>{pin}</td>"
                    f"<td>{artifact}</td>"
                    f"<td>{file_count}</td>"
                    "</tr>"
                )
            table = "<table><tr><th>Package</th><th>Version</th><th>Tier</th><th>Runtime</th><th>Build</th><th>Source</th><th>Artifact</th><th>Files</th></tr>" + "".join(rows) + "</table>"
            return render_page("KIKI Packages", "<div class='panel'>" + table + "</div>", active="/packages")

        def profiles_page(self) -> bytes:
            rows = []
            for profile in collect_profiles(server.config):
                roots = "".join(f"<span class='pill'>{html_escape(root)}</span>" for root in profile["roots"])
                rows.append(
                    "<tr>"
                    f"<td><b>{html_escape(profile['name'])}</b><br><small>{html_escape(profile['path'])}</small></td>"
                    f"<td>{html_escape(profile['description'])}</td>"
                    f"<td>{roots}</td>"
                    f"<td>{html_escape(profile['runtime_count'])}</td>"
                    f"<td>{html_escape(profile['build_count'])}</td>"
                    "</tr>"
                )
            table = "<table><tr><th>Profile</th><th>Description</th><th>Roots</th><th>Runtime Plan</th><th>Build Plan</th></tr>" + "".join(rows) + "</table>"
            return render_page("KIKI Profiles", "<div class='panel'>" + table + "</div>", active="/profiles")

        def artifacts_page(self) -> bytes:
            artifacts = collect_artifacts(server.config)
            package_rows = "".join(
                f"<tr><td>{html_escape(item['name'])}</td><td>{html_escape(item['size_display'])}</td><td><small>{html_escape(item['path'])}</small></td></tr>"
                for item in artifacts["packages"]
            ) or "<tr><td colspan='3' class='muted'>No packages</td></tr>"
            iso_rows = "".join(
                f"<tr><td>{html_escape(item['name'])}</td><td>{html_escape(item['size_display'])}</td><td><small>{html_escape(item['path'])}</small></td></tr>"
                for item in artifacts["isos"]
            ) or "<tr><td colspan='3' class='muted'>No ISO images</td></tr>"
            disk_image_rows = "".join(
                f"<tr><td>{html_escape(item['name'])}</td><td>{html_escape(item['size_display'])}</td><td><small>{html_escape(item['path'])}</small></td></tr>"
                for item in artifacts["disk_images"]
            ) or "<tr><td colspan='3' class='muted'>No disk images</td></tr>"
            rootfs_rows = "".join(
                f"<tr><td>{html_escape(item['name'])}</td><td><small>{html_escape(item['path'])}</small></td></tr>"
                for item in artifacts["rootfs"]
            ) or "<tr><td colspan='2' class='muted'>No rootfs directories</td></tr>"
            body = (
                "<div class='grid'>"
                + metric("Package Artifacts", artifacts["package_count"])
                + metric("Repo Packages", artifacts["repo_package_count"])
                + metric("Rootfs Trees", len(artifacts["rootfs"]))
                + metric("ISO Images", len(artifacts["isos"]))
                + metric("Disk Images", len(artifacts["disk_images"]))
                + "</div>"
                + "<div class='panel'><h2>Publish</h2><table>"
                + f"<tr><th>Target</th><td>{html_escape(artifacts['publish_dir'])}</td></tr>"
                + f"<tr><th>Manifest</th><td>{html_escape(artifacts['publish_manifest'] or 'not published')}</td></tr>"
                + "</table></div>"
                + "<div class='panel'><h2>Packages</h2><table><tr><th>Name</th><th>Size</th><th>Path</th></tr>"
                + package_rows
                + "</table></div>"
                + "<div class='panel'><h2>ISO</h2><table><tr><th>Name</th><th>Size</th><th>Path</th></tr>"
                + iso_rows
                + "</table></div>"
                + "<div class='panel'><h2>Disk Images</h2><table><tr><th>Name</th><th>Size</th><th>Path</th></tr>"
                + disk_image_rows
                + "</table></div>"
                + "<div class='panel'><h2>Rootfs</h2><table><tr><th>Name</th><th>Path</th></tr>"
                + rootfs_rows
                + "</table></div>"
            )
            return render_page("KIKI Artifacts", body, active="/artifacts")

        def security_page(self) -> bytes:
            security = collect_security(server.config)
            unpinned = "".join(f"<span class='pill bad'>{html_escape(name)}</span>" for name in security["unpinned_sources"]) or "<span class='good'>none</span>"
            present = "".join(f"<span class='pill good'>{html_escape(name)}</span>" for name in security["scanners_present"]) or "<span class='muted'>none</span>"
            missing = "".join(f"<span class='pill'>{html_escape(name)}</span>" for name in security["scanners_missing"]) or "<span class='good'>none</span>"
            scripts = "".join(f"<tr><td><small>{html_escape(path)}</small></td></tr>" for path in security["shell_scripts"])
            body = (
                "<div class='grid'>"
                + metric("Unpinned Sources", security["unpinned_count"], "bad" if security["unpinned_count"] else "good")
                + metric("Scanners Present", len(security["scanners_present"]))
                + metric("Shell Scripts", len(security["shell_scripts"]))
                + "</div>"
                + "<div class='panel'><h2>Source Pins</h2>"
                + unpinned
                + "</div><div class='panel'><h2>Scanners</h2><p>Present: "
                + present
                + "</p><p>Missing: "
                + missing
                + "</p></div><div class='panel'><h2>Shell Scripts</h2><table>"
                + scripts
                + "</table></div>"
            )
            return render_page("KIKI Security", body, active="/security")

        def deploy_page(self) -> bytes:
            body = (
                "<div class='panel'><h2>Server Units</h2>"
                "<table>"
                "<tr><th>Build Console</th><td><code>deploy/systemd/kiki-buildd.service</code></td></tr>"
                "<tr><th>Nightly Build</th><td><code>deploy/systemd/kiki-bootstrap-nightly.service</code></td></tr>"
                "<tr><th>Nightly Timer</th><td><code>deploy/systemd/kiki-bootstrap-nightly.timer</code></td></tr>"
                "<tr><th>SVN Hook</th><td><code>deploy/svn/post-commit.sample</code></td></tr>"
                "</table></div>"
                "<div class='panel'><h2>Publish Targets</h2>"
                "<table>"
                "<tr><th>Package Repo</th><td><code>dist/ki2/repo/</code></td></tr>"
                "<tr><th>Packages</th><td><code>dist/ki2/packages/</code></td></tr>"
                "<tr><th>ISO</th><td><code>dist/iso/</code></td></tr>"
                "<tr><th>Publish</th><td><code>dist/publish/</code></td></tr>"
                "</table></div>"
                "<div class='panel'><h2>APIs</h2>"
                "<table>"
                "<tr><th>Overview</th><td><code>/api/overview</code></td></tr>"
                "<tr><th>Jobs</th><td><code>/api/jobs</code></td></tr>"
                "<tr><th>Packages</th><td><code>/api/packages</code></td></tr>"
                "<tr><th>Profiles</th><td><code>/api/profiles</code></td></tr>"
                "<tr><th>Artifacts</th><td><code>/api/artifacts</code></td></tr>"
                "<tr><th>Security</th><td><code>/api/security</code></td></tr>"
                "</table></div>"
            )
            return render_page("KIKI Deploy", body, active="/deploy")

        def job_page(self, job_id: str) -> bytes:
            job = server.store.read(job_id)
            log_path = server.store.log_path(job_id)
            log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
            status = html.escape(job["status"])
            refresh = "<meta http-equiv='refresh' content='5'>" if job["status"] in {"pending", "running"} else ""
            steps = "".join(
                f"<tr><td>{html.escape(step['name'])}</td><td class='status {html.escape(step['status'])}'>{html.escape(step['status'])}</td><td>{html.escape(str(step.get('exit_code')))}</td></tr>"
                for step in job.get("steps", [])
            )
            body = (
                refresh
                + f"<a class='button secondary' href='/jobs'>Back</a><div class='panel'><h2>{html.escape(job_id)}</h2>"
                + f"<p>Pipeline: <b>{html.escape(job['pipeline'])}</b> Status: <b class='status {status}'>{status}</b></p>"
                + "<table><tr><th>Step</th><th>Status</th><th>Exit</th></tr>"
                + steps
                + "</table></div><div class='panel'><h2>Log</h2><pre>"
                + html.escape(log[-120000:])
                + "</pre></div>"
            )
            return render_page("KIKI Build Job", body, active="/jobs")

        def log_message(self, format: str, *args: Any) -> None:
            print(f"{self.address_string()} - {format % args}")

    return Handler


def make_config(args: argparse.Namespace) -> CiConfig:
    repo_root = args.repo_root.resolve()
    artifact_root = (args.artifact_root or repo_root / "build" / "ki2ci").resolve()
    publish_dir = (args.publish_dir or repo_root / "dist" / "publish").resolve()
    return CiConfig(
        repo_root=repo_root,
        artifact_root=artifact_root,
        arch=args.arch,
        jobs=args.jobs or max(os.cpu_count() or 1, 1),
        toolchain_id=args.toolchain_id,
        publish_dir=publish_dir,
    )


def command_run(args: argparse.Namespace) -> None:
    config = make_config(args)
    store = JobStore(config.artifact_root)
    job = store.create(args.pipeline)
    run_job(config, store, job["id"])
    print(f"job: {job['id']}")
    print(f"log: {store.log_path(job['id'])}")
    result = store.read(job["id"])
    raise SystemExit(int(result["exit_code"] or 0))


def command_serve(args: argparse.Namespace) -> None:
    config = make_config(args)
    server = BuildServer(config)
    httpd = ThreadingHTTPServer((args.host, args.port), make_handler(server))
    print(f"KIKI Build Console: http://{args.host}:{args.port}")
    print("No authentication is built in; bind to localhost or protect it with a reverse proxy.")
    httpd.serve_forever()


def command_list(args: argparse.Namespace) -> None:
    config = make_config(args)
    store = JobStore(config.artifact_root)
    for job in store.list():
        print(f"{job['id']} {job['pipeline']} {job['status']}")


def command_show(args: argparse.Namespace) -> None:
    config = make_config(args)
    store = JobStore(config.artifact_root)
    print(json.dumps(store.read(args.job_id), indent=2, sort_keys=True))
    print(store.log_path(args.job_id).read_text(encoding="utf-8", errors="replace"))


def command_security_audit(args: argparse.Namespace) -> None:
    raise SystemExit(security_audit(args.repo_root.resolve(), strict_pins=args.strict_pins))


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-root", type=Path, default=default_repo_root())
    parser.add_argument("--artifact-root", type=Path, default=None)
    parser.add_argument("--arch", default="x86_64")
    parser.add_argument("--jobs", type=int, default=None)
    parser.add_argument("--toolchain-id", default=os.environ.get("KIKI_TOOLCHAIN_ID", DEFAULT_TOOLCHAIN_ID))
    parser.add_argument("--publish-dir", type=Path, default=Path(os.environ["KIKI_PUBLISH_DIR"]) if os.environ.get("KIKI_PUBLISH_DIR") else None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="KIKI OS build automation and web console")
    subcommands = parser.add_subparsers(dest="command", required=True)

    run = subcommands.add_parser("run", help="run a pipeline synchronously")
    add_common(run)
    run.add_argument("pipeline", choices=pipeline_names())
    run.set_defaults(func=command_run)

    serve = subcommands.add_parser("serve", help="serve the build web console")
    add_common(serve)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8090)
    serve.set_defaults(func=command_serve)

    list_jobs = subcommands.add_parser("list-jobs", help="list known jobs")
    add_common(list_jobs)
    list_jobs.set_defaults(func=command_list)

    show_job = subcommands.add_parser("show-job", help="show job metadata and log")
    add_common(show_job)
    show_job.add_argument("job_id")
    show_job.set_defaults(func=command_show)

    audit = subcommands.add_parser("security-audit", help="run repository security checks")
    audit.add_argument("--repo-root", type=Path, default=default_repo_root())
    audit.add_argument("--strict-pins", action="store_true")
    audit.set_defaults(func=command_security_audit)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except CiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
