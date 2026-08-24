#!/usr/bin/env python3
"""Interactive management console for KIKI OS pre-ISO workflows."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TextIO


DEFAULT_PLAN = "distro/build-plans/stage3-server-core.yaml"
STAGE3_PLAN = "docs/kiki-stage3-v3-plan.ko.md"
REQUIRED_TOOLS = ("python3", "go", "git", "tar", "file", "readelf")
ISO_TOOL_GROUPS = (("xorriso",), ("grub-mkrescue", "grub2-mkrescue"))


class ConsoleError(RuntimeError):
    pass


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def run_capture(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def git_snapshot(repo_root: Path) -> dict[str, Any]:
    branch = run_capture(["git", "branch", "--show-current"], cwd=repo_root)
    status = run_capture(["git", "status", "--porcelain"], cwd=repo_root)
    upstream = run_capture(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"], cwd=repo_root)
    ahead = behind = None
    upstream_name = upstream.stdout.strip() if upstream.returncode == 0 else ""
    if upstream_name:
        counts = run_capture(["git", "rev-list", "--left-right", "--count", f"{upstream_name}...HEAD"], cwd=repo_root)
        if counts.returncode == 0:
            values = counts.stdout.split()
            if len(values) == 2:
                behind, ahead = (int(values[0]), int(values[1]))
    changed = [line for line in status.stdout.splitlines() if line.strip()]
    return {
        "branch": branch.stdout.strip() or "detached",
        "upstream": upstream_name or None,
        "ahead": ahead,
        "behind": behind,
        "clean": not changed,
        "changed_files": len(changed),
    }


def stage3_progress(repo_root: Path) -> dict[str, int]:
    path = repo_root / STAGE3_PLAN
    total = done = 0
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("- [x]") or line.startswith("- [ ]"):
                total += 1
                done += int(line.startswith("- [x]"))
    return {"done": done, "pending": total - done, "total": total}


def artifact_snapshot(repo_root: Path, arch: str) -> dict[str, Any]:
    package_dir = repo_root / "dist" / "ki2" / "packages" / arch
    rootfs_dir = repo_root / "dist" / "rootfs"
    iso_dir = repo_root / "dist" / "iso"
    run_root = repo_root / ".ki2osbuild"
    packages = sorted(package_dir.glob("*.ki2")) if package_dir.is_dir() else []
    rootfs = sorted(path for path in rootfs_dir.iterdir() if path.is_dir()) if rootfs_dir.is_dir() else []
    isos = sorted(iso_dir.glob("*.iso")) if iso_dir.is_dir() else []
    manifests = sorted(run_root.glob("*/manifest.json"), key=lambda path: path.stat().st_mtime, reverse=True) if run_root.is_dir() else []
    recent: dict[str, Any] | None = None
    if manifests:
        try:
            data = json.loads(manifests[0].read_text(encoding="utf-8"))
            recent = {
                "path": relative(manifests[0], repo_root),
                "status": data.get("status", "unknown"),
                "plan": data.get("plan", "unknown"),
            }
        except (OSError, json.JSONDecodeError):
            recent = {"path": relative(manifests[0], repo_root), "status": "invalid", "plan": "unknown"}
    return {
        "packages": len(packages),
        "package_bytes": sum(path.stat().st_size for path in packages),
        "rootfs": [relative(path, repo_root) for path in rootfs],
        "isos": [
            {"path": relative(path, repo_root), "bytes": path.stat().st_size}
            for path in isos
        ],
        "repository_index": (repo_root / "dist" / "ki2" / "repo" / f"index.{arch}.json").is_file(),
        "recent_run": recent,
    }


def collect_status(repo_root: Path, arch: str) -> dict[str, Any]:
    plan = repo_root / DEFAULT_PLAN
    return {
        "schema": "kiki-console-status-v1",
        "repo_root": str(repo_root),
        "git": git_snapshot(repo_root),
        "stage3": stage3_progress(repo_root),
        "default_plan": relative(plan, repo_root),
        "default_plan_exists": plan.is_file(),
        "artifacts": artifact_snapshot(repo_root, arch),
    }


def human_size(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def print_status(data: dict[str, Any], out: TextIO = sys.stdout) -> None:
    git = data["git"]
    progress = data["stage3"]
    artifacts = data["artifacts"]
    sync = "upstream 없음"
    if git["upstream"]:
        sync = f"ahead {git['ahead']} / behind {git['behind']}"
    tree = "깨끗함" if git["clean"] else f"변경 {git['changed_files']}개"
    print("KIKI OS 관리 콘솔", file=out)
    print(f"  브랜치       {git['branch']} ({sync})", file=out)
    print(f"  작업 트리    {tree}", file=out)
    print(f"  Stage 3      {progress['done']}/{progress['total']} 완료, {progress['pending']}개 대기", file=out)
    print(f"  기본 계획    {data['default_plan']} ({'준비됨' if data['default_plan_exists'] else '없음'})", file=out)
    print(f"  패키지       {artifacts['packages']}개 / {human_size(artifacts['package_bytes'])}", file=out)
    print(f"  저장소 인덱스 {'있음' if artifacts['repository_index'] else '없음'}", file=out)
    print(f"  rootfs       {len(artifacts['rootfs'])}개", file=out)
    print(f"  ISO          {len(artifacts['isos'])}개", file=out)
    if artifacts["recent_run"]:
        run = artifacts["recent_run"]
        print(f"  최근 실행    {run['status']} / {run['plan']} / {run['path']}", file=out)


def command_status(args: argparse.Namespace) -> int:
    data = collect_status(args.repo_root.resolve(), args.arch)
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print_status(data)
    return 0


def executable_available(name: str) -> bool:
    return shutil.which(name) is not None


def run_check(name: str, command: list[str], *, cwd: Path) -> Check:
    result = run_capture(command, cwd=cwd)
    detail = (result.stdout or result.stderr).strip().splitlines()
    summary = "통과" if result.returncode == 0 else (detail[-1] if detail else "명령 실패")
    return Check(name, "pass" if result.returncode == 0 else "fail", summary)


def doctor_checks(repo_root: Path, arch: str, plan: Path, *, include_iso: bool) -> list[Check]:
    checks: list[Check] = []
    for tool in REQUIRED_TOOLS:
        checks.append(Check(f"도구:{tool}", "pass" if executable_available(tool) else "fail", shutil.which(tool) or "찾을 수 없음"))
    for alternatives in ISO_TOOL_GROUPS:
        found = next((shutil.which(tool) for tool in alternatives if executable_available(tool)), None)
        label = "/".join(alternatives)
        available = found is not None
        status = "pass" if available else ("fail" if include_iso else "warn")
        checks.append(Check(f"ISO 도구:{label}", status, found or "ISO 생성 전에 설치 필요"))
    if not plan.is_file():
        checks.append(Check("빌드 계획", "fail", f"없음: {plan}"))
        return checks
    checks.append(Check("빌드 계획", "pass", relative(plan, repo_root)))
    checks.append(
        run_check(
            "Stage 3 계약",
            [sys.executable, "tools/ki2stage3.py", "verify"],
            cwd=repo_root,
        )
    )
    plan_command = [sys.executable, "tools/ki2osbuild.py", "plan", "--repo-root", str(repo_root), "--arch", arch, "--build-plan", str(plan)]
    if include_iso:
        plan_command.append("--iso")
    checks.append(run_check("빌드 계획 렌더링", plan_command, cwd=repo_root))
    checks.append(run_check("Git 공백 검사", ["git", "diff", "--check"], cwd=repo_root))
    return checks


def print_checks(checks: list[Check], out: TextIO = sys.stdout) -> None:
    labels = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}
    for check in checks:
        print(f"[{labels[check.status]}] {check.name}: {check.detail}", file=out)
    failed = sum(check.status == "fail" for check in checks)
    warned = sum(check.status == "warn" for check in checks)
    print(f"결과: 실패 {failed}, 경고 {warned}, 전체 {len(checks)}", file=out)


def command_doctor(args: argparse.Namespace) -> int:
    repo_root = args.repo_root.resolve()
    plan = resolve_plan(repo_root, args.build_plan)
    checks = doctor_checks(repo_root, args.arch, plan, include_iso=args.iso)
    if args.json:
        print(json.dumps([asdict(check) for check in checks], indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print_checks(checks)
    return 1 if any(check.status == "fail" for check in checks) else 0


def resolve_plan(repo_root: Path, value: Path) -> Path:
    return value.resolve() if value.is_absolute() else (repo_root / value).resolve()


def osbuild_command(args: argparse.Namespace, action: str, *, include_iso: bool = False) -> list[str]:
    repo_root = args.repo_root.resolve()
    plan = resolve_plan(repo_root, args.build_plan)
    command = [
        sys.executable,
        "tools/ki2osbuild.py",
        action,
        "--repo-root",
        str(repo_root),
        "--build-plan",
        str(plan),
        "--arch",
        args.arch,
        "--jobs",
        str(args.jobs),
    ]
    if include_iso:
        command.append("--iso")
    if getattr(args, "skip_build", False):
        command.append("--skip-build")
    if getattr(args, "dry_run", False):
        command.append("--dry-run")
    if getattr(args, "run_dir", None):
        command.extend(["--run-dir", str(args.run_dir)])
    return command


def execute(command: list[str], *, cwd: Path) -> int:
    print("$ " + shlex.join(command), flush=True)
    return subprocess.run(command, cwd=cwd, check=False).returncode


def command_plan(args: argparse.Namespace) -> int:
    return execute(osbuild_command(args, "plan", include_iso=args.iso), cwd=args.repo_root.resolve())


def command_verify(args: argparse.Namespace) -> int:
    return execute([sys.executable, "tools/ki2stage3.py", "verify"], cwd=args.repo_root.resolve())


def command_build(args: argparse.Namespace) -> int:
    return execute(osbuild_command(args, "run"), cwd=args.repo_root.resolve())


def command_iso(args: argparse.Namespace) -> int:
    if not args.yes:
        if not sys.stdin.isatty():
            raise ConsoleError("ISO 빌드는 --yes로 명시적으로 승인해야 합니다")
        answer = input("패키지·rootfs 검증 후 ISO 빌드를 실행할까요? [y/N] ").strip().lower()
        if answer not in {"y", "yes", "예"}:
            print("취소했습니다.")
            return 0
    return execute(osbuild_command(args, "run", include_iso=True), cwd=args.repo_root.resolve())


def command_artifacts(args: argparse.Namespace) -> int:
    data = artifact_snapshot(args.repo_root.resolve(), args.arch)
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True))
        return 0
    print(f"패키지: {data['packages']}개 / {human_size(data['package_bytes'])}")
    print("rootfs:")
    for item in data["rootfs"] or ["(없음)"]:
        print(f"  {item}")
    print("ISO:")
    if data["isos"]:
        for item in data["isos"]:
            print(f"  {item['path']} ({human_size(item['bytes'])})")
    else:
        print("  (없음)")
    return 0


def shell_help(out: TextIO = sys.stdout) -> None:
    print("명령: status, doctor, verify, plan, build, iso, artifacts, help, quit", file=out)
    print("ISO 실제 빌드는 'iso --yes'처럼 명시적으로 승인해야 합니다.", file=out)


def shell_dispatch(line: str, base: list[str]) -> int | None:
    words = shlex.split(line)
    if not words:
        return 0
    if words[0] in {"quit", "exit"}:
        return None
    if words[0] == "help":
        shell_help()
        return 0
    return main([words[0], *base, *words[1:]], interactive_child=True)


def command_shell(args: argparse.Namespace) -> int:
    base = ["--repo-root", str(args.repo_root.resolve()), "--arch", args.arch, "--jobs", str(args.jobs), "--build-plan", str(args.build_plan)]
    print("KIKI OS 대화형 관리 콘솔입니다. 'help'로 명령을 확인하세요.")
    while True:
        try:
            line = input("kiki> ")
        except EOFError:
            print()
            return 0
        try:
            result = shell_dispatch(line, base)
        except (ConsoleError, ValueError) as exc:
            print(f"오류: {exc}", file=sys.stderr)
            continue
        if result is None:
            return 0


def add_common(parser: argparse.ArgumentParser, *, plan: bool = False) -> None:
    parser.add_argument("--repo-root", type=Path, default=default_repo_root())
    parser.add_argument("--arch", default="x86_64")
    if plan:
        parser.add_argument("--build-plan", type=Path, default=Path(DEFAULT_PLAN))
        parser.add_argument("--jobs", type=int, default=max(os.cpu_count() or 2, 2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="KIKI OS ISO 사전 관리 콘솔")
    subcommands = parser.add_subparsers(dest="command", required=True)

    status = subcommands.add_parser("status", help="Git, Stage 3, 빌드 산출물 상태 표시")
    add_common(status)
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=command_status)

    doctor = subcommands.add_parser("doctor", help="Stage 3 및 ISO 빌드 준비도 검사")
    add_common(doctor, plan=True)
    doctor.add_argument("--iso", action="store_true", help="ISO 도구 누락도 실패로 처리")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=command_doctor)

    verify = subcommands.add_parser("verify", help="Stage 3 종합 검증 실행")
    add_common(verify)
    verify.set_defaults(func=command_verify)

    plan = subcommands.add_parser("plan", help="실행할 OS 빌드 단계 표시")
    add_common(plan, plan=True)
    plan.add_argument("--iso", action="store_true")
    plan.set_defaults(func=command_plan)

    build = subcommands.add_parser("build", help="ISO를 제외한 패키지·저장소·rootfs 빌드")
    add_common(build, plan=True)
    build.add_argument("--skip-build", action="store_true")
    build.add_argument("--dry-run", action="store_true")
    build.add_argument("--run-dir", type=Path)
    build.set_defaults(func=command_build)

    iso = subcommands.add_parser("iso", help="검증을 포함한 설치 ISO 빌드")
    add_common(iso, plan=True)
    iso.add_argument("--skip-build", action="store_true")
    iso.add_argument("--dry-run", action="store_true")
    iso.add_argument("--run-dir", type=Path)
    iso.add_argument("--yes", action="store_true", help="실제 ISO 빌드 승인")
    iso.set_defaults(func=command_iso)

    artifacts = subcommands.add_parser("artifacts", help="패키지, rootfs, ISO 산출물 표시")
    add_common(artifacts)
    artifacts.add_argument("--json", action="store_true")
    artifacts.set_defaults(func=command_artifacts)

    shell = subcommands.add_parser("shell", help="대화형 관리 콘솔 시작")
    add_common(shell, plan=True)
    shell.set_defaults(func=command_shell)
    return parser


def main(argv: list[str] | None = None, *, interactive_child: bool = False) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if not values:
        values = ["shell" if sys.stdin.isatty() else "status"]
    parser = build_parser()
    try:
        args = parser.parse_args(values)
        return int(args.func(args) or 0)
    except (ConsoleError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except SystemExit:
        if interactive_child:
            return 2
        raise


if __name__ == "__main__":
    raise SystemExit(main())
