"""GUI の破壊的操作が確認プロンプトを経由することを検証するテスト。

``WSLManager`` / ``SnapshotManagerDialog`` のインスタンスは生成せず (Tk ルート不要)、
メソッドを ``MagicMock`` の ``self`` に対して呼び出す。``messagebox`` /
``simpledialog`` はモックに差し替え、確認を拒否した場合に WSL 操作が一切
実行されないこと、承認した場合にのみ実行されることを確認する。
"""

from __future__ import annotations

import inspect
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


# patch("...TransferProgressDialog") 中でも本物のシグネチャを使えるよう import 時に取得する
_TRANSFER_SIGNATURE = (
    inspect.signature(wslmgr.TransferProgressDialog.__init__) if wslmgr is not None else None
)


def _transfer_call(call: object) -> dict:
    """``TransferProgressDialog(...)`` の呼び出しを引数名で引く。

    位置引数の並び順に依存しないので、シグネチャの並べ替えで確認プロンプトとは
    無関係にテストが壊れることを避けられる。
    """
    return dict(_TRANSFER_SIGNATURE.bind(None, *call.args, **call.kwargs).arguments)


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
    def test_cancelling_name_entry_does_not_unregister(self, mb: MagicMock, sd: MagicMock) -> None:
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
        self.assertEqual(
            _transfer_call(dialog.call_args)["wsl_args"], ["--set-version", "Ubuntu", "1"]
        )


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


@unittest.skipIf(wslmgr is None, f"wslmgr を import できません: {_IMPORT_ERROR}")
class ExportConfirmationTests(unittest.TestCase):
    """エクスポートは出力先が既存ファイルの場合に上書き確認を経由する。"""

    @staticmethod
    def _run(
        askyesno: list[bool], save_path: str, exists: bool
    ) -> tuple[MagicMock, MagicMock, MagicMock]:
        app = _make_app()
        with (
            patch("wslmgr.messagebox") as mb,
            patch("wslmgr.filedialog") as fd,
            patch(
                "wslmgr.os"
            ) as fake_os,  # wslmgr 内の os だけを差し替える (os.path はグローバルに触れない)
            patch("wslmgr.TransferProgressDialog") as dialog,
            patch("wslmgr._get_distro_vhdx_path", return_value=None),
            patch("wslmgr.wsl_core.discard_partial_write") as discard,
        ):
            fake_os.path.exists.return_value = exists
            mb.askyesno.side_effect = askyesno
            fd.asksaveasfilename.return_value = save_path
            wslmgr.WSLManager._export_distro_image(app)
        return mb, dialog, discard

    def test_overwrite_declined_does_not_export(self) -> None:
        mb, dialog, discard = self._run([False, False], "C:/out/u.tar", exists=True)

        self.assertEqual(mb.askyesno.call_count, 2)  # 形式選択 + 上書き確認
        dialog.assert_not_called()
        discard.assert_not_called()

    def test_overwrite_confirmed_exports(self) -> None:
        mb, dialog, _ = self._run([False, True], "C:/out/u.tar", exists=True)

        self.assertEqual(mb.askyesno.call_count, 2)
        dialog.assert_called_once()
        args = _transfer_call(dialog.call_args)["wsl_args"]
        self.assertEqual(args[:2], ["--export", "Ubuntu"])
        self.assertNotIn("--vhd", args)

    def test_new_file_skips_overwrite_prompt(self) -> None:
        mb, dialog, _ = self._run([False], "C:/out/u.tar", exists=False)

        self.assertEqual(mb.askyesno.call_count, 1)  # 形式選択のみ
        dialog.assert_called_once()

    def test_vhd_format_adds_flag(self) -> None:
        _, dialog, _ = self._run([True], "C:/out/u.vhdx", exists=False)

        self.assertIn("--vhd", _transfer_call(dialog.call_args)["wsl_args"])

    def test_cancelled_save_dialog_does_not_export(self) -> None:
        mb, dialog, _ = self._run([False], "", exists=True)

        self.assertEqual(mb.askyesno.call_count, 1)
        dialog.assert_not_called()

    @patch("wslmgr.TransferProgressDialog")
    @patch("wslmgr.messagebox")
    def test_without_selection_neither_prompts_nor_exports(
        self, mb: MagicMock, dialog: MagicMock
    ) -> None:
        wslmgr.WSLManager._export_distro_image(_make_app(name=None))

        mb.showwarning.assert_called_once()
        mb.askyesno.assert_not_called()
        dialog.assert_not_called()


