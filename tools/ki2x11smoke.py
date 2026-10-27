"""Run cookie-authenticated Xvfb and X11 clients inside a disposable KIKI rootfs."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import ki2build


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rootfs", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--package", type=Path, help="extract the built package into the marked disposable root")
    args = p.parse_args()
    root = args.rootfs.resolve(strict=True)
    if not (root/".kiki-x11-disposable-test").is_file():
        raise ValueError("requires a marked disposable test rootfs")
    if args.package:
        manifest = ki2build.read_package_manifest(args.package)
        if manifest["name"] != "kiki-x11-runtime":
            raise ValueError("not the X11 runtime package")
        ki2build.extract_package_rootfs(args.package, root)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    def command(argv, **kwargs):
        return subprocess.run(["chroot", str(root), *argv], capture_output=True, text=True,
                              timeout=30, **kwargs)
    check = command(["/usr/bin/kiki-x11-check"], check=True)
    (out/"preflight.txt").write_text(check.stdout)
    for binary in ["/usr/libexec/Xorg", "/usr/bin/Xvfb", "/usr/bin/xterm"]:
        command(["/lib64/ld-linux-x86-64.so.2", "--list", binary], check=True)
    auth = root/"tmp/x11-test.auth"
    auth.touch(mode=0o600, exist_ok=False)
    command(["/usr/bin/xauth", "-q", "-f", "/tmp/x11-test.auth", "source", "-"],
            input="add :97 MIT-MAGIC-COOKIE-1 "+secrets.token_hex(16)+"\n", check=True)
    server = None
    checks = {}
    try:
        with (out/"xvfb.log").open("w") as log:
            server = subprocess.Popen(["chroot", str(root), "/usr/bin/Xvfb", ":97",
                                       "-screen", "0", "1024x768x24", "-nolisten", "tcp",
                                       "-auth", "/tmp/x11-test.auth"], stdout=log, stderr=log)
            env = ["/usr/bin/env", "DISPLAY=:97", "XAUTHORITY=/tmp/x11-test.auth"]
            for _ in range(40):
                info = command(env+["/usr/bin/xdpyinfo"])
                if info.returncode == 0 or server.poll() is not None:
                    break
                time.sleep(.25)
            checks["xvfb_and_xdpyinfo"] = info.returncode == 0
            (out/"xdpyinfo.txt").write_text(info.stdout+info.stderr)
            denied = command(["/usr/bin/env", "DISPLAY=:97", "XAUTHORITY=/tmp/nonexistent-auth",
                              "/usr/bin/xdpyinfo"])
            checks["unauthenticated_client_rejected"] = denied.returncode != 0
            (root/"tmp/xterm-result").unlink(missing_ok=True)
            client = command(env+["/usr/bin/xterm", "-e", "/bin/sh", "-c",
                                 "echo XTERM_CLIENT_OK > /tmp/xterm-result"])
            checks["xterm_client"] = client.returncode == 0 and (root/"tmp/xterm-result").read_text().strip() == "XTERM_CLIENT_OK"
            (out/"xterm.txt").write_text(client.stdout+client.stderr)
    finally:
        if server is not None and server.poll() is None:
            server.terminate()
            server.wait(timeout=10)
        auth.unlink(missing_ok=True)
    report = {"success": all(checks.values()) and len(checks)==3, "checks": checks,
              "scope": "isolated KIKI rootfs Xvfb; physical Xorg/VT/Hyper-V input not tested"}
    (out/"result.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report,indent=2))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
