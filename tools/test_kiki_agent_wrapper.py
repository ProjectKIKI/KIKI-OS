from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "distro/sources/kiki-agent/usr/bin/kiki-agent"


def load_agent():
    loader = importlib.machinery.SourceFileLoader("kiki_agent_wrapper", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class KikiAgentWrapperTests(unittest.TestCase):
    def test_kube_reconcile_delegates_to_stage3_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "kiki-agent-stage3"
            binary.write_text("stage3\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"KIKI_STAGE3_AGENT": str(binary)}):
                module = load_agent()
            with mock.patch.object(sys, "argv", [str(SCRIPT), "kube", "reconcile", "--dry-run"]):
                with mock.patch.object(module.os, "execv") as execute:
                    self.assertTrue(module.dispatch_stage3())
            execute.assert_called_once_with(str(binary), [str(binary), "kube", "reconcile", "--dry-run"])

    def test_heartbeat_mode_is_not_delegated(self):
        module = load_agent()
        with mock.patch.object(sys, "argv", [str(SCRIPT)]):
            self.assertFalse(module.dispatch_stage3())

    def test_plan_fetch_delegates_to_stage3_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "kiki-agent-stage3"
            binary.write_text("stage3\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"KIKI_STAGE3_AGENT": str(binary)}):
                module = load_agent()
            with mock.patch.object(sys, "argv", [str(SCRIPT), "plan", "fetch", "--sha256", "a" * 64]):
                with mock.patch.object(module.os, "execv") as execute:
                    self.assertTrue(module.dispatch_stage3())
            execute.assert_called_once_with(str(binary), [str(binary), "plan", "fetch", "--sha256", "a" * 64])


if __name__ == "__main__":
    unittest.main()
