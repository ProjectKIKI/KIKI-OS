import contextlib
import io
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import ki2ci


class BuildExecutionTests(unittest.TestCase):
    def config(self, root):
        return ki2ci.CiConfig(Path(root), Path(root) / "ci", "x86_64", 2, "test", Path(root) / "publish")

    def test_spawn_error_records_failed_step_and_skips_remaining_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self.config(tmp)
            store = ki2ci.JobStore(config.artifact_root)
            job = store.create("smoke")
            steps = [ki2ci.Step("missing tool", [str(Path(tmp) / "does-not-exist")]),
                     ki2ci.Step("must not run", [sys.executable, "-c", "raise Exception('unexpected')"])]
            with mock.patch.object(ki2ci, "pipeline_steps", return_value=steps):
                ki2ci.run_job(config, store, job["id"])
            result = store.read(job["id"])
            self.assertEqual(result["status"], "failed")
            self.assertEqual([step["status"] for step in result["steps"]], ["failed", "skipped"])
            self.assertIsNotNone(result["finished_at"])
            self.assertIn("[error]", store.log_path(job["id"]).read_text(encoding="utf-8"))

    def test_keyboard_interrupt_is_persisted_and_propagated(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self.config(tmp)
            store = ki2ci.JobStore(config.artifact_root)
            job = store.create("smoke")
            with mock.patch.object(ki2ci, "pipeline_steps", return_value=[ki2ci.Step("compile", ["fixture"])]), \
                 mock.patch.object(ki2ci, "run_step", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    ki2ci.run_job(config, store, job["id"])
            result = store.read(job["id"])
            self.assertEqual(result["status"], "interrupted")
            self.assertEqual(result["exit_code"], 130)
            self.assertEqual(result["steps"][0]["status"], "interrupted")

    def test_concurrent_status_reads_do_not_break_atomic_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ki2ci.JobStore(Path(tmp))
            job = store.create("smoke")
            errors = []
            def reader():
                try:
                    for _ in range(100):
                        self.assertEqual(store.read(job["id"])["id"], job["id"])
                        self.assertEqual(len(store.list()), 1)
                except Exception as exc:
                    errors.append(exc)
            thread = threading.Thread(target=reader)
            thread.start()
            for count in range(100):
                job["counter"] = count
                store.write(job)
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])

    def test_fifo_cancel_and_retry_preserve_original_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = ki2ci.BuildServer(self.config(tmp))
            started, release = threading.Event(), threading.Event()
            executed = []

            def fake_step(config, step, log):
                executed.append(step.name)
                if len(executed) == 1:
                    started.set()
                    if not release.wait(5):
                        raise RuntimeError("test worker timed out")
                return 0

            try:
                with mock.patch.object(ki2ci, "pipeline_steps", side_effect=lambda config, name: [ki2ci.Step(name, ["fixture"])]), \
                     mock.patch.object(ki2ci, "run_step", side_effect=fake_step):
                    first = server.submit("smoke")
                    self.assertTrue(started.wait(3))
                    cancelled = server.submit("bootstrap")
                    third = server.submit("security")
                    self.assertEqual(server.job(cancelled["id"])["queue_position"], 1)
                    with self.assertRaises(ki2ci.CiError):
                        server.cancel(first["id"])
                    server.cancel(cancelled["id"])
                    with self.assertRaises(ki2ci.CiError):
                        server.retry(third["id"])
                    release.set()
                    server.queue.join()
                    retry = server.retry(cancelled["id"])
                    server.queue.join()
                    self.assertEqual(executed, ["smoke", "security", "bootstrap"])
                    self.assertEqual(server.store.read(cancelled["id"])["status"], "cancelled")
                    self.assertEqual(server.store.read(retry["id"])["retry_of"], cancelled["id"])
                    self.assertEqual(server.store.read(third["id"])["status"], "succeeded")
            finally:
                release.set()
                server.close()
                server.worker.join(timeout=5)

    def test_restart_recovers_pending_and_marks_running_interrupted(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self.config(tmp)
            store = ki2ci.JobStore(config.artifact_root)
            running = store.create("smoke")
            running.update(status="running", steps=[{"name": "compile", "status": "running"}])
            store.write(running)
            pending = store.create("security")
            with mock.patch.object(ki2ci, "pipeline_steps", return_value=[]):
                server = ki2ci.BuildServer(config)
                try:
                    server.queue.join()
                    self.assertEqual(store.read(running["id"])["status"], "interrupted")
                    self.assertEqual(store.read(running["id"])["steps"][0]["status"], "interrupted")
                    self.assertEqual(store.read(pending["id"])["status"], "succeeded")
                finally:
                    server.close()
                    server.worker.join(timeout=3)

    def test_builder_lease_prevents_second_owner_and_releases_on_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            lease = ki2ci.BuilderLease(Path(tmp))
            try:
                with self.assertRaises(ki2ci.CiError):
                    ki2ci.BuilderLease(Path(tmp))
            finally:
                lease.close()
            second = ki2ci.BuilderLease(Path(tmp))
            second.close()

    def test_log_cursor_is_bounded_and_preserves_split_utf8(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "log"
            path.write_bytes("a한글z".encode())
            first = ki2ci.log_chunk(path, 0, limit=3)
            second = ki2ci.log_chunk(path, first["offset"], limit=4)
            third = ki2ci.log_chunk(path, second["offset"], limit=4)
            self.assertEqual(first["text"] + second["text"] + third["text"], "a한글z")
            self.assertEqual(third["offset"], path.stat().st_size)
            with self.assertRaises(ki2ci.CiError):
                ki2ci.log_chunk(path, -1)
            path.write_bytes(b"a" * 100000)
            tail = ki2ci.log_chunk(path)
            self.assertEqual(len(tail["text"]), 65536)
            self.assertTrue(tail["truncated"])

    def test_web_plan_log_cancel_and_origin_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = ki2ci.BuildServer(self.config(tmp))
            job = server.store.create("smoke")
            ki2ci.append_log(server.store.log_path(job["id"]), "한글 <script>\n")
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), ki2ci.make_handler(server))
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            url = f"http://127.0.0.1:{httpd.server_port}"
            try:
                with urllib.request.urlopen(url + "/api/plan?pipeline=security") as response:
                    self.assertTrue(json.load(response)[0]["command"])
                with urllib.request.urlopen(url + f"/api/jobs/{job['id']}/log?offset=0") as response:
                    self.assertIn("한글", json.load(response)["text"])
                with urllib.request.urlopen(url + f"/jobs/{job['id']}") as response:
                    self.assertIn(b"&lt;script&gt;", response.read())
                request = urllib.request.Request(url + f"/jobs/{job['id']}/cancel", b"action=cancel",
                    headers={"Content-Type": "application/x-www-form-urlencoded", "Origin": "http://untrusted.invalid"})
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(request)
                self.assertEqual(error.exception.code, 403)
                error.exception.close()
                request.remove_header("Origin")
                with urllib.request.urlopen(request) as response:
                    self.assertIn(b"cancelled", response.read())
                self.assertEqual(server.store.read(job["id"])["status"], "cancelled")
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=3)
                server.close()

    def test_json_cli_output_is_parseable_without_appended_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self.config(tmp)
            store = ki2ci.JobStore(config.artifact_root)
            job = store.create("smoke")
            ki2ci.append_log(store.log_path(job["id"]), "plain log text")
            args = ki2ci.build_parser().parse_args(["show-job", job["id"], "--artifact-root", str(config.artifact_root), "--json"])
            with contextlib.redirect_stdout(io.StringIO()) as output:
                ki2ci.command_show(args)
            self.assertEqual(json.loads(output.getvalue())["id"], job["id"])


if __name__ == "__main__":
    unittest.main()
