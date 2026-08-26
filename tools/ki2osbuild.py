#!/usr/bin/env python3
"""OS build orchestrator for KIKI build plans."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parent))
import ki2build  # type: ignore  # noqa: E402


UTC = dt.timezone.utc
SCHEMA = "kiki-os-build-plan-v1"
DEFAULT_PLAN = "distro/build-plans/stage2-kube-compute-containerd.yaml"


class OsBuildError(RuntimeError):
    pass


@dataclass
class Step:
    name: str
    command: list[str]
    skip_if_exists: Path | tuple[Path, ...] | None = None
    skip_message: str = ""


@dataclass
class BuildContext:
    repo_root: Path
    plan_path: Path
    plan: dict[str, Any]
    arch: str
    jobs: int
    toolchain_id: str
    run_dir: Path
    include_iso: bool
    skip_build: bool
    skip_verify: bool
    force_key: bool


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def now() -> str:
    return dt.datetime.now(UTC).isoformat()


def slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip().lower()).strip("-")
    return cleaned or "step"


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def resolve_path(root: Path, value: str | Path | None, *, default: Path | None = None) -> Path:
    if value is None or str(value) == "":
        if default is None:
            raise OsBuildError("missing required path")
        return default
    path = value if isinstance(value, Path) else Path(str(value))
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def load_build_plan(path: Path) -> dict[str, Any]:
    data = ki2build.read_structured_file(path)
    plan = data.get("os_build", data)
    if not isinstance(plan, dict):
        raise OsBuildError(f"{path}: expected mapping")
    if plan.get("schema") != SCHEMA:
        raise OsBuildError(f"{path}: unsupported schema {plan.get('schema')!r}")
    return plan


def bool_value(data: dict[str, Any], key: str, default: bool = False) -> bool:
    value = data.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def python_cmd(*args: str) -> list[str]:
    return [sys.executable, *args]


def ki2build_cmd(ctx: BuildContext, *args: str) -> list[str]:
    return python_cmd(
        "tools/ki2build.py",
        "--repo-root",
        str(ctx.repo_root),
        "--arch",
        ctx.arch,
        "--jobs",
        str(ctx.jobs),
        "--toolchain-id",
        ctx.toolchain_id,
        *args,
    )


def ki2repo_cmd(ctx: BuildContext, *args: str) -> list[str]:
    return python_cmd(
        "tools/ki2repo.py",
        "--repo-root",
        str(ctx.repo_root),
        "--arch",
        ctx.arch,
        *args,
    )


def ki2stage2_cmd(ctx: BuildContext, *args: str) -> list[str]:
    return python_cmd(
        "tools/ki2stage2.py",
        *args,
        "--repo-root",
        str(ctx.repo_root),
        "--arch",
        ctx.arch,
    )


def plan_name(plan: dict[str, Any]) -> str:
    return str(plan.get("name") or "unnamed")


def build_profile(ctx: BuildContext) -> Path:
    build = ctx.plan.get("build", {})
    if not isinstance(build, dict):
        raise OsBuildError("build section must be a mapping")
    return resolve_path(ctx.repo_root, build.get("profile"))


def rootfs_profile(ctx: BuildContext) -> Path:
    rootfs = ctx.plan.get("rootfs", {})
    if not isinstance(rootfs, dict):
        raise OsBuildError("rootfs section must be a mapping")
    return resolve_path(ctx.repo_root, rootfs.get("profile"), default=build_profile(ctx))


def rootfs_output(ctx: BuildContext) -> Path:
    rootfs = ctx.plan.get("rootfs", {})
    if not isinstance(rootfs, dict):
        raise OsBuildError("rootfs section must be a mapping")
    return resolve_path(ctx.repo_root, rootfs.get("output"), default=ctx.repo_root / "dist" / "rootfs" / plan_name(ctx.plan))


def signing_key(ctx: BuildContext) -> Path:
    repository = ctx.plan.get("repository", {})
    if not isinstance(repository, dict):
        raise OsBuildError("repository section must be a mapping")
    return resolve_path(ctx.repo_root, repository.get("signing_key"), default=ctx.repo_root / "build" / "ki2" / "keys" / "stage2-v2-repo.hmac")


def signing_algorithm(ctx: BuildContext) -> str:
    repository = ctx.plan.get("repository", {})
    if not isinstance(repository, dict):
        raise OsBuildError("repository section must be a mapping")
    algorithm = str(repository.get("algorithm") or "hmac-sha256")
    if algorithm not in {"hmac-sha256", "ed25519"}:
        raise OsBuildError(f"unsupported repository signing algorithm: {algorithm}")
    return algorithm


def verification_key(ctx: BuildContext) -> Path:
    key = signing_key(ctx)
    return Path(str(key) + ".pub") if signing_algorithm(ctx) == "ed25519" else key


def release_channel(ctx: BuildContext) -> str:
    release = ctx.plan.get("release", {})
    if not isinstance(release, dict):
        return "stage2-v2"
    return str(release.get("channel") or "stage2-v2")


def rootfs_runtime(ctx: BuildContext) -> str:
    rootfs = ctx.plan.get("rootfs", {})
    if not isinstance(rootfs, dict):
        return "containerd"
    return str(rootfs.get("runtime") or "containerd")


def build_steps(ctx: BuildContext) -> list[Step]:
    build = ctx.plan.get("build", {})
    repository = ctx.plan.get("repository", {})
    rootfs = ctx.plan.get("rootfs", {})
    verify = ctx.plan.get("verify", {})
    iso = ctx.plan.get("iso", {})
    if not all(isinstance(section, dict) for section in (build, repository, rootfs, verify, iso)):
        raise OsBuildError("build, repository, rootfs, verify, and iso sections must be mappings")

    steps: list[Step] = []
    profile = build_profile(ctx)
    max_packages = str(build.get("max_packages") or 72)
    allow_unpinned = bool_value(build, "allow_unpinned", True)

    graphics = ctx.plan.get("graphics", {})
    if graphics and not isinstance(graphics, dict):
        raise OsBuildError("graphics section must be a mapping")
    if isinstance(graphics, dict) and bool_value(graphics, "enabled", False) and not ctx.skip_build:
        graphics_output = ctx.repo_root / str(graphics.get("output") or "build/ki2/host-graphics/rootfs")
        steps.append(Step(
            "Prepare GTK/Wayland installer runtime",
            python_cmd(
                "tools/ki2graphics.py",
                "prepare",
                "--repo-root",
                str(ctx.repo_root),
                "--output",
                str(graphics_output),
                "--jobs",
                str(ctx.jobs),
            ),
        ))

    steps.append(Step("Validate package profile", ki2build_cmd(ctx, "validate", "--profile", rel(profile, ctx.repo_root), "--max-packages", max_packages)))
    steps.append(Step("Print package dependency plan", ki2build_cmd(ctx, "plan", "--profile", rel(profile, ctx.repo_root))))
    if not ctx.skip_build:
        build_command = ki2build_cmd(ctx, "build", "--profile", rel(profile, ctx.repo_root))
        if allow_unpinned:
            build_command.append("--allow-unpinned")
        steps.append(Step("Build profile packages", build_command))
    steps.append(Step("Write package repository index", ki2build_cmd(ctx, "repo-index")))

    sign = bool_value(repository, "sign", True)
    if sign:
        key = signing_key(ctx)
        algorithm = signing_algorithm(ctx)
        if algorithm == "ed25519":
            keygen = ki2repo_cmd(ctx, "keygen-ed25519", "--private-key", str(key), "--public-key", str(verification_key(ctx)))
        else:
            keygen = ki2repo_cmd(ctx, "keygen", "--output", str(key))
        if ctx.force_key:
            keygen.append("--force")
        key_targets: Path | tuple[Path, ...] = (key, verification_key(ctx)) if algorithm == "ed25519" else key
        steps.append(Step("Ensure repository signing key", keygen, skip_if_exists=None if ctx.force_key else key_targets, skip_message=f"signing key exists: {key}"))
        generate = ki2repo_cmd(ctx, "generate", "--channel", release_channel(ctx), "--sign-key", str(key))
        if algorithm == "ed25519":
            generate.extend(["--sign-algorithm", "ed25519"])
        base_url = str(repository.get("base_url") or "")
        if base_url:
            generate.extend(["--base-url", base_url])
        steps.append(Step("Generate signed repository metadata", generate))
        steps.append(Step("Verify repository metadata signature", ki2repo_cmd(ctx, "verify", "--key", str(verification_key(ctx)))))
    else:
        steps.append(Step("Generate unsigned repository metadata", ki2repo_cmd(ctx, "generate", "--channel", release_channel(ctx))))

    if bool_value(rootfs, "enabled", True):
        rf_profile = rootfs_profile(ctx)
        rf_output = rootfs_output(ctx)
        rootfs_command = ki2build_cmd(ctx, "rootfs", "--profile", rel(rf_profile, ctx.repo_root), "--rootfs-dir", str(rf_output))
        if bool_value(rootfs, "clean", True):
            rootfs_command.append("--clean-rootfs")
        steps.append(Step("Assemble OS rootfs", rootfs_command))

    if not ctx.skip_verify:
        strict = bool_value(verify, "strict_production", True)
        require_signed = bool_value(verify, "require_signed_metadata", True)
        if bool_value(verify, "stage3_contract", False):
            steps.append(Step("Verify Stage 3 platform contract", python_cmd("tools/ki2stage3.py", "verify")))
        if bool_value(verify, "stage2_kubernetes", True):
            command = ki2stage2_cmd(ctx, "verify-kubernetes")
            if require_signed:
                command.append("--require-signed-metadata")
            if strict:
                command.append("--strict-production")
            steps.append(Step("Verify Stage 2 Kubernetes readiness", command))
        if bool_value(verify, "network_userspace", True):
            command = ki2stage2_cmd(ctx, "verify-network-userspace")
            if strict:
                command.append("--strict-production")
            steps.append(Step("Verify network userspace packages", command))
        if bool_value(verify, "binary_smoke", True):
            steps.append(Step("Verify runtime binary smoke", ki2stage2_cmd(ctx, "verify-binary-smoke")))
        if bool_value(verify, "package_manager", True):
            steps.append(
                Step(
                    "Verify package manager repository flows",
                    python_cmd("tools/ki2stage2.py", "verify-package-manager", "--repo-root", str(ctx.repo_root)),
                )
            )
        if bool_value(verify, "installed_rootfs", True) and bool_value(rootfs, "enabled", True):
            steps.append(
                Step(
                    "Verify installed OS rootfs",
                    python_cmd(
                        "tools/ki2stage2.py",
                        "verify-installed-rootfs",
                        "--root",
                        str(rootfs_output(ctx)),
                        "--runtime",
                        rootfs_runtime(ctx),
                    ),
                )
            )
    steps.append(Step("Summarize repository", ki2repo_cmd(ctx, "summary")))

    iso_enabled = bool_value(iso, "enabled", False) or ctx.include_iso
    if iso_enabled:
        iso_profile = str(iso.get("profile") or "bootstrap-stage1")
        iso_mode = str(iso.get("mode") or "installer")
        command = python_cmd(
            "tools/ki2bootiso.py",
            "--repo-root",
            str(ctx.repo_root),
            "--arch",
            ctx.arch,
            "--profile",
            iso_profile,
            "--mode",
            iso_mode,
            "--release-name",
            str(iso.get("release_name") or release_channel(ctx)),
        )
        if bool_value(rootfs, "enabled", True):
            command.extend(["--rootfs-dir", str(rootfs_output(ctx))])
        if bool_value(iso, "no_hyperv_vhdx", True):
            command.append("--no-hyperv-vhdx")
        steps.append(Step("Build bootable ISO", command))
    return steps


def command_text(command: list[str]) -> str:
    return " ".join(command)


def list_plans(repo_root: Path) -> list[Path]:
    return sorted((repo_root / "distro" / "build-plans").glob("*.yaml"))


def make_context(args: argparse.Namespace) -> BuildContext:
    repo_root = args.repo_root.resolve()
    plan_path = resolve_path(repo_root, args.build_plan)
    plan = load_build_plan(plan_path)
    release = plan.get("release", {})
    arch = args.arch or (str(release.get("arch")) if isinstance(release, dict) and release.get("arch") else "x86_64")
    release_id = args.release_id or dt.datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    run_dir = resolve_path(repo_root, args.run_dir, default=repo_root / ".ki2osbuild" / release_id)
    return BuildContext(
        repo_root=repo_root,
        plan_path=plan_path,
        plan=plan,
        arch=arch,
        jobs=args.jobs,
        toolchain_id=args.toolchain_id,
        run_dir=run_dir,
        include_iso=args.iso,
        skip_build=args.skip_build,
        skip_verify=args.skip_verify,
        force_key=args.force_key,
    )


def command_list(args: argparse.Namespace) -> None:
    repo_root = args.repo_root.resolve()
    plans = list_plans(repo_root)
    if not plans:
        print("no build plans found")
        return
    for path in plans:
        plan = load_build_plan(path)
        release = plan.get("release", {})
        channel = release.get("channel", "-") if isinstance(release, dict) else "-"
        print(f"{plan_name(plan):32} {channel:12} {rel(path, repo_root)}")


def command_plan(args: argparse.Namespace) -> None:
    ctx = make_context(args)
    print(f"plan: {plan_name(ctx.plan)}")
    print(f"channel: {release_channel(ctx)}")
    print(f"arch: {ctx.arch}")
    print(f"run-dir: {ctx.run_dir}")
    for index, step in enumerate(build_steps(ctx), start=1):
        targets = step.skip_if_exists if isinstance(step.skip_if_exists, tuple) else ((step.skip_if_exists,) if step.skip_if_exists else ())
        skip = f" [skip if all exist: {', '.join(str(path) for path in targets)}]" if targets else ""
        print(f"{index:02d}. {step.name}{skip}")
        print(f"    {command_text(step.command)}")


def run_step(ctx: BuildContext, step: Step, index: int, dry_run: bool) -> dict[str, Any]:
    record: dict[str, Any] = {
        "name": step.name,
        "command": step.command,
        "status": "pending",
        "started_at": now(),
        "finished_at": None,
        "returncode": None,
    }
    if step.skip_if_exists is not None:
        targets = step.skip_if_exists if isinstance(step.skip_if_exists, tuple) else (step.skip_if_exists,)
        present = [path.exists() for path in targets]
        if all(present):
            record["status"] = "skipped"
            record["finished_at"] = now()
            record["message"] = step.skip_message or "all required files exist"
            print(f"[skip] {step.name}: {record['message']}")
            return record
        if any(present):
            existing = ", ".join(str(path) for path, exists in zip(targets, present) if exists)
            missing = ", ".join(str(path) for path, exists in zip(targets, present) if not exists)
            raise OsBuildError(
                f"incomplete signing key set; existing: {existing}; missing: {missing}; use --force-key to replace the pair"
            )
    print(f"[run] {step.name}")
    print(f"      {command_text(step.command)}")
    if dry_run:
        record["status"] = "dry-run"
        record["finished_at"] = now()
        return record

    log_path = ctx.run_dir / f"{index:02d}-{slug(step.name)}.log"
    record["log"] = str(log_path)
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.run(step.command, cwd=ctx.repo_root, text=True, stdout=log, stderr=subprocess.STDOUT, check=False)
    record["returncode"] = proc.returncode
    record["finished_at"] = now()
    record["status"] = "succeeded" if proc.returncode == 0 else "failed"
    if proc.returncode != 0:
        raise OsBuildError(f"{step.name} failed with exit code {proc.returncode}; see {log_path}")
    return record


def command_run(args: argparse.Namespace) -> None:
    ctx = make_context(args)
    steps = build_steps(ctx)
    ctx.run_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "schema": "kiki-os-build-run-v1",
        "plan": plan_name(ctx.plan),
        "plan_path": str(ctx.plan_path),
        "channel": release_channel(ctx),
        "arch": ctx.arch,
        "run_dir": str(ctx.run_dir),
        "started_at": now(),
        "finished_at": None,
        "status": "running",
        "dry_run": args.dry_run,
        "steps": [],
    }
    try:
        for index, step in enumerate(steps, start=1):
            manifest["steps"].append(run_step(ctx, step, index, args.dry_run))
        manifest["status"] = "succeeded"
    except Exception:
        manifest["status"] = "failed"
        raise
    finally:
        manifest["finished_at"] = now()
        manifest_path = ctx.run_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"[manifest] {manifest_path}")


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-root", type=Path, default=default_repo_root())
    parser.add_argument("--build-plan", type=Path, default=Path(DEFAULT_PLAN))
    parser.add_argument("--arch", default="")
    parser.add_argument("--jobs", type=int, default=max(os.cpu_count() or 2, 2))
    parser.add_argument("--toolchain-id", default=ki2build.DEFAULT_TOOLCHAIN_ID)
    parser.add_argument("--run-dir", type=Path, default=None)
    parser.add_argument("--release-id", default="")
    parser.add_argument("--iso", action="store_true", help="also build the ISO declared by the build plan")
    parser.add_argument("--skip-build", action="store_true", help="skip package build and use existing packages")
    parser.add_argument("--skip-verify", action="store_true", help="skip Stage 2 verification steps")
    parser.add_argument("--force-key", action="store_true", help="overwrite repository signing key")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run declarative KIKI OS build plans")
    subcommands = parser.add_subparsers(dest="command", required=True)

    list_parser = subcommands.add_parser("list", help="list OS build plans")
    list_parser.add_argument("--repo-root", type=Path, default=default_repo_root())
    list_parser.set_defaults(func=command_list)

    plan_parser = subcommands.add_parser("plan", help="print generated OS build steps")
    add_common(plan_parser)
    plan_parser.set_defaults(func=command_plan)

    run_parser = subcommands.add_parser("run", help="execute an OS build plan")
    add_common(run_parser)
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.set_defaults(func=command_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (OsBuildError, OSError, json.JSONDecodeError, ki2build.Ki2Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