@unittest.skipIf(wslmgr is None, f"wslmgr を import できません: {_IMPORT_ERROR}")
class ImportConfirmationTests(unittest.TestCase):
    """インポートは内容確認を経由し、中断時は登録解除を別途確認する。"""

    @staticmethod
    def _run(askyesno: list[bool]) -> tuple[MagicMock, MagicMock, MagicMock]:
        app = _make_app()
        with (
            patch("wslmgr.messagebox") as mb,
            patch("wslmgr.simpledialog") as sd,
            patch("wslmgr.filedialog") as fd,
            patch("wslmgr.TransferProgressDialog") as dialog,
        ):
            sd.askstring.return_value = "NewDistro"
            fd.askopenfilename.return_value = "C:/img/u.tar"
            fd.askdirectory.return_value = "C:/wsl/new"
            mb.askyesno.side_effect = askyesno
            wslmgr.WSLManager._import_distro_image(app)
        return app, mb, dialog

    def test_declined_summary_does_not_import(self) -> None:
        _, mb, dialog = self._run([True, False])  # WSL2 を選び、内容確認で拒否

        self.assertEqual(mb.askyesno.call_count, 2)
        dialog.assert_not_called()

    def test_confirmed_summary_imports(self) -> None:
        app, _, dialog = self._run([True, True])

        dialog.assert_called_once()
        self.assertEqual(
            _transfer_call(dialog.call_args)["wsl_args"],
            ["--import", "NewDistro", "C:/wsl/new", "C:/img/u.tar", "--version", "2"],
        )
        app._log_operation.assert_called_once()

    def test_wsl1_choice_is_passed_through(self) -> None:
        _, _, dialog = self._run([False, True])

        self.assertEqual(_transfer_call(dialog.call_args)["wsl_args"][-2:], ["--version", "1"])

    @patch("wslmgr.filedialog")  # 検証漏れで先へ進んでも本物のダイアログを開かせない
    @patch("wslmgr.simpledialog")
    @patch("wslmgr.TransferProgressDialog")
    @patch("wslmgr.messagebox")
    def test_invalid_name_does_not_prompt_or_import(
        self, mb: MagicMock, dialog: MagicMock, sd: MagicMock, fd: MagicMock
    ) -> None:
        sd.askstring.return_value = "a/b"  # "/" は使用できない文字

        wslmgr.WSLManager._import_distro_image(_make_app())

        mb.showwarning.assert_called_once()
        fd.askopenfilename.assert_not_called()
        mb.askyesno.assert_not_called()
        dialog.assert_not_called()

    def _finish(self, returncode: int, cancelled: bool, answer: bool = False) -> tuple:
        app, _, dialog = self._run([True, True])
        on_done = _transfer_call(dialog.call_args)["on_done"]
        with patch("wslmgr.messagebox") as mb:
            mb.askyesno.return_value = answer
            on_done(returncode, "err", cancelled)
        return app, mb

    def _cancelled_callback(self, unregister_answer: bool) -> MagicMock:
        app, mb = self._finish(1, True, unregister_answer)  # ユーザーが中断
        self.assertEqual(mb.askyesno.call_count, 1)
        return app

    def test_successful_import_does_not_prompt_or_unregister(self) -> None:
        app, mb = self._finish(0, False)

        mb.askyesno.assert_not_called()
        app._run_wsl_cmd.assert_not_called()
        app._refresh.assert_called_once()

    def test_failed_import_does_not_prompt_or_unregister(self) -> None:
        app, mb = self._finish(1, False)

        mb.askyesno.assert_not_called()
        app._run_wsl_cmd.assert_not_called()
        app._refresh.assert_called_once()

    def test_cancelled_import_declining_cleanup_keeps_registration(self) -> None:
        app = self._cancelled_callback(False)

        app._run_wsl_cmd.assert_not_called()

    def test_cancelled_import_confirming_cleanup_unregisters(self) -> None:
        app = self._cancelled_callback(True)

        app._run_wsl_cmd.assert_called_once()
        self.assertEqual(app._run_wsl_cmd.call_args.args[0], ["--unregister", "NewDistro"])


