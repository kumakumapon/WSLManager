"""GUI の破壊的操作が確認プロンプトを経由することを検証するテスト。

``WSLManager`` / ``SnapshotManagerDialog`` のインスタンスは生成せず (Tk ルート不要)、
メソッドを ``MagicMock`` の ``self`` に対して呼び出す。``messagebox`` /
``simpledialog`` はモックに差し替え、確認を拒否した場合に WSL 操作が一切
実行されないこと、承認した場合にのみ実行されることを確認する。
"""

from __future__ import annotations

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


def _make_app(name: str | None = "Ubuntu") -> MagicMock:
    """確認プロンプト周りだけを検証する ``WSLManager`` の代役を作る。"""
    app = MagicMock()
    app._language = "en"
    app._t.side_effect = lambda key, **values: wsl_core.translate(key, "en", **values)
    app._selected_name.return_value = name
    return app


@unittest.skipIf(wslmgr is None, f"wslmgr を import できません: {_IMPORT_ERROR}")
class StopAndShutdownConfirmationTests(unittest.TestCase):
    @patch("wslmgr.messagebox")
    def test_stop_declined_does_not_run_wsl(self, mb: MagicMock) -> None:
        mb.askyesno.return_value = False
        app = _make_app()

        wslmgr.WSLManager._stop_distro(app)

        mb.askyesno.assert_called_once()
        app._run_wsl_cmd.assert_not_called()
        app._log_operation.assert_not_called()

    @patch("wslmgr.messagebox")
    def test_stop_confirmed_runs_terminate(self, mb: MagicMock) -> None:
        mb.askyesno.return_value = True
        app = _make_app()

        wslmgr.WSLManager._stop_distro(app)

        app._run_wsl_cmd.assert_called_once()
        self.assertEqual(app._run_wsl_cmd.call_args.args[0], ["--terminate", "Ubuntu"])

    @patch("wslmgr.messagebox")
    def test_stop_without_selection_neither_prompts_nor_runs(self, mb: MagicMock) -> None:
        app = _make_app(name=None)

        wslmgr.WSLManager._stop_distro(app)

        mb.showwarning.assert_called_once()
        mb.askyesno.assert_not_called()
        app._run_wsl_cmd.assert_not_called()

    @patch("wslmgr.messagebox")
    def test_shutdown_declined_does_not_run_wsl(self, mb: MagicMock) -> None:
        mb.askyesno.return_value = False
        app = _make_app()

        wslmgr.WSLManager._shutdown_all(app)

        mb.askyesno.assert_called_once()
        app._run_wsl_cmd.assert_not_called()

    @patch("wslmgr.messagebox")
    def test_shutdown_confirmed_runs_shutdown(self, mb: MagicMock) -> None:
        mb.askyesno.return_value = True
        app = _make_app()

        wslmgr.WSLManager._shutdown_all(app)

        self.assertEqual(app._run_wsl_cmd.call_args.args[0], ["--shutdown"])


@unittest.skipIf(wslmgr is None, f"wslmgr を import できません: {_IMPORT_ERROR}")
class UninstallConfirmationTests(unittest.TestCase):
    """アンインストールは「はい/いいえ」とディストロ名の再入力の二段階確認。"""

    @patch("wslmgr.simpledialog")
    @patch("wslmgr.messagebox")
    def test_declining_first_prompt_skips_name_entry_and_unregister(
        self, mb: MagicMock, sd: MagicMock
    ) -> None:
        mb.askyesno.return_value = False
        app = _make_app()

        wslmgr.WSLManager._uninstall_distro(app)

        sd.askstring.assert_not_called()
        app._run_wsl_cmd.assert_not_called()

    @patch("wslmgr.simpledialog")
    @patch("wslmgr.messagebox")
    def test_cancelling_name_entry_does_not_unregister(
        self, mb: MagicMock, sd: MagicMock
    ) -> None:
        mb.askyesno.return_value = True
        sd.askstring.return_value = None
        app = _make_app()

        wslmgr.WSLManager._uninstall_distro(app)

        app._run_wsl_cmd.assert_not_called()

    @patch("wslmgr.simpledialog")
    @patch("wslmgr.messagebox")
    def test_mismatched_name_does_not_unregister(self, mb: MagicMock, sd: MagicMock) -> None:
        mb.askyesno.return_value = True
        sd.askstring.return_value = "ubuntu-other"
        app = _make_app()

        wslmgr.WSLManager._uninstall_distro(app)

        mb.showwarning.assert_called_once()
        app._run_wsl_cmd.assert_not_called()
        app._log_operation.assert_not_called()

    @patch("wslmgr.simpledialog")
    @patch("wslmgr.messagebox")
    def test_matching_name_runs_unregister(self, mb: MagicMock, sd: MagicMock) -> None:
        mb.askyesno.return_value = True
        sd.askstring.return_value = "  Ubuntu "
        app = _make_app()

        wslmgr.WSLManager._uninstall_distro(app)

        app._run_wsl_cmd.assert_called_once()
        self.assertEqual(app._run_wsl_cmd.call_args.args[0], ["--unregister", "Ubuntu"])

    @patch("wslmgr.simpledialog")
    @patch("wslmgr.messagebox")
    def test_without_selection_neither_prompts_nor_unregisters(
        self, mb: MagicMock, sd: MagicMock
    ) -> None:
        app = _make_app(name=None)

        wslmgr.WSLManager._uninstall_distro(app)

        mb.askyesno.assert_not_called()
        sd.askstring.assert_not_called()
        app._run_wsl_cmd.assert_not_called()


