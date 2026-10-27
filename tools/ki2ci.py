#!/usr/bin/env python3
"""Small CI/web build console for KIKI OS.

The daemon intentionally uses only Python's standard library so a fresh Rocky
builder can run it before the distribution build environment is mature.
"""

from __future__ import annotations

import argparse
import codecs
import datetime as dt
import html
import json
import os
import queue
import random
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
from dataclasses import dataclass, replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from ki2git import GitSources, GitError
from ki2git_views import git_page, source_summary


UTC = dt.timezone.utc
DEFAULT_TOOLCHAIN_ID = "host-bootstrap-v0"
JOB_STATUSES = {"pending", "running", "succeeded", "failed", "cancelled", "interrupted"}
TERMINAL_STATUSES = JOB_STATUSES - {"pending", "running"}


@dataclass(frozen=True)
class CiConfig:
    repo_root: Path
    artifact_root: Path
    arch: str
    jobs: int
    toolchain_id: str
    publish_dir: Path
    git_url: str | None = None
    git_branch: str = "stage3"


@dataclass(frozen=True)
class Step:
    name: str
    command: list[str]
    allow_failure: bool = False


class CiError(RuntimeError):
    pass


class BuilderLease:
    """One console/CLI runner owns an artifact root; OS releases it on exit."""

    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.handle = (root / "builder.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                if self.handle.tell() == 0:
                    self.handle.write(b"\0")
                    self.handle.flush()
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            raise CiError(f"another build console or CLI runner owns {root}") from exc

    def close(self) -> None:
        self.handle.close()


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


def ki2repo_cmd(config: CiConfig, *args: str) -> list[str]:
    return python_cmd(
        config,
        "tools/ki2repo.py",
        "--repo-root",
        str(config.repo_root),
        "--arch",
        config.arch,
        *args,
    )


def stage2_repo_signing_key(config: CiConfig) -> Path:
    return config.artifact_root / "keys" / "stage2-v2-repo.hmac"


def stage2_rootfs_dir(config: CiConfig, profile: str) -> Path:
    if os.name == "posix":
        return Path(os.environ.get("TMPDIR", "/tmp")) / "kiki-ki2ci" / config.artifact_root.name / "rootfs" / profile
    return config.artifact_root / "rootfs" / profile


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
                "tools/kiki_console.py",
                "tools/ki2osbuild.py",
                "tools/ki2publish.py",
                "tools/ki2repo.py",
                "tools/ki2stage2.py",
                "tools/test_ki2build.py",
                "tools/test_ki2bootiso.py",
                "tools/test_ki2ci.py",
                "tools/test_ki2ci_execution.py",
                "tools/test_ki2ctl.py",
                "tools/test_ki2iso.py",
                "tools/test_kiki_console.py",
                "tools/test_ki2osbuild.py",
                "tools/test_ki2publish.py",
                "tools/test_ki2repo.py",
                "tools/test_ki2stage2.py",
            ),
        ),
        Step("ki2build unit tests", python_cmd(config, "tools/test_ki2build.py")),
        Step("ki2bootiso unit tests", python_cmd(config, "tools/test_ki2bootiso.py")),
        Step("ki2ctl unit tests", python_cmd(config, "tools/test_ki2ctl.py")),
        Step("ki2repo unit tests", python_cmd(config, "tools/test_ki2repo.py")),
        Step("ki2stage2 unit tests", python_cmd(config, "tools/test_ki2stage2.py")),
        Step("ki2ci unit tests", python_cmd(config, "tools/test_ki2ci.py")),
        Step("ki2ci queue and execution tests", python_cmd(config, "tools/test_ki2ci_execution.py")),
        Step("KIKI management console unit tests", python_cmd(config, "tools/test_kiki_console.py")),
        Step("KIKI OS build orchestrator unit tests", python_cmd(config, "tools/test_ki2osbuild.py")),
        Step(
            "Core seed profile validation",
            ki2build_cmd(
                config,
                "validate",
                "--profile",
                "distro/profiles/world.toml",
                "--max-packages",
                "72",
            ),
        ),
        Step(
            "minimal-systemd runtime plan",
            ki2build_cmd(config, "plan", "--profile", "distro/profiles/minimal-systemd.toml"),
        ),
        Step(
            "kiki-kube-bootstrap CRI-O runtime plan",
            ki2build_cmd(config, "plan", "--profile", "distro/profiles/kiki-kube-bootstrap.yaml"),
        ),
        Step(
            "kiki-kube-control CRI-O runtime plan",
            ki2build_cmd(config, "plan", "--profile", "distro/profiles/kiki-kube-control.yaml"),
        ),
        Step(
            "kiki-kube-compute CRI-O runtime plan",
            ki2build_cmd(config, "plan", "--profile", "distro/profiles/kiki-kube-compute.yaml"),
        ),
        Step(
            "kiki-kube-bootstrap containerd runtime plan",
            ki2build_cmd(config, "plan", "--profile", "distro/profiles/kiki-kube-bootstrap-containerd.yaml"),
        ),
        Step(
            "kiki-kube-control containerd runtime plan",
            ki2build_cmd(config, "plan", "--profile", "distro/profiles/kiki-kube-control-containerd.yaml"),
        ),
        Step(
            "kiki-kube-compute containerd runtime plan",
            ki2build_cmd(config, "plan", "--profile", "distro/profiles/kiki-kube-compute-containerd.yaml"),
        ),
        Step(
            "Go TUI containerd install plan render",
            ["go", "run", "./cmd/kiki-installer-tui", "--profile", "kiki-kube-compute-containerd", "--render"],
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


def stage2_steps(config: CiConfig) -> list[Step]:
    signing_key = stage2_repo_signing_key(config)
    crio_rootfs = stage2_rootfs_dir(config, "kiki-kube-compute")
    containerd_rootfs = stage2_rootfs_dir(config, "kiki-kube-compute-containerd")
    go_tui_plan = config.artifact_root / "plans" / "kiki-kube-compute-containerd.install-plan.yaml"
    return [
        Step("Write package repository index", ki2build_cmd(config, "repo-index")),
        Step("Generate Stage 2 repository signing key", ki2repo_cmd(config, "keygen", "--output", str(signing_key), "--force")),
        Step("Generate signed Stage 2 repository metadata", ki2repo_cmd(config, "generate", "--channel", "stage2-v2", "--sign-key", str(signing_key))),
        Step("Verify signed Stage 2 repository metadata", ki2repo_cmd(config, "verify", "--key", str(signing_key))),
        Step(
            "Verify Stage 2 Kubernetes readiness",
            python_cmd(
                config,
                "tools/ki2stage2.py",
                "verify-kubernetes",
                "--repo-root",
                str(config.repo_root),
                "--arch",
                config.arch,
                "--require-signed-metadata",
                "--strict-production",
            ),
        ),
        Step(
            "Verify Stage 2 network userspace package status",
            python_cmd(
                config,
                "tools/ki2stage2.py",
                "verify-network-userspace",
                "--repo-root",
                str(config.repo_root),
                "--arch",
                config.arch,
                "--strict-production",
            ),
        ),
        Step(
            "Verify Stage 2 runtime and Kubernetes binary smoke",
            python_cmd(
                config,
                "tools/ki2stage2.py",
                "verify-binary-smoke",
                "--repo-root",
                str(config.repo_root),
                "--arch",
                config.arch,
            ),
        ),
        Step(
            "Write Go TUI Stage 2 containerd install plan",
            [
                "go",
                "run",
                "./cmd/kiki-installer-tui",
                "--profile",
                "kiki-kube-compute-containerd",
                "--write",
                "--plan",
                str(go_tui_plan),
            ],
        ),
        Step(
            "Verify Go TUI Stage 2 install plan contract",
            python_cmd(
                config,
                "tools/ki2stage2.py",
                "verify-install-plan",
                "--plan",
                str(go_tui_plan),
                "--runtime",
                "containerd",
                "--role",
                "compute",
            ),
        ),
        Step(
            "Assemble Stage 2 CRI-O Kubernetes rootfs",
            ki2build_cmd(
                config,
                "rootfs",
                "--profile",
                "distro/profiles/kiki-kube-compute.yaml",
                "--rootfs-dir",
                str(crio_rootfs),
                "--clean-rootfs",
            ),
        ),
        Step(
            "Verify installed Stage 2 CRI-O Kubernetes rootfs",
            python_cmd(
                config,
                "tools/ki2stage2.py",
                "verify-installed-rootfs",
                "--root",
                str(crio_rootfs),
                "--runtime",
                "cri-o",
            ),
        ),
        Step(
            "Assemble Stage 2 containerd Kubernetes rootfs",
            ki2build_cmd(
                config,
                "rootfs",
                "--profile",
                "distro/profiles/kiki-kube-compute-containerd.yaml",
                "--rootfs-dir",
                str(containerd_rootfs),
                "--clean-rootfs",
            ),
        ),
        Step(
            "Verify installed Stage 2 containerd Kubernetes rootfs",
            python_cmd(
                config,
                "tools/ki2stage2.py",
                "verify-installed-rootfs",
                "--root",
                str(containerd_rootfs),
                "--runtime",
                "containerd",
            ),
        ),
        Step(
            "Verify Stage 2 package manager repository flows",
            python_cmd(
                config,
                "tools/ki2stage2.py",
                "verify-package-manager",
                "--repo-root",
                str(config.repo_root),
            ),
        ),
        Step("Summarize Stage 2 repository", ki2repo_cmd(config, "summary")),
    ]


def pipeline_steps(config: CiConfig, name: str) -> list[Step]:
    pipelines: dict[str, Callable[[CiConfig], list[Step]]] = {
        "smoke": base_smoke_steps,
        "bootstrap": lambda cfg: [*base_smoke_steps(cfg), *bootstrap_steps(cfg)],
        "minimal-systemd": lambda cfg: [*base_smoke_steps(cfg), *minimal_systemd_steps(cfg)],
        "stage2": lambda cfg: [*base_smoke_steps(cfg), *stage2_steps(cfg)],
        "security": security_steps,
        "iso": lambda cfg: [*base_smoke_steps(cfg), *iso_steps(cfg)],
        "bootiso": lambda cfg: [*base_smoke_steps(cfg), *boot_iso_steps(cfg)],
        "installer-iso": lambda cfg: [*base_smoke_steps(cfg), *installer_iso_steps(cfg)],
        "publish": publish_steps,
        "release": lambda cfg: [
            *base_smoke_steps(cfg),
            *bootstrap_steps(cfg),
            *stage2_steps(cfg),
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
        "stage2",
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
        self.lock = threading.RLock()

    def create(self, pipeline: str, *, package: str | None = None) -> dict[str, Any]:
        job_id = dt.datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + f"-{random.randrange(1000, 9999)}"
        job_dir = self.jobs_dir / job_id
        while True:
            try:
                job_dir.mkdir()
                break
            except FileExistsError:
                job_id = dt.datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + f"-{random.randrange(1000, 9999)}"
                job_dir = self.jobs_dir / job_id
        job = {
            "id": job_id,
            "pipeline": pipeline,
            "package": package,
            "status": "pending",
            "created_at": now(),
            "started_at": None,
            "finished_at": None,
            "exit_code": None,
            "steps": [],
        }
        (job_dir / "log.txt").write_text("", encoding="utf-8")
        self.write(job)
        return job

    def path(self, job_id: str) -> Path:
        if not re.fullmatch(r"\d{8}-\d{6}-\d{4}", job_id):
            raise KeyError(job_id)
        return self.jobs_dir / job_id / "metadata.json"

    def log_path(self, job_id: str) -> Path:
        self.path(job_id)
        return self.jobs_dir / job_id / "log.txt"

    def read(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            path = self.path(job_id)
            if not path.exists():
                raise KeyError(job_id)
            return json.loads(path.read_text(encoding="utf-8"))

    def write(self, job: dict[str, Any]) -> None:
        path = self.path(job["id"])
        with self.lock:
            tmp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
            try:
                tmp.write_text(json.dumps(job, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                # Windows readers in another CLI process can briefly hold the file.
                for attempt in range(6):
                    try:
                        tmp.replace(path)
                        break
                    except PermissionError:
                        if attempt == 5:
                            raise
                        time.sleep(0.01 * (attempt + 1))
            finally:
                tmp.unlink(missing_ok=True)

    def list(self) -> list[dict[str, Any]]:
        jobs = []
        for path in sorted(self.jobs_dir.glob("*/metadata.json"), reverse=True):
            try:
                with self.lock:
                    jobs.append(json.loads(path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
        return jobs


def append_log(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8", errors="replace") as handle:
        handle.write(text)


def log_chunk(path: Path, offset: int | None = None, limit: int = 65536) -> dict[str, Any]:
    with path.open("rb") as handle:
        size = path.stat().st_size
        start = max(0, size - limit) if offset is None else offset
        if start < 0 or start > size:
            raise CiError("log offset is out of range")
        handle.seek(start)
        data = handle.read(limit)
    if offset is None and start:
        while data and data[0] & 0xC0 == 0x80:
            start += 1
            data = data[1:]
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    text = decoder.decode(data, final=False)
    pending, _ = decoder.getstate()
    return {"text": text, "offset": start + len(data) - len(pending), "truncated": offset is None and start > 0}


def package_build_steps(config: CiConfig, package: str, job_id: str) -> list[Step]:
    # The package comes from the recipe catalog, never from a shell fragment.
    job_root = config.artifact_root / "jobs" / job_id
    profile = job_root / "package-profile.toml"
    profile.write_text(f'name = "web-{job_id}"\npackages = ["{package}"]\n', encoding="utf-8")
    return [Step(f"Build {package} and required dependencies", ki2build_cmd(
        config, "build", "--profile", str(profile),
        "--build-dir", str(job_root / "work"),
        "--packages-dir", str(job_root / "packages"),
        "--repo-dir", str(job_root / "repo"),
        "--source-cache", str(job_root / "sources"),
        "--rootfs-dir", str(job_root / "rootfs"),
    ))]


def run_step(config: CiConfig, step: Step, log_path: Path) -> int:
    append_log(log_path, f"\n==> {step.name}\n")
    append_log(log_path, "+ " + shlex.join(step.command) + "\n")
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    pycache = config.artifact_root / "pycache"
    pycache.mkdir(parents=True, exist_ok=True)
    env["PYTHONPYCACHEPREFIX"] = str(pycache)
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
    try:
        for line in proc.stdout:
            append_log(log_path, line)
        proc.wait()
    except BaseException:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        raise
    finally:
        proc.stdout.close()
    append_log(log_path, f"<== {step.name} exit={proc.returncode}\n")
    return proc.returncode


def run_job(config: CiConfig, store: JobStore, job_id: str, build_lock: threading.Lock | None = None,
            *, git_sources: GitSources | None = None) -> None:
    log_path = store.log_path(job_id)
    lock = build_lock or threading.Lock()
    with lock:
        with store.lock:
            job = store.read(job_id)
            if job["status"] != "pending":
                return
            job["status"] = "running"
            job["started_at"] = now()
            store.write(job)
        exit_code = 0
        interrupted = False
        step_meta = None
        try:
            if job.get("source", {}).get("kind") == "git-latest":
                if git_sources is None:
                    raise CiError("Git 최신 소스를 확인할 수 없습니다. 이전 소스로 대체하지 않습니다.")
                append_log(log_path, "HTTPS Git: fetching latest branch before build\n")
                record = git_sources.sync()
                root = store.jobs_dir / job_id / "source"
                job["source"] = git_sources.export(record["commit"], root)
                store.write(job)
                if job.get("package"):
                    validate_package(replace(config, repo_root=root), job["package"], engine_root=config.repo_root)
            if job.get("source", {}).get("kind") == "git":
                config = replace(config, repo_root=store.jobs_dir / job_id / "source",
                                 publish_dir=store.jobs_dir / job_id / "publish")
                append_log(log_path, "Git source: " + job["source"]["commit"] + "\n")
            steps = package_build_steps(config, job["package"], job_id) if job.get("package") else pipeline_steps(config, job["pipeline"])
            job["steps"] = [
                {"name": step.name, "command": step.command, "status": "pending", "started_at": None,
                 "finished_at": None, "exit_code": None, "allow_failure": step.allow_failure}
                for step in steps
            ]
            store.write(job)
            for step, step_meta in zip(steps, job["steps"]):
                step_meta.update(status="running", started_at=now())
                store.write(job)
                code = run_step(config, step, log_path)
                step_meta.update(finished_at=now(), exit_code=code, status="succeeded" if code == 0 else "failed")
                store.write(job)
                if code != 0 and not step.allow_failure:
                    exit_code = code
                    break
        except (Exception, KeyboardInterrupt) as exc:
            interrupted = isinstance(exc, KeyboardInterrupt)
            exit_code = 130 if interrupted else 1
            job["error"] = str(exc) or "Interrupted by operator"
            if step_meta is not None:
                step_meta.update(status="interrupted" if interrupted else "failed", finished_at=now(), exit_code=exit_code)
            append_log(log_path, f"\n[error] {job['error']}\n")
            if interrupted:
                raise
        finally:
            for remaining in job.get("steps", []):
                if remaining["status"] == "pending":
                    remaining["status"] = "skipped"
            job["exit_code"] = exit_code
            job["finished_at"] = now()
            job["status"] = "interrupted" if interrupted else ("succeeded" if exit_code == 0 else "failed")
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
        if profile.get("prebuilt"):
            # These roots are supplied by signed package manifests, not the source recipe catalog.
            # Repository validation belongs to assembly/import; browsing a fresh Git tree must work without binaries.
            profiles.append({"name": profile["name"], "description": profile.get("description", ""),
                             "path": relative_path(config.repo_root, path), "roots": roots,
                             "runtime_count": None, "build_count": None, "runtime_plan": [], "build_plan": [],
                             "plan_status": "prebuilt_required"})
            continue
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
        ("/package-build", "Build KI2"),
        ("/kernel-build", "커널 빌드"),
        ("/profiles", "Profiles"),
        ("/artifacts", "Artifacts"),
        ("/security", "Security"),
        ("/deploy", "Deploy"),
        ("/git", "Git 소스 동기화"),
    ]
    return "<nav>" + "".join(
        f"<a class='{('active' if key == active else '')}' href='{href}'>{label}</a>" for href, label in items for key in [href]
    ) + "</nav>"


def metric(label: str, value: Any, tone: str = "") -> str:
    return f"<div class='metric {tone}'><div class='metric-value'>{html_escape(value)}</div><div class='metric-label'>{html_escape(label)}</div></div>"


def render_page(title: str, body: str, *, active: str = "/", head: str = "") -> bytes:
    css = """
body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f4f6f8;color:#1f252e}
header{background:#20242c;color:white;padding:18px 28px}
header h1{margin:0;font-size:22px;letter-spacing:0}
nav{display:flex;gap:4px;flex-wrap:wrap;background:#2a303a;padding:0 24px}
nav a{color:#dce3ee;text-decoration:none;padding:12px 13px;border-bottom:3px solid transparent}
nav a.active{color:white;border-bottom-color:#65a30d}
main{padding:24px;max-width:1280px;margin:auto;min-width:0}
h2{font-size:18px;margin:0 0 12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
.bar{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}
button,.button{border:0;background:#1f5fbf;color:white;padding:9px 12px;border-radius:6px;cursor:pointer;text-decoration:none;display:inline-block}
select{padding:9px 12px;border:1px solid #c5cbd5;border-radius:6px;background:white;min-width:280px;max-width:100%}
button.secondary,.button.secondary{background:#475467}
.panel{background:white;border:1px solid #d9dee7;border-radius:8px;padding:16px;margin:14px 0;overflow-x:auto}
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
label{align-self:center;font-weight:600}summary{cursor:pointer;font-weight:600;padding:8px 0}
details li{padding:6px 0}details code{display:block;overflow-wrap:anywhere;color:#667085;font-size:12px}
progress{width:100%;height:12px;accent-color:#1f5fbf}.cancelled,.interrupted,.skipped{color:#667085}
#live-log{min-height:160px}#job-error{overflow-wrap:anywhere}button:disabled{opacity:.55;cursor:wait}
@media(max-width:600px){main{padding:12px}header{padding:16px}nav{padding:0 8px}nav a{padding:10px 8px}select{min-width:0;width:100%}.bar{align-items:center}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.metric-value{font-size:22px}}
"""
    return f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title><style>{css}</style>{head}<script src='/build-console.js' defer></script></head><body><header><h1>{html.escape(title)}</h1></header>{nav(active)}<main>{body}</main></body></html>".encode("utf-8")


class BuildServer:
    def __init__(self, config: CiConfig):
        self.config = config
        self.git = GitSources(config.artifact_root / "git", config.git_url, config.git_branch) if config.git_url else None
        self.lease = BuilderLease(config.artifact_root)
        self.store = JobStore(config.artifact_root)
        self.queue: queue.Queue[str | None] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.closed = False
        # Pending jobs survive a restart; an interrupted build needs explicit retry.
        for job in sorted(self.store.list(), key=lambda item: (item["created_at"], item["id"])):
            if job["status"] == "running":
                job.update(status="interrupted", finished_at=now(), exit_code=1,
                           error="Build console stopped during execution; retry after checking the log.")
                for step in job.get("steps", []):
                    if step["status"] == "running":
                        step.update(status="interrupted", finished_at=now())
                    elif step["status"] == "pending":
                        step["status"] = "skipped"
                self.store.write(job)
            elif job["status"] == "pending":
                self.queue.put(job["id"])
        if not self.queue.empty():
            self._start_worker()

    def _start_worker(self) -> None:
        if self.worker is None:
            self.worker = threading.Thread(target=self._work, name="kiki-build-worker", daemon=True)
            self.worker.start()

    def _work(self) -> None:
        try:
            while True:
                job_id = self.queue.get()
                try:
                    if job_id is None or self.closed:
                        return
                    run_job(self.config, self.store, job_id, git_sources=self.git)
                finally:
                    self.queue.task_done()
        finally:
            self.lease.close()

    def close(self) -> None:
        with self.store.lock:
            self.closed = True
            if self.worker is not None:
                self.queue.put(None)
            else:
                self.lease.close()

    def _submit(self, pipeline: str, *, package: str | None = None, retry_of: str | None = None,
                source: str = "preserved", commit: str = "") -> dict[str, Any]:
        with self.store.lock:
            if self.closed:
                raise CiError("build console is shutting down")
            if source not in {"preserved", "git", "git-latest"}:
                raise CiError("지원하지 않는 빌드 소스입니다.")
            if source in {"git", "git-latest"}:
                if self.git is None:
                    raise CiError("Git 연동이 설정되지 않았습니다.")
                if pipeline not in {"smoke", "security", "package"}:
                    raise CiError("Git 소스는 기본 검사·보안 검사·개별 패키지 빌드부터 사용할 수 있습니다.")
                try:
                    if source == "git-latest" and not commit:
                        commit = self.git.status().get("current", {}).get("commit", "")
                    self.git.record(commit)
                except GitError as exc:
                    raise CiError(str(exc)) from exc
            job = self.store.create(pipeline, package=package)
            if source == "git-latest":
                job["source"] = {"kind": "git-latest", "branch": self.git.branch, "viewed_commit": commit}
                job["source_request"] = {"mode": "latest", "viewed_commit": commit}
            if source == "git":
                try:
                    job["source"] = self.git.export(commit, self.store.jobs_dir / job["id"] / "source")
                    if package:
                        validate_package(replace(self.config, repo_root=self.store.jobs_dir / job["id"] / "source"), package,
                                         engine_root=self.config.repo_root)
                except Exception as exc:
                    job.update(status="failed", finished_at=now(), exit_code=1, error=str(exc))
                    self.store.write(job)
                    raise CiError(str(exc)) from exc
            elif source == "preserved":
                job["source"] = {"kind": "preserved"}
            if retry_of:
                job["retry_of"] = retry_of
            self.store.write(job)
            self.queue.put(job["id"])
            self._start_worker()
            return job

    def job(self, job_id: str) -> dict[str, Any]:
        job = self.store.read(job_id)
        pending = sorted((item for item in self.store.list() if item["status"] == "pending"),
                         key=lambda item: (item["created_at"], item["id"]))
        ids = [item["id"] for item in pending]
        job["queue_position"] = ids.index(job_id) + 1 if job_id in ids else None
        return job

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self.store.lock:
            job = self.store.read(job_id)
            if job["status"] != "pending":
                raise CiError("only queued jobs can be cancelled")
            job.update(status="cancelled", finished_at=now(), exit_code=None)
            self.store.write(job)
            return job

    def retry(self, job_id: str) -> dict[str, Any]:
        with self.store.lock:
            job = self.store.read(job_id)
            if job["status"] not in TERMINAL_STATUSES:
                raise CiError("wait until the job finishes before retrying")
            if job.get("package"):
                if job.get("source", {}).get("kind") not in {"git", "git-latest"}:
                    validate_package(self.config, job["package"])
            elif job["pipeline"] not in pipeline_names():
                raise CiError("pipeline is no longer available")
            return self._submit(job["pipeline"], package=job.get("package"), retry_of=job_id,
                                source=job.get("source", {}).get("kind", "preserved"),
                                commit=job.get("source", {}).get("commit", ""))

    def submit(self, pipeline: str, *, source="preserved", commit="") -> dict[str, Any]:
        if pipeline not in pipeline_names():
            raise CiError(f"unknown pipeline {pipeline!r}")
        return self._submit(pipeline, source=source, commit=commit)

    def submit_package(self, name: str, *, source=None, commit="") -> dict[str, Any]:
        source = source or ("git-latest" if self.git else "preserved")
        if source == "git-latest":
            if not self.git:
                raise CiError("Git 연동이 설정되지 않았습니다.")
            # Validate against the displayed catalog now, then against the actual fetched commit in the worker.
            commit = commit or self.git.status().get("current", {}).get("commit", "")
            validate_package(self.git_catalog(commit), name, engine_root=self.config.repo_root)
        elif source != "git":
            validate_package(self.config, name)
        return self._submit("package", package=name, source=source, commit=commit)

    def git_catalog(self, commit):
        if not self.git:
            raise CiError("Git 연동이 설정되지 않았습니다.")
        try:
            self.git.record(commit)
            # Serialize catalogue extraction with job submissions, without a network fetch.
            with self.store.lock:
                root = self.config.artifact_root / "git" / "catalogs" / commit
                if not root.exists():
                    temp = root.with_name("pending-" + uuid.uuid4().hex)
                    self.git.export(commit, temp)
                    temp.rename(root)
                return replace(self.config, repo_root=root)
        except (GitError, OSError) as exc:
            raise CiError(str(exc)) from exc


def validate_package(config: CiConfig, name: str, *, engine_root=None) -> None:
    try:
        recipes = load_ki2build_module(engine_root or config.repo_root).load_recipes(config.repo_root / "distro/recipes")
    except (ValueError, OSError, RuntimeError) as exc:
        raise CiError("패키지 명세를 읽지 못했습니다. 소스와 명세 형식을 확인하세요.") from exc
    recipe = recipes.get(name)
    if recipe is None or not recipe.supports_arch(config.arch):
        raise CiError("select a supported package from the recipe catalog")


def pipeline_plan(config: CiConfig, name: str) -> list[dict[str, Any]]:
    return [{"name": step.name, "command": step.command, "allow_failure": step.allow_failure}
            for step in pipeline_steps(config, name)]


def make_handler(server: BuildServer):
    class Handler(BaseHTTPRequestHandler):
        def send_error(self, code, message=None, explain=None):
            if message and not message.isascii():
                body = render_page("요청을 처리할 수 없습니다", "<div class='panel'><p>" + html_escape(message) + "</p></div>")
                self.send_response(code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)
                return
            super().send_error(code, message, explain)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/api/git":
                self.send_json(server.git.status() if server.git else {"enabled": False})
                return
            if parsed.path == "/git":
                state = server.git.status() if server.git else {"enabled": False}
                self.send_html(render_page("Git 소스 동기화", git_page(state), active="/git",
                                           head="<meta http-equiv='refresh' content='3'>" if state.get("busy") else ""))
                return
            if parsed.path == "/favicon.ico":
                self.send_response(HTTPStatus.NO_CONTENT)
                self.end_headers()
                return
            if parsed.path == "/build-console.js":
                body = Path(__file__).with_name("ki2ci_ui.js").read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/javascript; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/api/plan":
                name = urllib.parse.parse_qs(parsed.query).get("pipeline", [""])[0]
                try:
                    self.send_json(pipeline_plan(server.config, name))
                except CiError as exc:
                    self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            log_match = re.fullmatch(r"/api/jobs/(\d{8}-\d{6}-\d{4})/log", parsed.path)
            if log_match:
                try:
                    server.store.read(log_match[1])
                    value = urllib.parse.parse_qs(parsed.query).get("offset", [None])[0]
                    self.send_json(log_chunk(server.store.log_path(log_match[1]), int(value) if value is not None else None))
                except KeyError:
                    self.send_error(HTTPStatus.NOT_FOUND, "job not found")
                except (ValueError, CiError) as exc:
                    self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            artifact_match = re.fullmatch(r"/jobs/(\d{8}-\d{6}-\d{4})/artifacts/([A-Za-z0-9_.-]+\.ki2)", parsed.path)
            if artifact_match:
                job_id, filename = artifact_match.groups()
                try:
                    job = server.store.read(job_id)
                except KeyError:
                    job = {}
                if not job.get("package"):
                    self.send_error(HTTPStatus.NOT_FOUND, "artifact not found")
                    return
                artifact = server.store.jobs_dir / job_id / "packages" / server.config.arch / filename
                if not artifact.is_file():
                    self.send_error(HTTPStatus.NOT_FOUND, "artifact not found")
                    return
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.send_header("Content-Length", str(artifact.stat().st_size))
                self.end_headers()
                with artifact.open("rb") as source:
                    shutil.copyfileobj(source, self.wfile)
                return
            if parsed.path == "/":
                self.send_html(self.dashboard_page())
                return
            if parsed.path == "/jobs":
                self.send_html(self.jobs_page())
                return
            if parsed.path == "/packages":
                self.send_html(self.packages_page())
                return
            if parsed.path in {"/package-build", "/kernel-build"}:
                query = urllib.parse.parse_qs(parsed.query)
                try:
                    self.send_html(self.package_build_page(query.get("source", [None])[0], query.get("commit", [""])[0],
                                                          kernel=parsed.path == "/kernel-build"))
                except CiError as exc:
                    self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
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
                    self.send_json(server.job(job_id))
                except KeyError:
                    self.send_error(HTTPStatus.NOT_FOUND, "job not found")
                return
            self.send_error(HTTPStatus.NOT_FOUND, "not found")

        def do_POST(self) -> None:  # noqa: N802
            action = re.fullmatch(r"/jobs/(\d{8}-\d{6}-\d{4})/(retry|cancel)", self.path)
            if self.path not in {"/jobs", "/package-build", "/kernel-build", "/git/sync"} and not action:
                self.send_error(HTTPStatus.NOT_FOUND, "not found")
                return
            origin = self.headers.get("Origin")
            if origin and urllib.parse.urlparse(origin).netloc != self.headers.get("Host"):
                self.send_error(HTTPStatus.FORBIDDEN, "cross-origin submission denied")
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/x-www-form-urlencoded":
                self.send_error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "form data required")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if not 0 < length <= 4096:
                self.send_error(HTTPStatus.BAD_REQUEST, "invalid form size")
                return
            body = self.rfile.read(length).decode("utf-8")
            data = urllib.parse.parse_qs(body)
            pipeline = data.get("pipeline", [""])[0]
            try:
                if self.path == "/git/sync":
                    if not server.git:
                        raise CiError("Git 연동이 설정되지 않았습니다.")
                    server.git.start_sync()
                    self.send_response(HTTPStatus.SEE_OTHER)
                    self.send_header("Location", "/git")
                    self.end_headers()
                    return
                elif action:
                    job = server.retry(action[1]) if action[2] == "retry" else server.cancel(action[1])
                else:
                    package_request = self.path in {"/package-build", "/kernel-build"}
                    source = data.get("source", ["git-latest" if package_request and server.git else "preserved"])[0]
                    commit = data.get("commit", [""])[0]
                    if self.path == "/kernel-build" and source not in {"git", "git-latest"}:
                        raise CiError("커널 빌드는 Git 소스를 사용해야 합니다.")
                    package = "linux" if self.path == "/kernel-build" else data.get("package", [""])[0]
                    job = (server.submit_package(package, source=source, commit=commit)
                           if package_request else server.submit(pipeline, source=source, commit=commit))
            except KeyError:
                self.send_error(HTTPStatus.NOT_FOUND, "job not found")
                return
            except (CiError, GitError) as exc:
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
            options = "".join(f"<option value='{name}'>{name}</option>" for name in pipeline_names())
            return (
                "<p class='muted'>One build runs at a time, in submission order. Compiler parallelism: "
                f"{server.config.jobs}. Select a pipeline to preview its steps.</p>"
                "<form method='post' action='/jobs' data-build-plan><div class='bar'>"
                f"<label for='pipeline'>Pipeline</label><select id='pipeline' name='pipeline'>{options}</select>"
                "<button type='submit'>Queue build</button></div>"
                "<details open><summary>Execution plan</summary><ol data-plan-steps><li>Loading plan…</li></ol></details>"
                "<p data-plan-error role='status' class='bad'></p></form>"
            )

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
                    f"<td>{html.escape(job.get('package') or job['pipeline'])}</td>"
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
                + metric("Queued builds", overview["job_counts"]["pending"])
                + metric("Running builds", overview["job_counts"]["running"])
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

        def package_build_page(self, source=None, commit="", *, kernel=False) -> bytes:
            source = source or ("git-latest" if server.git else "preserved")
            title = "KIKI 커널 빌드" if kernel else "KIKI Individual Package Build"
            route = "/kernel-build" if kernel else "/package-build"
            if source not in {"preserved", "git", "git-latest"}:
                raise CiError("지원하지 않는 빌드 소스입니다.")
            if kernel and (not server.git or source == "preserved"):
                return render_page(title, "<div class='panel'><p>커널 빌드를 위한 Git 저장소를 먼저 설정하세요.</p><a href='/git'>Git 소스 동기화</a></div>", active=route)
            if source == "git-latest" and not commit:
                commit = server.git.status().get("current", {}).get("commit", "")
                if not commit:
                    return render_page(title, "<div class='panel'><p>먼저 Git 소스 동기화를 실행하세요.</p><a href='/git'>Git 소스 동기화</a></div>", active=route)
            config = server.git_catalog(commit) if source in {"git", "git-latest"} else server.config
            try:
                recipes = load_ki2build_module(server.config.repo_root).load_recipes(config.repo_root / "distro/recipes")
            except (ValueError, OSError, RuntimeError) as exc:
                raise CiError("패키지 명세를 읽지 못했습니다. 소스와 명세 형식을 확인하세요.") from exc
            options = "".join(
                f"<option value='{html_escape(recipe.name)}'>{html_escape(recipe.name)} — {html_escape(recipe.version)}-{html_escape(recipe.release)}</option>"
                for recipe in sorted(recipes.values(), key=lambda item: item.name)
                if recipe.supports_arch(server.config.arch) and (not kernel or recipe.name == "linux")
            )
            kernel_info = ""
            if kernel:
                recipe = recipes.get("linux")
                if not recipe or recipe.build.get("system") != "kernel":
                    raise CiError("선택한 커밋에 지원하는 Linux 커널 명세가 없습니다.")
                kernel_info = ("<h2>Linux " + html_escape(recipe.version) + "-" + html_escape(recipe.release) + "</h2>"
                               + "<p>공식 소스: " + html_escape(recipe.source.get("url", "")) + "</p>"
                               + "<p>소스 SHA-256: <code>" + html_escape(recipe.source.get("sha256", "미지정")) + "</code></p>"
                               + "<p>Git의 커널 설정: <code>" + html_escape(", ".join(recipe.build.get("config_fragments", []))) + "</code></p>")
            body = (
                ("<div class='panel'><h2>Git 커널 소스 빌드</h2>" if kernel else "<div class='panel'><h2>Build one KI2 recipe</h2>")
                + "<p>Select an existing reviewed recipe. Dependencies build in an isolated job directory; this does not sign or publish packages.</p>"
                + kernel_info
                + (source_summary(server.git.record(commit)) if source in {"git", "git-latest"} else "<p>빌드 소스: 기존 후보 작업본 · <a href='/git'>Git 소스 선택</a></p>")
                + ("<p><strong>Git 최신 빌드:</strong> 위 목록은 마지막 확인한 커밋 기준입니다. 실행 직전에 HTTPS로 최신 커밋을 가져와 고정하며, 연결 실패 시 이전 소스로 대체하지 않습니다.</p>" if source == "git-latest" else "")
                + f"<form method='post' action='{route}'>"
                + (f"<input type='hidden' name='source' value='{source}'><input type='hidden' name='commit' value='{html_escape(commit)}'>" if source in {"git", "git-latest"} else "")
                + "<label for='package'>Package</label> "
                + f"<select id='package' name='package' required>{options}</select> "
                + ("<button type='submit'>커널 빌드 시작</button>" if kernel else "<button type='submit'>Build package</button>")
                + "</form></div><div class='panel'><h2>Recent jobs</h2>" + self.jobs_table(limit=10) + "</div>"
            )
            return render_page(title, body, active=route)

        def profiles_page(self) -> bytes:
            rows = []
            for profile in collect_profiles(server.config):
                roots = "".join(f"<span class='pill'>{html_escape(root)}</span>" for root in profile["roots"])
                rows.append(
                    "<tr>"
                    f"<td><b>{html_escape(profile['name'])}</b><br><small>{html_escape(profile['path'])}</small></td>"
                    f"<td>{html_escape(profile['description'])}</td>"
                    f"<td>{roots}</td>"
                    f"<td>{html_escape(profile['runtime_count'] if profile['runtime_count'] is not None else '보관 패키지 기준 · 조립 시 검증')}</td>"
                    f"<td>{html_escape(profile['build_count'] if profile['build_count'] is not None else '보관소 별도 준비')}</td>"
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
            job = server.job(job_id)
            log_path = server.store.log_path(job_id)
            chunk = log_chunk(log_path)
            log = chunk["text"]
            status = html.escape(job["status"])
            steps = "".join(
                f"<tr><td>{html.escape(step['name'])}</td><td class='status {html.escape(step['status'])}'>{html.escape(step['status'])}</td><td>{html.escape(str(step.get('exit_code')))}</td></tr>"
                for step in job.get("steps", [])
            )
            artifacts = "".join(
                f"<li><a href='/jobs/{job_id}/artifacts/{html_escape(path.name)}'>{html_escape(path.name)}</a> ({path.stat().st_size:,} bytes)</li>"
                for path in sorted((server.store.jobs_dir / job_id / "packages").rglob("*.ki2"))
            ) if job.get("package") else ""
            body = (
                f"<a class='button secondary' href='/jobs'>Back to builds</a>"
                + f"<div class='panel' data-job-id='{job_id}' data-log-offset='{chunk['offset']}'><h2>{html.escape(job.get('package') or job['pipeline'])}</h2>"
                + f"<p><code>{job_id}</code> · <b id='job-status' class='status {status}'>{status}</b></p>"
                + source_summary(job.get("source"))
                + "<p id='job-summary' role='status'></p><progress id='job-progress' value='0' max='1' aria-label='Completed build steps'></progress>"
                + f"<p id='job-error' class='bad'>{html_escape(job.get('error', ''))}</p>"
                + "<div class='bar'>"
                + f"<form id='cancel-job' method='post' action='/jobs/{job_id}/cancel'{' hidden' if status != 'pending' else ''}><input type='hidden' name='action' value='cancel'><button class='secondary'>Cancel queued build</button></form>"
                + f"<form id='retry-job' method='post' action='/jobs/{job_id}/retry'{' hidden' if status not in TERMINAL_STATUSES else ''}><input type='hidden' name='action' value='retry'><button>Retry entire build</button></form>"
                + "</div><table><thead><tr><th>Step</th><th>Status</th><th>Exit</th></tr></thead><tbody id='job-steps'>"
                + steps + "</tbody>"
                + "</table></div>"
                + ("<div class='panel'><h2>KI2 artifacts</h2><p>Refresh this page after completion to see new downloads.</p><ul>" + (artifacts or "<li>None yet</li>") + "</ul></div>" if job.get("package") else "")
                + "<div class='panel'><h2>Build log</h2><label><input id='follow-log' type='checkbox' checked> Follow output</label> <span id='connection-state' class='muted' role='status'></span><pre id='live-log'>"
                + html.escape(("[Earlier output omitted]\n" if chunk['truncated'] else "") + log)
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
        git_url=args.git_url,
        git_branch=args.git_branch,
    )


def command_run(args: argparse.Namespace) -> None:
    config = make_config(args)
    lease = BuilderLease(config.artifact_root)
    try:
        store = JobStore(config.artifact_root)
        job = store.create(args.pipeline)
        run_job(config, store, job["id"])
        print(f"job: {job['id']}")
        print(f"log: {store.log_path(job['id'])}")
        result = store.read(job["id"])
        raise SystemExit(int(result["exit_code"] or 0))
    finally:
        lease.close()


def command_serve(args: argparse.Namespace) -> None:
    config = make_config(args)
    server = BuildServer(config)
    httpd = ThreadingHTTPServer((args.host, args.port), make_handler(server))
    print(f"KIKI Build Console: http://{args.host}:{args.port}")
    print("No authentication is built in; bind to localhost or protect it with a reverse proxy.")
    try:
        httpd.serve_forever()
    finally:
        server.close()
        httpd.server_close()


def command_list(args: argparse.Namespace) -> None:
    config = make_config(args)
    store = JobStore(config.artifact_root)
    jobs = store.list()
    if args.json:
        print(json.dumps(jobs, indent=2, sort_keys=True))
        return
    if not jobs:
        print("No build jobs yet.")
    for job in jobs:
        steps = job.get("steps", [])
        done = sum(step["status"] in {"succeeded", "failed"} for step in steps)
        print(f"{job['id']}  {job.get('package') or job['pipeline']:<24} {job['status']:<12} {done}/{len(steps)} steps")


def command_show(args: argparse.Namespace) -> None:
    config = make_config(args)
    store = JobStore(config.artifact_root)
    print(json.dumps(store.read(args.job_id), indent=2, sort_keys=True))
    if not args.json:
        print(log_chunk(store.log_path(args.job_id))["text"])


def command_plan(args: argparse.Namespace) -> None:
    steps = pipeline_plan(make_config(args), args.pipeline)
    if args.json:
        print(json.dumps(steps, indent=2, sort_keys=True))
        return
    print(f"Pipeline: {args.pipeline} · {len(steps)} steps")
    for index, step in enumerate(steps, 1):
        print(f"{index:02d}. {step['name']}" + (" (optional check)" if step['allow_failure'] else ""))
        print("    " + shlex.join(step["command"]))


def command_security_audit(args: argparse.Namespace) -> None:
    raise SystemExit(security_audit(args.repo_root.resolve(), strict_pins=args.strict_pins))


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-root", type=Path, default=default_repo_root())
    parser.add_argument("--artifact-root", type=Path, default=None)
    parser.add_argument("--git-url", default=os.environ.get("KIKI_GIT_URL"))
    parser.add_argument("--git-branch", default=os.environ.get("KIKI_GIT_BRANCH", "stage3"))
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

    plan = subcommands.add_parser("plan", help="preview pipeline steps without executing commands")
    add_common(plan)
    plan.add_argument("pipeline", choices=pipeline_names())
    plan.add_argument("--json", action="store_true")
    plan.set_defaults(func=command_plan)

    serve = subcommands.add_parser("serve", help="serve the build web console")
    add_common(serve)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8090)
    serve.set_defaults(func=command_serve)

    list_jobs = subcommands.add_parser("list-jobs", help="list known jobs")
    add_common(list_jobs)
    list_jobs.add_argument("--json", action="store_true")
    list_jobs.set_defaults(func=command_list)

    show_job = subcommands.add_parser("show-job", help="show job metadata and log")
    add_common(show_job)
    show_job.add_argument("job_id")
    show_job.add_argument("--json", action="store_true", help="print metadata only")
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
    except (CiError, OSError, KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