@unittest.skipIf(wslmgr is None, f"wslmgr を import できません: {_IMPORT_ERROR}")
class SnapshotRestoreConfirmationTests(unittest.TestCase):
    MODULE = "wslmgr_gui.dialogs.snapshot"

    @staticmethod
    def _make_dialog() -> MagicMock:
        dialog = MagicMock()
        dialog._selected_snapshot.return_value = {
            "distro_name": "Ubuntu",
            "tar_path": "C:/snap/a.tar",
            "tar_exists": True,
            "wsl_version": "2",
        }
        dialog._parent._all_distros = [{"name": "Ubuntu"}]
        return dialog

    def _run(self, answer: bool) -> tuple[MagicMock, MagicMock, MagicMock]:
        dialog = self._make_dialog()
        with (
            patch(f"{self.MODULE}.messagebox") as mb,
            patch(f"{self.MODULE}.simpledialog") as sd,
            patch(f"{self.MODULE}.filedialog") as fd,
            patch(f"{self.MODULE}.TransferProgressDialog") as transfer,
        ):
            sd.askstring.return_value = "Restored"
            fd.askdirectory.return_value = "C:/wsl/restored"
            mb.askyesno.return_value = answer
            wslmgr.SnapshotManagerDialog._restore_snapshot(dialog)
            self.assertEqual(mb.askyesno.call_count, 1)
        return dialog, mb, transfer

    def test_declined_does_not_restore(self) -> None:
        dialog, _, transfer = self._run(False)

        transfer.assert_not_called()
        dialog._parent._log_operation.assert_not_called()

    def test_confirmed_restores(self) -> None:
        dialog, _, transfer = self._run(True)

        transfer.assert_called_once()
        self.assertEqual(
            _transfer_call(transfer.call_args)["wsl_args"],
            ["--import", "Restored", "C:/wsl/restored", "C:/snap/a.tar", "--version", "2"],
        )
        dialog._parent._log_operation.assert_called_once()

    def _finish(self, returncode: int, cancelled: bool, answer: bool = False) -> tuple:
        dialog, _, transfer = self._run(True)
        on_done = _transfer_call(transfer.call_args)["on_done"]
        with patch(f"{self.MODULE}.messagebox") as mb:
            mb.askyesno.return_value = answer
            on_done(returncode, "err", cancelled)
        return dialog._parent, mb

    def _cancelled_callback(self, unregister_answer: bool) -> MagicMock:
        parent, mb = self._finish(1, True, unregister_answer)
        self.assertEqual(mb.askyesno.call_count, 1)
        return parent

    def test_successful_restore_does_not_prompt_or_unregister(self) -> None:
        parent, mb = self._finish(0, False)

        mb.askyesno.assert_not_called()
        parent._run_wsl_cmd.assert_not_called()
        parent._refresh.assert_called_once()

    def test_failed_restore_does_not_prompt_or_unregister(self) -> None:
        parent, mb = self._finish(1, False)

        mb.askyesno.assert_not_called()
        parent._run_wsl_cmd.assert_not_called()
        parent._refresh.assert_called_once()

    def test_cancelled_restore_declining_cleanup_keeps_registration(self) -> None:
        parent = self._cancelled_callback(False)

        parent._run_wsl_cmd.assert_not_called()

    def test_cancelled_restore_confirming_cleanup_unregisters(self) -> None:
        parent = self._cancelled_callback(True)

        parent._run_wsl_cmd.assert_called_once()
        self.assertEqual(parent._run_wsl_cmd.call_args.args[0], ["--unregister", "Restored"])

    @patch("wslmgr_gui.dialogs.snapshot.TransferProgressDialog")
    @patch("wslmgr_gui.dialogs.snapshot.messagebox")
    def test_missing_tar_neither_prompts_nor_restores(
        self, mb: MagicMock, transfer: MagicMock
    ) -> None:
        dialog = self._make_dialog()
        dialog._selected_snapshot.return_value["tar_exists"] = False

        wslmgr.SnapshotManagerDialog._restore_snapshot(dialog)

        mb.showwarning.assert_called_once()
        mb.askyesno.assert_not_called()
        transfer.assert_not_called()