@unittest.skipIf(wslmgr is None, f"wslmgr を import できません: {_IMPORT_ERROR}")
class ConvertVersionConfirmationTests(unittest.TestCase):
    @patch("wslmgr.TransferProgressDialog")
    @patch("wslmgr.messagebox")
    def test_declined_does_not_start_conversion(self, mb: MagicMock, dialog: MagicMock) -> None:
        mb.askyesno.return_value = False
        app = _make_app()
        app._tree.selection.return_value = ["row"]
        app._tree.item.return_value = {"values": ["Ubuntu", "Running", "", "WSL2"]}

        wslmgr.WSLManager._convert_version(app)

        mb.askyesno.assert_called_once()
        dialog.assert_not_called()
        app._log_operation.assert_not_called()

    @patch("wslmgr.TransferProgressDialog")
    @patch("wslmgr.messagebox")
    def test_confirmed_starts_conversion(self, mb: MagicMock, dialog: MagicMock) -> None:
        mb.askyesno.return_value = True
        app = _make_app()
        app._tree.selection.return_value = ["row"]
        app._tree.item.return_value = {"values": ["Ubuntu", "Running", "", "WSL2"]}

        wslmgr.WSLManager._convert_version(app)

        dialog.assert_called_once()
        self.assertEqual(dialog.call_args.args[3], ["--set-version", "Ubuntu", "1"])


@unittest.skipIf(wslmgr is None, f"wslmgr を import できません: {_IMPORT_ERROR}")
class SnapshotDeleteConfirmationTests(unittest.TestCase):
    @staticmethod
    def _make_dialog() -> MagicMock:
        dialog = MagicMock()
        dialog._selected_snapshot.return_value = {
            "distro_name": "Ubuntu",
            "created_at": "2026-01-01T00:00:00",
            "tar_file": "a.tar",
            "tar_path": "C:/snap/a.tar",
            "json_path": "C:/snap/a.json",
            "tar_exists": True,
        }
        return dialog

    @patch("wslmgr_gui.dialogs.snapshot.os.remove")
    @patch("wslmgr_gui.dialogs.snapshot.messagebox")
    def test_declined_keeps_files(self, mb: MagicMock, remove: MagicMock) -> None:
        mb.askyesno.return_value = False
        dialog = self._make_dialog()

        wslmgr.SnapshotManagerDialog._delete_snapshot(dialog)

        # 確認ダイアログが実際にモックへ到達していること (パッチ先の誤りで素通りしないための確認)
        mb.askyesno.assert_called_once()
        remove.assert_not_called()
        dialog._parent._log_operation.assert_not_called()

    @patch("wslmgr_gui.dialogs.snapshot.os.remove")
    @patch("wslmgr_gui.dialogs.snapshot.messagebox")
    def test_confirmed_removes_tar_and_json(self, mb: MagicMock, remove: MagicMock) -> None:
        mb.askyesno.return_value = True
        dialog = self._make_dialog()

        wslmgr.SnapshotManagerDialog._delete_snapshot(dialog)

        self.assertEqual(
            [c.args[0] for c in remove.call_args_list], ["C:/snap/a.tar", "C:/snap/a.json"]
        )

    @patch("wslmgr_gui.dialogs.snapshot.os.remove")
    @patch("wslmgr_gui.dialogs.snapshot.messagebox")
    def test_without_selection_does_not_prompt_or_remove(
        self, mb: MagicMock, remove: MagicMock
    ) -> None:
        dialog = MagicMock()
        dialog._selected_snapshot.return_value = None

        wslmgr.SnapshotManagerDialog._delete_snapshot(dialog)

        mb.showwarning.assert_called_once()
        mb.askyesno.assert_not_called()
        remove.assert_not_called()


if __name__ == "__main__":
    unittest.main()
