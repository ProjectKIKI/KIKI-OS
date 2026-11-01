#!/usr/bin/python3
"""Shared, JSON-speaking backend for the native KIKI administrator and CLI.

Read commands never elevate. The fixed polkit helper accepts only reviewed
operations against /; it cannot accept a shell command, environment or root path.
"""
import argparse
import contextlib
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import runpy
import shlex
import subprocess
import sys
from types import SimpleNamespace
from urllib.parse import urlsplit

VERSION = "0.1.0"
ENV = dict(PATH="/usr/sbin:/usr/bin:/sbin:/bin", LC_ALL="C", LANG="C", HOME="/root")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}\Z")
UNIT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@:+\\-]{0,200}\.service\Z")


class AdminError(RuntimeError):
    pass


def command(argv, timeout=30):
    try:
        proc = subprocess.run(argv, env=ENV, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
        return dict(code=proc.returncode, stdout=proc.stdout[-262144:].strip(),
                    stderr=proc.stderr[-16384:].strip())
    except (OSError, subprocess.TimeoutExpired) as error:
        return dict(code=1, stdout="", stderr=str(error))


def checked(argv, timeout=30):
    result = command(argv, timeout)
    if result["code"]:
        raise AdminError(result["stderr"] or result["stdout"] or "명령을 실행하지 못했습니다.")
    return result["stdout"]


def identifier(value):
    if not NAME.fullmatch(value):
        raise AdminError("올바른 패키지·그룹·저장소 이름을 입력하세요.")
    return value


class Backend:
    def __init__(self, root=Path("/"), ki2_path=Path("/usr/bin/ki2ctl")):
        # Alternate roots are a Python test seam, never a privileged CLI option.
        self.root = Path(root)
        self.ki2_path = ki2_path
        self.ki2 = SimpleNamespace(**runpy.run_path(str(ki2_path), run_name="kiki_admin_ki2"))

    def path(self, value):
        return self.root / value.lstrip("/")

    def read(self, value, default):
        path = self.path(value)
        return json.loads(path.read_text()) if path.exists() else default

    def failed(self):
        result = command(["/usr/bin/systemctl", "--failed", "--type=service", "--no-legend", "--plain", "--no-pager"])
        rows = []
        for line in result["stdout"].splitlines():
            parts = line.lstrip("● ").split(None, 4)
            if len(parts) >= 4 and UNIT.fullmatch(parts[0]):
                rows.append(dict(unit=parts[0], description=parts[4] if len(parts) > 4 else parts[0]))
        return rows, result["stderr"] if result["code"] else ""

    def packages(self):
        k = self.ki2
        db = k.load_installed(self.root)
        installed = db.get("packages", {})
        groups = k.load_package_groups(self.root)
        indexes = k.load_saved_indexes(self.root, platform.machine())
        catalog = k.package_catalog(indexes)
        rows = []
        for name, record in sorted(installed.items()):
            candidate = catalog.get(name)
            newer = bool(candidate and k.package_sort_key(candidate[1]) > k.installed_sort_key(record))
            rows.append(dict(name=name, version=k.package_version_label(record),
                             summary=str(record.get("summary", "")), update=newer,
                             available=k.package_version_label(candidate[1]) if candidate else ""))
        group_rows = []
        for name, group in groups.items():
            _, names, _, _ = k.resolve_package_group(groups, name)
            if group.get("selectable") is False:
                continue
            count = sum(p in installed for p in names)
            available, reason = True, ""
            try:
                k.resolve_packages(catalog, names)
            except k.Ki2CtlError as error:
                available, reason = False, "현재 저장소에 필요한 패키지가 없습니다: " + str(error)
            group_rows.append(dict(id=name, name=group.get("name_ko", name),
                                   description=group.get("description_ko", ""),
                                   available=available, unavailable_reason=reason,
                                   installed=name in db.get("groups", {}), configured=count == len(names), total=len(names), present=count))
        repos = []
        policy = k.repository_policy(self.root)
        for repo in k.load_configured_repos(self.root):
            key = k.repo_verify_key_path(self.root, repo, None, policy)
            cache = k.repo_state_dir(self.root, repo.name) / ("index." + platform.machine() + ".json")
            repos.append(dict(name=repo.name, url=repo.url, signed=bool(key and key.is_file()),
                              key=str(key or ""), cached=cache.exists(),
                              cache_time=datetime.datetime.fromtimestamp(cache.stat().st_mtime).astimezone().isoformat(timespec="seconds") if cache.exists() else ""))
        hooks = k.load_pending_hooks(self.root).get("hooks", [])
        return dict(installed=rows, groups=group_rows, repos=repos, updates=sum(r["update"] for r in rows),
                    cached=bool(indexes), hooks=[h for h in hooks if h.get("status", "pending") not in {"succeeded", "applied"}])

    def snapshot(self):
        warnings = []
        info = {}
        os_release = self.path("/etc/os-release")
        if os_release.exists():
            for line in os_release.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    try:
                        info[key] = " ".join(shlex.split(value))
                    except ValueError:
                        pass
        failed, service_error = self.failed()
        if service_error:
            warnings.append("서비스 상태 조회: " + service_error)
        disks = []
        seen = set()
        mounts = []
        try:
            # Kernel mountinfo works on minimal KIKI images whose util-linux
            # build does not include findmnt's optional JSON frontend.
            def unescape(value):
                return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), value)
            for line in self.path("/proc/self/mountinfo").read_text().splitlines():
                before, after = line.split(" - ", 1)
                fields, fs = before.split(), after.split()
                mounts.append(dict(target=unescape(fields[4]), source=unescape(fs[1]), fstype=fs[0]))
        except (OSError, ValueError, IndexError) as error:
            warnings.append("저장 장치 목록 조회: " + str(error))
        for mount in mounts:
            target = mount.get("target", "")
            if mount.get("fstype") not in {"ext2", "ext3", "ext4", "xfs", "btrfs", "vfat", "f2fs"}:
                continue
            try:
                path = self.path(target)
                dev = path.stat().st_dev
                if dev in seen:
                    continue
                usage = os.statvfs(path)
                seen.add(dev)
                disks.append(dict(mount=target, source=mount.get("source", ""),
                                  total=usage.f_blocks * usage.f_frsize, free=usage.f_bavail * usage.f_frsize,
                                  used=(usage.f_blocks - usage.f_bfree) * usage.f_frsize))
            except OSError as error:
                warnings.append(target + ": " + str(error))
        if not disks:
            warnings.append("사용 가능한 로컬 파일시스템의 여유 공간을 확인하지 못했습니다.")
        try:
            packages = self.packages()
        except (OSError, ValueError, RuntimeError) as error:
            packages = dict(installed=[], groups=[], repos=[], updates=0, cached=False, hooks=[])
            warnings.append("패키지 정보 조회: " + str(error))
        return dict(schema="kiki-admin-v1", version=VERSION,
                    observed_at=datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                    os=info.get("PRETTY_NAME", "KIKI OS"), kernel=platform.release(), hostname=platform.node(),
                    disks=disks, failed=failed, warnings=warnings, **packages)

    def fingerprint(self):
        paths = [self.path(p) for p in ["/var/lib/ki2/installed.json", "/var/lib/ki2/pending-hooks.json",
                                       "/usr/share/ki2/package-groups.json", "/etc/ki2/policy.json"]]
        for directory in ["/etc/ki2/repos.d", "/etc/ki2/trust", "/var/lib/ki2/repos"]:
            base = self.path(directory)
            if base.exists():
                paths.extend(p for p in base.rglob("*") if p.is_file())
        digest = hashlib.sha256()
        for path in sorted(set(paths)):
            digest.update(str(path.relative_to(self.root)).encode())
            digest.update(path.read_bytes() if path.exists() else b"<missing>")
        return digest.hexdigest()

    def operation(self, action, target=""):
        k = self.ki2
        args = [str(self.ki2_path)]
        if action == "security-scan":
            if target:raise AdminError("보안 검사는 고정된 KIKI 정책만 실행합니다.")
            if not self.path('/usr/libexec/kiki-security-scan').is_file():raise AdminError("security-audit 그룹을 먼저 설치하세요.")
            return ['/usr/libexec/kiki-security-scan'], "고정된 OpenSCAP 정책으로 시스템 설정을 검사합니다. 설정을 자동 수정하지 않습니다. 결과의 fail·error 항목을 확인하세요."
        if action == "refresh":
            repos = self.packages()["repos"]
            if not repos:
                raise AdminError("등록된 저장소가 없습니다. 저장소 화면에서 먼저 추가하세요.")
            if any(not r["signed"] for r in repos):
                raise AdminError("모든 저장소에 서명 공개키를 먼저 설정하세요.")
            return args + ["update", "--require-signature"], "저장소의 서명과 인덱스 해시를 검증하고 목록을 새로 받습니다. 패키지 파일은 변경하지 않습니다."
        if action == "upgrade":
            return args + ["upgrade"], "설치된 패키지를 캐시된 저장소의 새 버전으로 업데이트합니다."
        if action in {"group-install", "group-upgrade"}:
            identifier(target)
            groups = k.load_package_groups(self.root)
            if target not in groups or groups[target].get("selectable") is False:
                raise AdminError("선택할 수 없는 패키지 그룹입니다.")
            return args + ["group", action.split("-", 1)[1], target], groups[target].get("description_ko", target)
        if action == "hooks":
            return args + ["hooks", "apply"], "패키지 설치 후 남은 캐시·색인 갱신 작업을 실행합니다."
        if action == "restart":
            if not UNIT.fullmatch(target):
                raise AdminError("올바른 서비스 이름이 아닙니다.")
            failed, error = self.failed()
            if error or target not in {r["unit"] for r in failed}:
                raise AdminError("현재 실패 상태인 서비스만 복구할 수 있습니다. 상태를 새로 확인하세요.")
            return ["/usr/bin/systemctl", "restart", target], "실패한 서비스를 다시 시작합니다. 서비스 연결이 잠시 끊길 수 있습니다."
        if action == "system-logs":
            if target and not UNIT.fullmatch(target):
                raise AdminError("올바른 서비스 이름이 아닙니다.")
            argv = ["/usr/bin/journalctl", "--boot", "--no-pager", "--output=short-iso", "--lines=200"]
            argv += ["--unit=" + target] if target else ["--priority=warning"]
            return argv, "관리자 인증 후 " + (target or "시스템 경고·오류") + " 로그의 최근 200줄을 조회합니다. 시스템 설정은 변경하지 않습니다."
        if action == "repo-remove":
            identifier(target)
            if target not in {r.name for r in k.load_configured_repos(self.root)}:
                raise AdminError("등록되지 않은 저장소입니다.")
            return args + ["repo", "remove", target], "이 저장소의 설정과 캐시된 목록을 제거합니다. 설치된 패키지는 유지합니다."
        if action == "repo-set":
            try:
                item = json.loads(target)
                name, url, key = (item[n] for n in ("name", "url", "key"))
            except (ValueError, TypeError, KeyError):
                raise AdminError("저장소 이름·HTTPS 주소·공개키 경로가 필요합니다.")
            identifier(name)
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise AdminError("인증 정보·쿼리가 없는 HTTPS 저장소 주소를 입력하세요.")
            trust = self.path("/etc/ki2/trust").resolve()
            key_path = self.path(key).resolve()
            if not key_path.is_relative_to(trust) or not key_path.is_file():
                raise AdminError("/etc/ki2/trust 아래에 설치된 공개키를 선택하세요.")
            stat = key_path.stat()
            if stat.st_uid != 0 or stat.st_mode & 0o022:
                raise AdminError("공개키는 root 소유이며 다른 사용자가 수정할 수 없어야 합니다.")
            try:
                k.parse_ed25519_public_key(key_path.read_bytes())
            except ValueError:
                raise AdminError("KI2 형식의 Ed25519 공개키를 선택하세요. 개인키는 사용할 수 없습니다.")
            return args + ["repo", "set", url, "--name", name, "--verify-key", "/" + str(key_path.relative_to(self.root))], "서명 공개키를 사용하는 HTTPS 저장소를 등록하거나 갱신합니다."
        raise AdminError("지원하지 않는 관리 작업입니다.")

    def plan(self, action, target=""):
        argv, description = self.operation(action, target)
        details = ""
        if action in {"upgrade", "group-install", "group-upgrade", "hooks"}:
            # Call the very same KI2 parser/resolver as the CLI. Dry runs only
            # use existing indexes, never the --repo fetch-and-save override.
            args = self.ki2.build_parser().parse_args(argv[1:] + ["--dry-run"])
            args.root = self.root
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                args.func(args)
            details = output.getvalue().strip()
        state = self.fingerprint()
        token = hashlib.sha256(json.dumps([action, target, state, details], ensure_ascii=False).encode()).hexdigest()
        return dict(action=action, target=target, description=description,
                    details=details or shlex.join(argv), token=token)

    def apply(self, action, target, token):
        if self.root != Path("/") or os.geteuid() != 0:
            raise AdminError("시스템 변경에는 관리자 인증이 필요합니다.")
        import fcntl
        # Only this application lock is claimed; existing KI2 transactions are
        # also checked below, including operations started from another client.
        with open("/run/lock/kiki-admin.lock", "a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise AdminError("다른 관리 작업이 실행 중입니다.")
            for path in self.path("/var/lib/ki2/transactions").glob("*.json"):
                tx = json.loads(path.read_text())
                if tx.get("status") in {"running", "preparing", "applying"}:
                    raise AdminError("진행 중인 KI2 트랜잭션이 있습니다. 진단 화면에서 확인하세요.")
            with self.ki2.mutation_lock(self.root):
                plan = self.plan(action, target)
                if not re.fullmatch(r"[0-9a-f]{64}", token) or plan["token"] != token:
                    raise AdminError("검토 후 시스템 상태가 바뀌었습니다. 새 계획을 확인하세요.")
                argv, _ = self.operation(action, target)
                if argv[0] == str(self.ki2_path):
                    args = self.ki2.build_parser().parse_args(argv[1:])
                    args.root = self.root
                    output = io.StringIO()
                    os.environ.clear()
                    os.environ.update(ENV)
                    with contextlib.redirect_stdout(output):
                        args.func(args)
                    result = dict(code=0, stdout=output.getvalue(), stderr="")
                else:
                    result = command(argv, timeout=240 if action == 'security-scan' else 120)
            command(["/usr/bin/logger", "--tag", "kiki-admin", "--", "action=" + action + " status=" + str(result["code"])])
            if result["code"]:
                raise AdminError(result["stderr"] + "\n" + result["stdout"])
            return dict(message="작업을 완료했습니다.", output=result["stdout"], action=action)

    def logs(self, unit=""):
        if unit and not UNIT.fullmatch(unit):
            raise AdminError("올바른 서비스 이름이 아닙니다.")
        argv = ["/usr/bin/journalctl", "--boot", "--no-pager", "--output=short-iso", "--lines=200"]
        argv += ["--unit=" + unit] if unit else ["--priority=warning"]
        result = command(argv)
        if result["code"]:
            raise AdminError(result["stderr"] or "로그에 접근할 수 없습니다.")
        return dict(unit=unit, output=result["stdout"], notice=result["stderr"])

    def diagnose(self):
        snapshot = self.snapshot()
        issues = []
        for disk in snapshot["disks"]:
            if disk["total"] and disk["free"] / disk["total"] < .1:
                issues.append(disk["mount"] + "의 여유 공간이 10% 미만입니다. 저장 파일과 패키지 캐시를 검토하세요.")
        issues += [r["unit"] + ": 서비스가 실패했습니다. 해당 로그를 확인한 뒤 다시 시작하세요." for r in snapshot["failed"]]
        if not snapshot["repos"]:
            issues.append("등록된 KI2 저장소가 없습니다.")
        elif not snapshot["cached"]:
            issues.append("로컬 패키지 목록이 없습니다. 저장소 목록을 동기화하세요.")
        issues += [r["name"] + ": 서명 공개키가 없습니다." for r in snapshot["repos"] if not r["signed"]]
        if snapshot["hooks"]:
            issues.append("완료되지 않은 패키지 후처리가 있습니다. 후처리 계획을 확인하세요.")
        transactions = []
        for path in self.path("/var/lib/ki2/transactions").glob("*.json"):
            tx = json.loads(path.read_text())
            if tx.get("status") not in {"succeeded", "rolled-back"}:
                transactions.append(dict(id=path.stem, status=tx.get("status", "unknown")))
        issues += ["KI2 트랜잭션 " + tx["id"] + ": " + tx["status"] + ". 설치 이력을 확인하세요." for tx in transactions]
        return dict(observed_at=snapshot["observed_at"], issues=issues, warnings=snapshot["warnings"], transactions=transactions,
                    summary="확인이 필요한 항목이 있습니다." if issues or snapshot["warnings"] else "현재 검사에서 발견한 문제가 없습니다.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="KIKI 시스템 관리자 JSON CLI")
    parser.add_argument("command", choices=["snapshot", "diagnose", "logs", "plan", "apply"])
    parser.add_argument("action", nargs="?", default="")
    parser.add_argument("target", nargs="?", default="")
    parser.add_argument("token", nargs="?", default="")
    args = parser.parse_args(argv)
    try:
        backend = Backend()
        if args.command == "apply":
            result = backend.apply(args.action, args.target, args.token)
        elif args.command == "plan":
            result = backend.plan(args.action, args.target)
        elif args.command == "logs":
            result = backend.logs(args.action)
        else:
            result = getattr(backend, args.command)()
        print(json.dumps(dict(ok=True, **result), ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        print(json.dumps(dict(ok=False, error=str(error)), ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