@unittest.skipIf(wslmgr is None, f"wslmgr を import できません: {_IMPORT_ERROR}")
class DiskOptimizeConfirmationTests(unittest.TestCase):
    """VHDX の圧縮・スパース化は確認後にのみバックグラウンド実行を開始する。

    ``threading`` をモックするため、実際の wsl.exe / diskpart は決して起動しない。
    """

    MODULE = "wslmgr_gui.dialogs.disk_optimize"

    @staticmethod
    def _make_dialog(busy: bool = False) -> MagicMock:
        dialog = MagicMock()
        dialog._busy = busy
        dialog._distro = "Ubuntu"
        dialog._vhdx = "C:/wsl/ext4.vhdx"
        return dialog

    def _call(self, method: str, answer: bool, busy: bool = False) -> tuple:
        dialog = self._make_dialog(busy)
        with (
            patch(f"{self.MODULE}.messagebox") as mb,
            patch(f"{self.MODULE}.threading") as threading_mock,
        ):
            mb.askyesno.return_value = answer
            getattr(wslmgr.DiskOptimizeDialog, method)(dialog)
        return dialog, mb, threading_mock

    def test_compact_declined_does_not_run(self) -> None:
        dialog, mb, threading_mock = self._call("_do_compact", False)

        mb.askyesno.assert_called_once()
        threading_mock.Thread.assert_not_called()
        dialog._set_busy.assert_not_called()
        dialog._run_cmd.assert_not_called()

    def test_compact_confirmed_starts_background_work(self) -> None:
        dialog, mb, threading_mock = self._call("_do_compact", True)

        mb.askyesno.assert_called_once()
        dialog._set_busy.assert_called_once_with(True)
        threading_mock.Thread.assert_called_once()
        threading_mock.Thread.return_value.start.assert_called_once()
        dialog._run_cmd.assert_not_called()  # 実行はスレッド側 (モック) のみ

    def test_compact_while_busy_does_not_prompt_or_run(self) -> None:
        _, mb, threading_mock = self._call("_do_compact", True, busy=True)

        mb.askyesno.assert_not_called()
        threading_mock.Thread.assert_not_called()

    def test_sparse_declined_does_not_run(self) -> None:
        dialog, mb, threading_mock = self._call("_do_sparse", False)

        mb.askyesno.assert_called_once()
        threading_mock.Thread.assert_not_called()
        dialog._set_busy.assert_not_called()

    def test_sparse_confirmed_starts_background_work(self) -> None:
        dialog, mb, threading_mock = self._call("_do_sparse", True)

        mb.askyesno.assert_called_once()
        dialog._set_busy.assert_called_once_with(True)
        threading_mock.Thread.return_value.start.assert_called_once()

    @patch("wslmgr_gui.dialogs.disk_optimize.messagebox")
    def test_close_while_busy_declined_keeps_dialog(self, mb: MagicMock) -> None:
        mb.askyesno.return_value = False
        dialog = self._make_dialog(busy=True)

        wslmgr.DiskOptimizeDialog._on_close(dialog)

        mb.askyesno.assert_called_once()
        dialog.destroy.assert_not_called()

    @patch("wslmgr_gui.dialogs.disk_optimize.messagebox")
    def test_close_while_busy_confirmed_closes_dialog(self, mb: MagicMock) -> None:
        mb.askyesno.return_value = True
        dialog = self._make_dialog(busy=True)

        wslmgr.DiskOptimizeDialog._on_close(dialog)

        mb.askyesno.assert_called_once()
        dialog.destroy.assert_called_once()

    @patch("wslmgr_gui.dialogs.disk_optimize.messagebox")
    def test_close_when_idle_closes_without_prompt(self, mb: MagicMock) -> None:
        dialog = self._make_dialog(busy=False)

        wslmgr.DiskOptimizeDialog._on_close(dialog)

        mb.askyesno.assert_not_called()
        dialog.destroy.assert_called_once()


