"""WSLc 3.0.1 contracts derived from the official tagged commands/tasks.

Fixtures model CLI output (not Docker's HTTP list response). No real WSL runs.
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import queue
import threading
import unittest
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import wsl_core
import wslmgr_cli

SYSTEM = {
    "Client": {"Version": "3.0.1.0", "WindowsVersion": "10.0.26200", "SettingsFile": "test"},
    "Server": {
        "SessionManagerVersion": "3.0.1",
        "Sessions": [
            {"ID": 7, "CreatorPid": 123, "Name": "開発 session"},
        ],
    },
}
RECORD = {
    "ID": "a" * 64,
    "Names": "web",
    "Image": "nginx:latest",
    "State": "running",
    "Status": "Up 2 minutes (healthy)",
    "HealthStatus": "healthy",
    "CreatedAt": "2026-10-02 00:00:00 +0000 UTC",
    "Ports": "80/tcp",
    "Platform": {"architecture": "amd64", "os": "linux"},
}
NDJSON = (
    json.dumps(RECORD) + "\r\n" + json.dumps({**RECORD, "ID": "b" * 64, "Names": "db"}) + "\r\n"
)


def result(stdout: str = "", returncode: int = 0, stderr: str = "") -> wsl_core.WslResult:
    return wsl_core.WslResult(returncode=returncode, stdout=stdout, stderr=stderr, error=None)


class TestContracts(unittest.TestCase):
    def test_stable_versions_only(self):
        for version in ("3.0.1", "3.0.1.0", "3.1.0", "4.0.0", " 3.0.2 "):
            with self.subTest(version=version):
                capability = wsl_core.wslc_capability(version)
                self.assertTrue(capability["version_supported"])
                self.assertFalse(capability["available"])
        for version in (None, "", "2.6.9", "3.0.0", "3.0.1-preview", "foo3.0.1", "3.0.1.0.2"):
            with self.subTest(version=version):
                self.assertFalse(wsl_core.wslc_capability(version)["version_supported"])

    def test_ndjson_multiple_and_empty(self):
        rows = wsl_core.parse_wslc_json("\ufeff" + NDJSON, ndjson=True)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["Names"], "db")
        self.assertEqual(wsl_core.parse_wslc_json(" \r\n", ndjson=True), [])

    def test_invalid_json_is_not_empty_success(self):
        for output in ("garbage", '{"ID":"a"}\ninvalid', "[]\n{}", "null", "1", '"x"'):
            with self.subTest(output=output), self.assertRaises(wsl_core.WslcError):
                wsl_core.parse_wslc_json(output, ndjson=True)
        for output in ("", "null", "[{}, 1]", '{"broken":'):
            with self.subTest(output=output), self.assertRaises(wsl_core.WslcError):
                wsl_core.parse_wslc_json(output)

    def test_real_list_fields_and_inspect_health(self):
        summary = wsl_core.container_summary(RECORD)
        self.assertEqual(
            summary,
            {
                "id": "a" * 64,
                "name": "web",
                "image": "nginx:latest",
                "status": "Up 2 minutes (healthy)",
                "health": "healthy",
                "created": RECORD["CreatedAt"],
            },
        )
        summary = wsl_core.container_summary(
            {
                "Id": "abc",
                "Name": "/web",
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
            }
        )
        self.assertEqual(summary["health"], "healthy")
        self.assertEqual(summary["id"], "abc")

    def test_list_command_preserves_full_ids_and_explicit_session(self):
        runner = Mock(return_value=result(NDJSON))
        client = wsl_core.WslcClient(runner)
        self.assertEqual(len(client.list_containers("開発 session", all_containers=True)), 2)
        runner.assert_called_once_with(
            [
                "container",
                "list",
                "--session",
                "開発 session",
                "--format",
                "json",
                "--no-trunc",
                "--all",
            ]
        )

    def test_default_list_does_not_include_all(self):
        runner = Mock(return_value=result(""))
        self.assertEqual(wsl_core.WslcClient(runner).list_containers("dev"), [])
        self.assertNotIn("--all", runner.call_args.args[0])

    def test_missing_list_id_is_error(self):
        with self.assertRaises(wsl_core.WslcError):
            wsl_core.WslcClient(Mock(return_value=result("{}"))).list_containers("dev")

    def test_system_info_preserves_object(self):
        runner = Mock(return_value=result(json.dumps(SYSTEM)))
        self.assertEqual(wsl_core.WslcClient(runner).system_info(), SYSTEM)
        runner.assert_called_once_with(["system", "info", "--format", "json"])

    def test_system_info_rejects_malformed_contract(self):
        for payload in (
            {},
            [],
            [SYSTEM],
            {"Client": {}, "Server": {}},
            {**SYSTEM, "Server": {"Sessions": ["dev"]}},
            {**SYSTEM, "Client": {"Version": "2.0.0"}},
        ):
            with self.subTest(payload=payload), self.assertRaises(wsl_core.WslcError):
                wsl_core.WslcClient(Mock(return_value=result(json.dumps(payload)))).system_info()

    def test_inspect_array_and_exact_command(self):
        data = [{"Id": "a" * 64, "State": {"Health": {"Status": "healthy"}}}]
        runner = Mock(return_value=result(json.dumps(data, indent=2)))
        self.assertEqual(wsl_core.WslcClient(runner).inspect_container("dev", "a" * 64), data)
        runner.assert_called_once_with(["container", "inspect", "--session", "dev", "a" * 64])
        with self.assertRaises(wsl_core.WslcError):
            wsl_core.WslcClient(Mock(return_value=result("{}"))).inspect_container("dev", "web")

    def test_invalid_identifiers_never_execute(self):
        for value in ("", " ", "--help", "x\n", "x\0"):
            runner = Mock()
            client = wsl_core.WslcClient(runner)
            with self.subTest(value=value), self.assertRaises(wsl_core.WslcError):
                client.list_containers(value)
            with self.subTest(value=value), self.assertRaises(wsl_core.WslcError):
                client.inspect_container("dev", value)
            runner.assert_not_called()

    def test_command_failures_preserve_diagnostics(self):
        for failure in (
            result("[]", 1, "Disabled by policy"),
            result("", -1, "not found"),
            result("", -1, "timed out"),
            result("Service unavailable", 5),
        ):
            client = wsl_core.WslcClient(Mock(return_value=failure))
            with self.subTest(failure=failure), self.assertRaises(wsl_core.WslcError) as cm:
                client.inspect_container("dev", "web")
            self.assertIn(failure.stderr or failure.stdout, str(cm.exception))


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.wsl = patch(
            "wslmgr_cli._run_wsl_command", return_value=(0, "WSL version: 3.0.1.0\n", "")
        )
        self.wsl.start()
        self.addCleanup(self.wsl.stop)

    def test_parser_requires_session_and_accepts_all(self):
        parser = wslmgr_cli.build_parser("en")
        for args in (["container", "list"], ["container", "inspect", "web"]):
            with patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit) as cm:
                parser.parse_args(args)
            self.assertEqual(cm.exception.code, 2)
        args = parser.parse_args(["container", "list", "--session", "dev", "--all"])
        self.assertTrue(args.all)
        self.assertEqual(args.session, "dev")

    @patch("wslmgr_cli._run_wslc_command")
    def test_system_info_single_probe_and_object(self, runner):
        runner.return_value = (0, json.dumps(SYSTEM), "")
        with patch("sys.stdout", io.StringIO()) as stdout:
            wslmgr_cli.cmd_container_system_info(argparse.Namespace(format="json"))
        self.assertEqual(json.loads(stdout.getvalue()), SYSTEM)
        runner.assert_called_once_with(["system", "info", "--format", "json"])

    @patch("wslmgr_cli._run_wslc_command")
    def test_doctor_failed_probe_does_not_claim_available(self, runner):
        runner.return_value = (1, "", "Disabled by policy")
        with (
            patch("sys.stdout", io.StringIO()) as stdout,
            patch("sys.stderr", io.StringIO()) as stderr,
        ):
            with self.assertRaises(SystemExit) as cm:
                wslmgr_cli.cmd_doctor(argparse.Namespace(format="json"))
        self.assertEqual(cm.exception.code, 4)
        report = json.loads(stdout.getvalue())
        self.assertTrue(report["wslc"]["version_supported"])
        self.assertFalse(report["wslc"]["available"])
        self.assertIn("Disabled by policy", stderr.getvalue())

    @patch("wslmgr_cli._run_wslc_command")
    def test_unknown_wsl_does_not_probe(self, runner):
        with patch("wslmgr_cli._run_wsl_command", return_value=(0, "unknown", "")):
            self.assertFalse(wslmgr_cli._get_wslc_diagnostic()["wslc"]["available"])
        runner.assert_not_called()

    @patch("wslmgr_cli._run_wslc_command")
    def test_list_ndjson_json_and_csv(self, runner):
        for fmt in ("json", "csv", "table"):
            runner.side_effect = [(0, json.dumps(SYSTEM), ""), (0, NDJSON, "")]
            args = argparse.Namespace(format=fmt, session="dev", all=True)
            with self.subTest(fmt=fmt), patch("sys.stdout", io.StringIO()) as stdout:
                wslmgr_cli.cmd_container_list(args)
            if fmt == "json":
                self.assertEqual(len(json.loads(stdout.getvalue())), 2)
            self.assertIn("web", stdout.getvalue())
            self.assertIn("healthy", stdout.getvalue())

    @patch("wslmgr_cli._run_wslc_command")
    def test_malformed_list_emits_no_success_json(self, runner):
        runner.side_effect = [(0, json.dumps(SYSTEM), ""), (0, "garbage", "")]
        with patch("sys.stdout", io.StringIO()) as stdout, patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                wslmgr_cli.cmd_container_list(argparse.Namespace(session="dev", format="json"))
        self.assertEqual(cm.exception.code, 4)
        self.assertEqual(stdout.getvalue(), "")


class TestDialogLogic(unittest.TestCase):
    """Execute the actual class with a fake Tk base; CI needs no window/display."""

    def setUp(self):
        source = (
            Path(__file__).resolve().parents[1].joinpath("wslmgr.py").read_text(encoding="utf-8")
        )
        node = next(
            n
            for n in ast.parse(source).body
            if isinstance(n, ast.ClassDef) and n.name == "ContainerManagerDialog"
        )
        module = ast.Module(
            body=[
                ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
                node,
            ],
            type_ignores=[],
        )
        namespace = {
            "tk": SimpleNamespace(
                Toplevel=type("FakeTop", (), {"destroy": lambda _: None}), END="end"
            ),
            "queue": queue,
            "threading": threading,
            "wsl_core": wsl_core,
            "Callable": Callable,
        }
        exec(compile(ast.fix_missing_locations(module), "wslmgr.py", "exec"), namespace)
        cls = namespace["ContainerManagerDialog"]
        self.dialog = cls.__new__(cls)
        d = self.dialog
        d._closed, d._busy, d._poll_id, d._row_session = False, False, None, ""
        d._results = queue.SimpleQueue()
        for attr in (
            "_refresh_button",
            "_inspect_button",
            "_all_button",
            "_sessions",
            "_status",
            "_session",
            "_all",
            "_tree",
            "after",
            "after_cancel",
        ):
            setattr(d, attr, Mock())
        d._tree.get_children.return_value = []
        d._session.get.return_value = ""
        d._all.get.return_value = False
        d._t = lambda key, **kwargs: key

    @patch("wsl_core.WslcClient")
    def test_no_session_never_lists(self, client):
        client.return_value.system_info.return_value = {"Server": {"Sessions": []}}
        self.dialog._start_task = lambda work, done: done(work())
        self.dialog._reload()
        client.return_value.list_containers.assert_not_called()
        self.dialog._status.set.assert_called_with("containers.none")

    @patch("wsl_core.WslcClient")
    def test_sole_session_is_explicit_and_multiple_need_selection(self, client):
        d = self.dialog
        d._start_task = lambda work, done: done(work())
        client.return_value.system_info.return_value = SYSTEM
        client.return_value.list_containers.return_value = [RECORD]
        d._reload()
        client.return_value.list_containers.assert_called_once_with(
            "開発 session", all_containers=False
        )
        self.assertEqual(d._row_session, "開発 session")
        client.reset_mock()
        client.return_value.system_info.return_value = {
            "Server": {"Sessions": [{"Name": "a"}, {"Name": "b"}]}
        }
        d._reload()
        client.return_value.list_containers.assert_not_called()
        self.assertEqual(d._row_session, "")

    @patch("wsl_core.WslcClient")
    def test_inspect_uses_full_id_and_rows_session(self, client):
        d = self.dialog
        d._row_session = "original"
        d._session.get.return_value = "different"
        d._tree.selection.return_value = ["item"]
        d._tree.item.return_value = ("a" * 64, "web")
        d._start_task = lambda work, done: work()
        d._show_inspect()
        client.return_value.inspect_container.assert_called_once_with("original", "a" * 64)

    @patch("threading.Thread")
    def test_worker_only_enqueues_and_busy_prevents_duplicate(self, thread):
        d = self.dialog
        done = Mock()
        d._start_task(lambda: [RECORD], done)
        d._start_task(lambda: [], done)
        thread.assert_called_once()
        d.after.assert_called_once()
        thread.call_args.kwargs["target"]()
        d.after.assert_called_once()  # no Tk calls from the worker
        done.assert_not_called()
        d._poll_result()
        done.assert_called_once_with([RECORD])
        self.assertFalse(d._busy)

    def test_close_cancels_poll_and_ignores_late_result(self):
        d = self.dialog
        d._poll_id = "timer"
        done = Mock()
        d.destroy()
        d._results.put((done, [], None))
        d._poll_result()
        d.after_cancel.assert_called_once_with("timer")
        d.after.assert_not_called()
        done.assert_not_called()

    def test_error_restores_controls_without_success_callback(self):
        d = self.dialog
        done = Mock()
        d._results.put((done, None, "policy denied"))
        d._poll_result()
        done.assert_not_called()
        d._sessions.configure.assert_called_with(state="readonly")
        d._status.set.assert_called_with("containers.error")


if __name__ == "__main__":
    unittest.main()
