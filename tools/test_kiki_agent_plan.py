from __future__ import annotations

import functools
import http.server
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        return


class KikiAgentPlanTests(unittest.TestCase):
    def test_cli_promotes_ed25519_signed_kernel_plan(self):
        with tempfile.TemporaryDirectory(prefix="kiki-agent-plan-test-") as tmp:
            base = Path(tmp)
            server_root = base / "server"
            target_root = base / "target"
            binary = base / "kiki-agent-stage3"
            private_key = base / "install-plan.ed25519"
            public_key = target_root / "etc/kiki/trust/install-plan.ed25519.pub"
            plan = server_root / "install-plan.yaml"
            signature = server_root / "install-plan.yaml.sig"
            server_root.mkdir(parents=True)
            public_key.parent.mkdir(parents=True)
            (target_root / "proc").mkdir(parents=True)
            shutil.copy2(REPO_ROOT / "distro/install-plans/kiki-kube-compute.yaml", plan)
            subprocess.run(
                ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private_key)],
                check=True,
            )
            subprocess.run(
                ["openssl", "pkey", "-in", str(private_key), "-pubout", "-out", str(public_key)],
                check=True,
            )
            subprocess.run(
                [
                    "openssl",
                    "pkeyutl",
                    "-sign",
                    "-inkey",
                    str(private_key),
                    "-rawin",
                    "-in",
                    str(plan),
                    "-out",
                    str(signature),
                ],
                check=True,
            )
            subprocess.run(
                [
                    "go",
                    "build",
                    "-mod=vendor",
                    "-buildvcs=false",
                    "-o",
                    str(binary),
                    "./cmd/kiki-agent",
                ],
                cwd=REPO_ROOT,
                env={**os.environ, "GOCACHE": str(base / "go-cache")},
                check=True,
            )

            handler = functools.partial(QuietHandler, directory=str(server_root))
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}/install-plan.yaml"
                (target_root / "proc/cmdline").write_text(
                    f"quiet kiki.plan.url={url} kiki.plan.signature={url}.sig\n",
                    encoding="utf-8",
                )
                result = subprocess.run(
                    [str(binary), "plan", "fetch", "--root", str(target_root)],
                    cwd=REPO_ROOT,
                    text=True,
                    capture_output=True,
                    check=False,
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("verified=true method=ed25519", result.stdout)
            promoted = target_root / "run/kiki/install-plan.yaml"
            self.assertEqual(promoted.read_bytes(), plan.read_bytes())


if __name__ == "__main__":
    unittest.main()