@unittest.skipIf(wslmgr is None, f"wslmgr を import できません: {_IMPORT_ERROR}")
class WslUpdateConfirmationTests(unittest.TestCase):
    """WSL 更新は専用の確認ダイアログで承認された場合のみ実行する。"""

    @staticmethod
    def _run_update(result: dict | None) -> MagicMock:
        app = _make_app()
        app._all_distros = [{"name": "Ubuntu", "state": "Running"}]
        with patch("wslmgr.WslUpdateConfirmDialog") as confirm:
            confirm.return_value.result = result
            wslmgr.WSLManager._update_wsl(app)
        confirm.assert_called_once()
        return app

    def test_cancelled_confirmation_does_not_update(self) -> None:
        app = self._run_update(None)

        app._run_wsl_update_cmd.assert_not_called()

    def test_confirmed_updates(self) -> None:
        app = self._run_update({"pre_release": False})

        app._run_wsl_update_cmd.assert_called_once_with(False)

    def test_confirmed_pre_release_is_passed_through(self) -> None:
        app = self._run_update({"pre_release": True})

        app._run_wsl_update_cmd.assert_called_once_with(True)

    @patch("wslmgr.TransferProgressDialog")
    def test_update_command_arguments(self, dialog: MagicMock) -> None:
        wslmgr.WSLManager._run_wsl_update_cmd(_make_app(), False)
        wslmgr.WSLManager._run_wsl_update_cmd(_make_app(), True)

        first, second = (_transfer_call(c) for c in dialog.call_args_list)
        self.assertEqual(first["wsl_args"], ["--update"])
        self.assertEqual(second["wsl_args"], ["--update", "--pre-release"])
        # 更新中のキャンセルは確認文言つきで確認される
        self.assertTrue(first.get("cancel_prompt"))


@unittest.skipIf(wslmgr is None, f"wslmgr を import できません: {_IMPORT_ERROR}")
class TransferCancelAndCloseConfirmationTests(unittest.TestCase):
    @staticmethod
    def _make_transfer() -> MagicMock:
        transfer = MagicMock()
        transfer._finished = False
        transfer._cancelled = False
        transfer._cancel_prompt = "cancel?"
        return transfer

    @patch("wslmgr_gui.dialogs.transfer.messagebox")
    def test_cancel_declined_keeps_process_running(self, mb: MagicMock) -> None:
        mb.askyesno.return_value = False
        transfer = self._make_transfer()

        wslmgr.TransferProgressDialog._request_cancel(transfer)

        mb.askyesno.assert_called_once()
        transfer._proc.terminate.assert_not_called()
        self.assertFalse(transfer._cancelled)

    @patch("wslmgr_gui.dialogs.transfer.messagebox")
    def test_cancel_confirmed_terminates_process(self, mb: MagicMock) -> None:
        mb.askyesno.return_value = True
        transfer = self._make_transfer()

        wslmgr.TransferProgressDialog._request_cancel(transfer)

        transfer._proc.terminate.assert_called_once()
        self.assertTrue(transfer._cancelled)

    @patch("wslmgr_gui.dialogs.transfer.messagebox")
    def test_cancel_after_finish_does_not_prompt(self, mb: MagicMock) -> None:
        transfer = self._make_transfer()
        transfer._finished = True

        wslmgr.TransferProgressDialog._request_cancel(transfer)

        mb.askyesno.assert_not_called()
        transfer._proc.terminate.assert_not_called()

    @staticmethod
    def _make_app_with_live_transfer() -> tuple[MagicMock, MagicMock]:
        app = _make_app()
        live = MagicMock()
        live.winfo_exists.return_value = True
        app._transfer_dialogs = [live]
        app._refresh_job = None
        return app, live

    @patch("wslmgr.messagebox")
    def test_close_with_running_transfer_declined_keeps_app_open(self, mb: MagicMock) -> None:
        mb.askyesno.return_value = False
        app, live = self._make_app_with_live_transfer()

        wslmgr.WSLManager.on_closing(app)

        mb.askyesno.assert_called_once()
        live.force_cancel.assert_not_called()
        app.destroy.assert_not_called()

    @patch("wslmgr.messagebox")
    def test_close_with_running_transfer_confirmed_cancels_and_closes(self, mb: MagicMock) -> None:
        mb.askyesno.return_value = True
        app, live = self._make_app_with_live_transfer()

        wslmgr.WSLManager.on_closing(app)

        live.force_cancel.assert_called_once()
        app.destroy.assert_called_once()

    @patch("wslmgr.messagebox")
    def test_close_without_transfer_does_not_prompt(self, mb: MagicMock) -> None:
        app = _make_app()
        app._transfer_dialogs = []
        app._refresh_job = None

        wslmgr.WSLManager.on_closing(app)

        mb.askyesno.assert_not_called()
        app.destroy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
