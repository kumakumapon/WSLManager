"""``WSLManager`` の操作ログ・設定保存・テーマ/言語・自動更新の挙動を確認するテスト。

``WSLManager`` のインスタンスは作らず (Tk ルート不要)、メソッドを ``MagicMock`` の
``self`` に対して呼び出す。実際のウィンドウ・ログファイル・設定ファイルには触れない
(ログ読込のテストだけ、一時ディレクトリの実ファイルを使う)。
"""

from __future__ import annotations

import os
import tempfile
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

import wsl_core

try:
    import wslmgr
except ImportError as exc:  # tkinter が無い環境のみ
    wslmgr = None
    _IMPORT_ERROR = str(exc)
else:
    _IMPORT_ERROR = ""

# メソッドが ``messagebox`` / ``LogViewerDialog`` を参照するモジュール (パッチ先)
LOG_MODULE = "wslmgr_gui.app.operation_log"


def _make_manager() -> MagicMock:
    manager = MagicMock()
    manager._language = "en"
    manager._t.side_effect = lambda key, **values: wsl_core.translate(key, "en", **values)
    manager._operation_log = []
    manager._refresh_job = None
    return manager


@unittest.skipIf(wslmgr is None, f"wslmgr を import できません: {_IMPORT_ERROR}")
class OperationLogTests(unittest.TestCase):
    def test_log_operation_appends_formatted_entry_and_persists(self) -> None:
        manager = _make_manager()

        wslmgr.WSLManager._log_operation(manager, "停止", "Ubuntu", "実行")

        self.assertEqual(len(manager._operation_log), 1)
        self.assertRegex(
            manager._operation_log[0],
            r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] 停止 \| Ubuntu \| 実行$",
        )
        manager._persist_log_entry.assert_called_once_with("停止", "Ubuntu", "実行")

    def test_log_operation_keeps_only_latest_1000_entries(self) -> None:
        manager = _make_manager()
        manager._operation_log = [f"old-{i}" for i in range(1000)]

        wslmgr.WSLManager._log_operation(manager, "停止", "Ubuntu", "実行")

        self.assertEqual(len(manager._operation_log), 1000)
        self.assertEqual(manager._operation_log[0], "old-1")  # 最古の 1 件が落ちる
        self.assertIn("Ubuntu", manager._operation_log[-1])

    def test_persist_log_entry_submits_with_gui_source(self) -> None:
        manager = _make_manager()

        wslmgr.WSLManager._persist_log_entry(manager, "停止", "Ubuntu", "実行")

        manager._log_writer.submit.assert_called_once_with("停止", "Ubuntu", "実行", source="gui")

    def test_load_persisted_log_reads_saved_entries(self) -> None:
        manager = _make_manager()
        with tempfile.TemporaryDirectory() as tmp:
            manager._log_file = os.path.join(tmp, "operations.log")
            lines = [
                wsl_core.serialize_log_entry(
                    "停止", "Ubuntu", "実行", timestamp="2026-01-01 00:00:00", source="gui"
                ),
                "not json",  # 壊れた行は読み飛ばされる
                wsl_core.serialize_log_entry(
                    "起動", "Debian", "実行", timestamp="2026-01-02 00:00:00"
                ),
            ]
            with open(manager._log_file, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")

            wslmgr.WSLManager._load_persisted_log(manager)

        self.assertEqual(len(manager._operation_log), 2)
        self.assertIn("停止 | Ubuntu | 実行", manager._operation_log[0])
        self.assertIn("起動 | Debian | 実行", manager._operation_log[1])

    def test_load_persisted_log_keeps_only_latest_1000_entries(self) -> None:
        manager = _make_manager()
        with tempfile.TemporaryDirectory() as tmp:
            manager._log_file = os.path.join(tmp, "operations.log")
            with open(manager._log_file, "w", encoding="utf-8") as f:
                for i in range(1005):
                    f.write(
                        wsl_core.serialize_log_entry(
                            "op", f"t{i}", "ok", timestamp="2026-01-01 00:00:00"
                        )
                        + "\n"
                    )

            wslmgr.WSLManager._load_persisted_log(manager)

        self.assertEqual(len(manager._operation_log), 1000)
        self.assertIn("t1004", manager._operation_log[-1])
        self.assertIn("t5", manager._operation_log[0])

    def test_load_persisted_log_without_file_is_noop(self) -> None:
        manager = _make_manager()
        with tempfile.TemporaryDirectory() as tmp:
            manager._log_file = os.path.join(tmp, "missing.log")

            wslmgr.WSLManager._load_persisted_log(manager)

        self.assertEqual(manager._operation_log, [])

    def test_load_persisted_log_ignores_unreadable_path(self) -> None:
        manager = _make_manager()
        with tempfile.TemporaryDirectory() as tmp:
            manager._log_file = tmp  # ディレクトリは open() で OSError になる

            wslmgr.WSLManager._load_persisted_log(manager)

        self.assertEqual(manager._operation_log, [])


@unittest.skipIf(wslmgr is None, f"wslmgr を import できません: {_IMPORT_ERROR}")
class ShowLogViewerTests(unittest.TestCase):
    """ログビューアーの「消去」は、書き込み待ちを片付けてからファイルを消す。"""

    def _open(self, failed: list[str]) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
        manager = _make_manager()
        manager._operation_log = ["entry"]
        manager._log_dir = "C:/logs"
        calls: list[str] = []
        manager._log_writer.flush.side_effect = lambda *a, **k: calls.append("flush")

        def fake_delete(directory: str) -> tuple[list[str], list[str]]:
            calls.append("delete")
            return [], failed

        manager.calls = calls
        with (
            patch(f"{LOG_MODULE}.LogViewerDialog") as viewer,
            patch(f"{LOG_MODULE}.messagebox") as mb,
            patch.object(wsl_core, "delete_log_files", side_effect=fake_delete),
        ):
            wslmgr.WSLManager._show_log_viewer(manager)
            clear = viewer.call_args.args[2]
            clear()
        return manager, viewer, mb, clear

    def test_viewer_receives_the_live_log_list(self) -> None:
        manager, viewer, _, _ = self._open([])

        self.assertIs(viewer.call_args.args[0], manager)
        # ビューアーには「ライブのログ」そのものを渡す (消去時にその場でクリアされる)
        self.assertIs(viewer.call_args.args[1], manager._operation_log)
        self.assertEqual(manager._operation_log, [])

    def test_clear_flushes_before_deleting_files(self) -> None:
        manager, _, _, _ = self._open([])

        self.assertEqual(manager.calls, ["flush", "delete"])

    def test_clear_without_failures_shows_no_warning(self) -> None:
        _, _, mb, _ = self._open([])

        mb.showwarning.assert_not_called()

    def test_clear_with_failures_warns_with_file_names(self) -> None:
        _, viewer, mb, _ = self._open(["C:/logs/a.log"])

        mb.showwarning.assert_called_once()
        self.assertIn("C:/logs/a.log", mb.showwarning.call_args.args[1])
        # 警告の親は、表示中のログビューアー
        self.assertIs(mb.showwarning.call_args.kwargs["parent"], viewer.return_value)


@unittest.skipIf(wslmgr is None, f"wslmgr を import できません: {_IMPORT_ERROR}")
class SettingsTests(unittest.TestCase):
    def test_toggle_auto_refresh_on_schedules_and_saves(self) -> None:
        manager = _make_manager()
        manager._auto_refresh_var.get.return_value = True

        wslmgr.WSLManager._toggle_auto_refresh(manager)

        manager._schedule_auto_refresh.assert_called_once()
        manager.after_cancel.assert_not_called()
        manager._save_settings.assert_called_once()

    def test_toggle_auto_refresh_off_cancels_pending_job(self) -> None:
        manager = _make_manager()
        manager._auto_refresh_var.get.return_value = False
        manager._refresh_job = "job-1"

        wslmgr.WSLManager._toggle_auto_refresh(manager)

        manager.after_cancel.assert_called_once_with("job-1")
        self.assertIsNone(manager._refresh_job)
        manager._schedule_auto_refresh.assert_not_called()
        manager._save_settings.assert_called_once()

    def test_toggle_auto_refresh_off_without_job_does_not_cancel(self) -> None:
        manager = _make_manager()
        manager._auto_refresh_var.get.return_value = False

        wslmgr.WSLManager._toggle_auto_refresh(manager)

        manager.after_cancel.assert_not_called()
        manager._save_settings.assert_called_once()

    def test_schedule_auto_refresh_refreshes_and_reschedules(self) -> None:
        manager = _make_manager()
        manager.after.return_value = "job-2"

        wslmgr.WSLManager._schedule_auto_refresh(manager)

        manager._refresh.assert_called_once()
        manager.after.assert_called_once_with(5000, manager._schedule_auto_refresh)
        self.assertEqual(manager._refresh_job, "job-2")

    @patch("tkinter.ttk.Style")
    def test_change_theme_applies_saves_and_reports(self, style: MagicMock) -> None:
        manager = _make_manager()

        wslmgr.WSLManager._change_theme(manager, "clam")

        style.return_value.theme_use.assert_called_once_with("clam")
        self.assertEqual(manager._current_theme, "clam")
        manager._save_settings.assert_called_once()
        self.assertIn("clam", manager._set_status.call_args.args[0])

    @patch("tkinter.ttk.Style")
    def test_change_theme_failure_keeps_theme_and_does_not_save(self, style: MagicMock) -> None:
        manager = _make_manager()
        manager._current_theme = "vista"
        style.return_value.theme_use.side_effect = tk.TclError("no such theme")

        wslmgr.WSLManager._change_theme(manager, "nope")

        self.assertEqual(manager._current_theme, "vista")
        manager._save_settings.assert_not_called()
        self.assertIn("nope", manager._set_status.call_args.args[0])

    def test_change_language_normalizes_saves_and_reports(self) -> None:
        manager = _make_manager()
        manager._settings = {}

        wslmgr.WSLManager._change_language(manager, "en")

        self.assertEqual(manager._settings["language"], "en")
        manager._save_settings.assert_called_once()
        manager._set_status.assert_called_once_with(
            wsl_core.translate("gui.language_changed", "en")
        )

    def test_change_language_falls_back_to_auto_for_unknown_value(self) -> None:
        manager = _make_manager()
        manager._settings = {}

        wslmgr.WSLManager._change_language(manager, "xx")

        self.assertEqual(manager._settings["language"], wsl_core.LANGUAGE_AUTO)

    def test_save_settings_writes_current_ui_state(self) -> None:
        manager = _make_manager()
        manager._sorter.get_state.return_value = ("cpu", True)
        manager._current_theme = "clam"
        manager._auto_refresh_var.get.return_value = True
        manager.geometry.return_value = "900x600+10+20"
        manager._settings = {"snapshot_dir": "C:/snap", "language": "ja"}
        manager._settings_path = "C:/cfg/settings.json"

        with patch.object(wsl_core, "save_settings") as save:
            wslmgr.WSLManager._save_settings(manager)

        save.assert_called_once_with(
            "C:/cfg/settings.json",
            {
                "theme": "clam",
                "auto_refresh": True,
                "window_geometry": "900x600+10+20",
                "sort_column": "cpu",
                "sort_desc": True,
                "snapshot_dir": "C:/snap",
                "language": "ja",
            },
        )

    def test_save_settings_defaults_language_to_auto(self) -> None:
        manager = _make_manager()
        manager._sorter.get_state.return_value = (None, False)
        manager.geometry.return_value = "1x1+0+0"
        manager._settings = {}

        with patch.object(wsl_core, "save_settings") as save:
            wslmgr.WSLManager._save_settings(manager)

        saved = save.call_args.args[1]
        self.assertEqual(saved["language"], wsl_core.LANGUAGE_AUTO)
        self.assertIsNone(saved["snapshot_dir"])


if __name__ == "__main__":
    unittest.main()
