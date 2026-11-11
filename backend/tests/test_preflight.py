"""Probe actual importability and bounded loopback health without inference."""
import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from email.message import Message
from pathlib import Path
from urllib.response import addinfourl
from unittest.mock import patch

from evaluation import live


@contextmanager
def health_transport(*, redirect=None, body=b'{"status": "ok"}'):
    """Exercise real urllib processing while replacing the socket transport."""
    requests = []

    class Transport(live.urllib.request.HTTPHandler):
        def http_open(self, request):
            requests.append(request.full_url)
            headers = Message()
            if redirect:
                headers["Location"] = redirect
            response = addinfourl(io.BytesIO(body), headers, request.full_url, 302 if redirect else 200)
            response.msg = "Found" if redirect else "OK"
            return response

    build = live.urllib.request.build_opener
    with patch.object(live.urllib.request, "build_opener", side_effect=lambda *handlers: build(*handlers, Transport())) as opener:
        yield requests, opener


class RuntimeImportTest(unittest.TestCase):
    def test_discoverable_but_broken_native_module_is_not_ready_and_error_is_redacted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "_citepath_broken_native.py").write_text(
                "raise ImportError('private DLL error with private-api-key')\n", encoding="utf-8")
            with patch.dict(os.environ, {"PYTHONPATH": temp + os.pathsep + os.environ.get("PYTHONPATH", "")}), \
                    patch.object(live, "RUNTIME_MODULES", {"native_test": "_citepath_broken_native"}):
                ready, status = live.runtime_imports(timeout=5)
        self.assertEqual(status, "completed")
        self.assertEqual(ready, {"native_test": False})
        self.assertNotIn("private", json.dumps([ready, status]))

    def test_timeout_keeps_unobserved_modules_unready_without_exporting_stderr(self):
        timeout = subprocess.TimeoutExpired("hidden command", 30,
                                            output=b'["pymysql", true]\n', stderr=b'private-api-key')
        with patch.object(live.subprocess, "run", side_effect=timeout) as run:
            ready, status = live.runtime_imports()
        self.assertEqual(status, "timeout")
        self.assertTrue(ready["pymysql"])
        self.assertFalse(ready["pymilvus"])
        self.assertNotIn("private", json.dumps([ready, status]))
        self.assertEqual(run.call_args.kwargs["timeout"], 30)

    def test_process_crash_or_unavailable_executable_cannot_report_ready(self):
        output = "\n".join(json.dumps([name, True]) for name in live.RUNTIME_MODULES)
        completed = subprocess.CompletedProcess([], 1, stdout=output, stderr="private DLL error")
        for effect in (completed, OSError("private executable path")):
            with self.subTest(effect=type(effect).__name__):
                kwargs = {"side_effect": effect} if isinstance(effect, OSError) else {"return_value": effect}
                with patch.object(live.subprocess, "run", **kwargs):
                    ready, status = live.runtime_imports()
                self.assertFalse(any(ready.values()))
                self.assertNotIn("private", json.dumps([ready, status]))


class HealthProbeTest(unittest.TestCase):
    def test_arbitrary_remote_origins_are_rejected_before_opening_any_connection(self):
        for origin in ("https://provider.invalid", "http://127.0.0.1@provider.invalid",
                       "http://127.0.0.1:8000/path", "http://127.0.0.1/?token=secret",
                       "http://user:password@localhost:8000", "http://127.0.0.1:99999"):
            with self.subTest(origin=origin), patch.object(live.urllib.request, "build_opener") as opener:
                self.assertFalse(live.api_health(origin))
                opener.assert_not_called()

    def test_local_json_health_ignores_environment_proxy_and_rejects_html(self):
        with patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1", "http_proxy": "http://127.0.0.1:1"}):
            with health_transport() as (requests, opener):
                self.assertTrue(live.api_health("http://127.0.0.1:8765"))
                self.assertEqual(requests, ["http://127.0.0.1:8765/api/health"])
                self.assertEqual(opener.call_args.args[0].proxies, {})
            with health_transport(body=b"<html>another service</html>"):
                self.assertFalse(live.api_health("http://127.0.0.1:8765"))

    def test_redirect_never_opens_the_external_destination(self):
        with health_transport(redirect="https://provider.invalid/private-destination") as (requests, _), \
                patch.object(live.urllib.request.HTTPSHandler, "https_open") as external:
            self.assertFalse(live.api_health("http://127.0.0.1:8765"))
            self.assertEqual(requests, ["http://127.0.0.1:8765/api/health"])
            external.assert_not_called()

    def test_preflight_reports_runner_scope_and_blocks_broken_import_without_a_model_call(self):
        imported = {name: name != "pymilvus" for name in live.RUNTIME_MODULES}
        with patch.dict(os.environ, {"LLM_PROVIDER": "hku", "HKU_API_KEY": "unit-test-key"}), \
                patch.object(live, "runtime_imports", return_value=(imported, "completed")), \
                patch.object(live, "api_health", return_value=True), \
                patch.object(live.socket, "create_connection"), \
                patch("agent.llm.chat_model") as model:
            report = live.preflight_report()
        runtime = next(row for row in report["checks"] if row["name"] == "full_runtime_dependencies")
        self.assertFalse(runtime["ready"])
        self.assertIn("pymilvus", runtime["detail"])
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["model_configuration_scope"], "runner_local")
        self.assertFalse(report["server_model_configuration_verified"])
        self.assertFalse(report["model_invoked"])
        model.assert_not_called()


if __name__ == "__main__":
    unittest.main()
