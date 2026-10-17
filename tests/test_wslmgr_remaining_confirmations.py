"""GUI の確認プロンプトのうち、これまでテストで守られていなかったものを確認するテスト。

対象: 複製 (``_clone_distro``)、スナップショット作成 (``_create_snapshot``)、
ディストロのインストール (``_open_install_dialog``)、``wsl.conf`` 保存後の再起動確認
(``DistroConfDialog._on_saved``)、プロセスの強制終了 (``ProcessWindow._kill_process``)。

ウィンドウは作らず、メソッドを ``MagicMock`` の ``self`` に対して呼び出す。実際の
``wsl.exe`` / スレッド / 本物のダイアログは起動しない (すべてモック)。ファイルを扱う
テストは、一時ディレクトリの中だけで行う。
"""

from __future__ import annotations

import os
import tempfile
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
    app = MagicMock()
    app._language = "en"
    app._t.side_effect = lambda key, **values: wsl_core.translate(key, "en", **values)
    app._selected_name.return_value = name
    app._all_distros = [{"name": "Ubuntu", "version": 2}, {"name": "Debian", "version": 1}]
    return app


@unittest.skipIf(wslmgr is None, f"wslmgr を import できません: {_IMPORT_ERROR}")
class CloneConfirmationTests(unittest.TestCase):
    """複製は、名前の検証・複製先の選択・内容確認を経てから始まる。"""

    @staticmethod
    def _run(
        *,
        new_name: str | None = "Ubuntu-clone",
        folder: str = "C:/wsl/clone",
        confirm: bool = True,
        name: str | None = "Ubuntu",
    ) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
        app = _make_app(name)
        with (
            patch("wslmgr.messagebox") as mb,
            patch("wslmgr.simpledialog") as sd,
            patch("wslmgr.filedialog") as fd,
        ):
            sd.askstring.return_value = new_name
            fd.askdirectory.return_value = folder
            mb.askyesno.return_value = confirm
            wslmgr.WSLManager._clone_distro(app)
        return app, mb, sd, fd

    def test_declined_confirmation_does_not_clone(self) -> None:
        app, mb, _, _ = self._run(confirm=False)

        mb.askyesno.assert_called_once()
        app._run_clone_cmd.assert_not_called()
        app._log_operation.assert_not_called()

    def test_confirmed_clone_runs_with_selected_values(self) -> None:
        app, mb, _, _ = self._run(confirm=True)

        mb.askyesno.assert_called_once()
        app._run_clone_cmd.assert_called_once_with("Ubuntu", "Ubuntu-clone", "C:/wsl/clone", "2")
        app._log_operation.assert_called_once_with("複製", "Ubuntu", "→ Ubuntu-clone")

    def test_confirmation_shows_source_target_and_folder(self) -> None:
        _, mb, _, _ = self._run(confirm=False)

        message = mb.askyesno.call_args.args[1]
        for expected in ("Ubuntu", "Ubuntu-clone", "C:/wsl/clone"):
            self.assertIn(expected, message)

    def test_cancelled_name_input_does_nothing(self) -> None:
        app, mb, _, fd = self._run(new_name=None)

        fd.askdirectory.assert_not_called()
        mb.askyesno.assert_not_called()
        app._run_clone_cmd.assert_not_called()

    def test_name_that_already_exists_is_rejected_before_asking_for_a_folder(self) -> None:
        app, mb, _, fd = self._run(new_name="Debian")  # 既存の名前

        mb.showwarning.assert_called_once()
        fd.askdirectory.assert_not_called()
        mb.askyesno.assert_not_called()
        app._run_clone_cmd.assert_not_called()

    def test_cancelled_folder_selection_does_not_prompt_or_clone(self) -> None:
        app, mb, _, _ = self._run(folder="")

        mb.askyesno.assert_not_called()
        app._run_clone_cmd.assert_not_called()

    def test_without_selection_neither_prompts_nor_clones(self) -> None:
        app, mb, sd, _ = self._run(name=None)

        mb.showwarning.assert_called_once()
        sd.askstring.assert_not_called()
        mb.askyesno.assert_not_called()
        app._run_clone_cmd.assert_not_called()


@unittest.skipIf(wslmgr is None, f"wslmgr を import できません: {_IMPORT_ERROR}")
class CreateSnapshotTests(unittest.TestCase):
    """スナップショット作成は、コメント入力後に進捗ダイアログ経由で ``--export`` を実行する。"""

    @staticmethod
    def _run(
        snap_dir: str, comment: str | None = "memo", name: str | None = "Ubuntu"
    ) -> tuple[MagicMock, MagicMock, MagicMock]:
        app = _make_app(name)
        app._snapshot_dir.return_value = snap_dir
        with (
            patch("wslmgr.messagebox") as mb,
            patch("wslmgr.simpledialog") as sd,
            patch("wslmgr.TransferProgressDialog") as transfer,
            patch("wslmgr._get_distro_vhdx_path", return_value=None),
        ):
            sd.askstring.return_value = comment
            wslmgr.WSLManager._create_snapshot(app)
        return app, mb, transfer

    def test_cancelled_comment_input_does_not_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app, _, transfer = self._run(tmp, comment=None)

        transfer.assert_not_called()
        app._log_operation.assert_not_called()

    def test_without_selection_does_not_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, mb, transfer = self._run(tmp, name=None)

        mb.showwarning.assert_called_once()
        transfer.assert_not_called()

    def test_unusable_snapshot_dir_shows_error_and_does_not_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            a_file = os.path.join(tmp, "file")
            with open(a_file, "w", encoding="utf-8") as f:
                f.write("x")
            # ファイルの下にはフォルダを作れない
            app, mb, transfer = self._run(os.path.join(a_file, "snapshots"))

        mb.showerror.assert_called_once()
        transfer.assert_not_called()
        app._log_operation.assert_not_called()

    def test_export_arguments_use_a_partial_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app, _, transfer = self._run(tmp)

            self.assertEqual(transfer.call_count, 1)
            wsl_args = transfer.call_args.args[3]
            self.assertEqual(wsl_args[:2], ["--export", "Ubuntu"])
            partial = wsl_args[2]
            self.assertTrue(partial.startswith(tmp))
            # 完成するまでは最終的な .tar の名前では書かない (途中のファイルを残さないため)
            self.assertNotEqual(os.path.splitext(partial)[1], ".tar")
            app._log_operation.assert_called_once()

    def _finish(self, returncode: int, cancelled: bool) -> tuple[MagicMock, list[str]]:
        with tempfile.TemporaryDirectory() as tmp:
            app, _, transfer = self._run(tmp)
            partial = transfer.call_args.args[3][2]
            on_done = transfer.call_args.args[-1]
            with open(partial, "wb") as f:
                f.write(b"tar-bytes")
            on_done(returncode, "err", cancelled)
            files = sorted(os.listdir(tmp))
        return app, files

    def test_successful_export_is_finalized_with_metadata(self) -> None:
        app, files = self._finish(0, False)

        self.assertEqual(len([f for f in files if f.endswith(".tar")]), 1)
        self.assertEqual(len([f for f in files if f.endswith(".json")]), 1)
        # 途中ファイル (.wslmgr-partial) は残らず、.tar と .json の 2 件だけになる
        self.assertFalse([f for f in files if wsl_core.PARTIAL_WRITE_SUFFIX in f], files)
        self.assertEqual(len(files), 2, files)
        app._refresh.assert_called_once()

    def test_cancelled_export_leaves_no_files(self) -> None:
        app, files = self._finish(1, True)

        self.assertEqual(files, [])
        self.assertIn("キャンセル", str(app._log_operation.call_args_list[-1]))

    def test_failed_export_leaves_no_files(self) -> None:
        app, files = self._finish(1, False)

        self.assertEqual(files, [])
        app._refresh.assert_called_once()


@unittest.skipIf(wslmgr is None, f"wslmgr を import できません: {_IMPORT_ERROR}")
class InstallConfirmationTests(unittest.TestCase):
    @staticmethod
    def _run(result: str | None, confirm: bool, err: str | None = None) -> tuple:
        app = _make_app()
        with (
            patch("wslmgr.InstallDialog") as dialog,
            patch("wslmgr.messagebox") as mb,
        ):
            dialog.return_value.result = result
            mb.askyesno.return_value = confirm
            wslmgr.WSLManager._open_install_dialog(app, ["Ubuntu"], err)
        return app, mb

    def test_cancelled_selection_does_not_prompt_or_install(self) -> None:
        app, mb = self._run(None, True)

        mb.askyesno.assert_not_called()
        app._run_wsl_cmd.assert_not_called()

    def test_declined_confirmation_does_not_install(self) -> None:
        app, mb = self._run("Ubuntu-24.04", False)

        mb.askyesno.assert_called_once()
        app._run_wsl_cmd.assert_not_called()

    def test_confirmed_installs_without_launching(self) -> None:
        app, mb = self._run("Ubuntu-24.04", True)

        mb.askyesno.assert_called_once()
        self.assertIn("Ubuntu-24.04", mb.askyesno.call_args.args[1])
        app._run_wsl_cmd.assert_called_once()
        self.assertEqual(
            app._run_wsl_cmd.call_args.args[0], ["--install", "-d", "Ubuntu-24.04", "--no-launch"]
        )

    def test_fetch_error_is_reported_before_the_dialog(self) -> None:
        app, _ = self._run(None, False, err="network down")

        app._set_status.assert_any_call("network down")


@unittest.skipIf(wslmgr is None, f"wslmgr を import できません: {_IMPORT_ERROR}")
class WslConfSavedConfirmationTests(unittest.TestCase):
    """``wsl.conf`` の保存後、再起動 (``wsl --terminate``) するかを確認する。"""

    MODULE = "wslmgr_gui.dialogs.distro_conf"

    @staticmethod
    def _make_dialog(exists: bool = True) -> MagicMock:
        dialog = MagicMock()
        dialog._distro = "Ubuntu"
        dialog.winfo_exists.return_value = exists
        return dialog

    def _saved(self, *, ok: bool, answer: bool, exists: bool = True) -> tuple:
        dialog = self._make_dialog(exists)
        with (
            patch(f"{self.MODULE}.messagebox") as mb,
            patch(f"{self.MODULE}.threading") as threading_mock,
            patch("subprocess.run") as run,
        ):
            mb.askyesno.return_value = answer
            wslmgr.DistroConfDialog._on_saved(
                dialog, ok, "disk full", {"boot": {"systemd": "true"}}
            )
        return dialog, mb, threading_mock, run

    def test_declined_restart_closes_without_terminating(self) -> None:
        dialog, mb, threading_mock, run = self._saved(ok=True, answer=False)

        mb.askyesno.assert_called_once()
        threading_mock.Thread.assert_not_called()
        run.assert_not_called()
        dialog.destroy.assert_called_once()
        # MagicMock は未代入でも真になるため、True の代入そのものを確認する
        self.assertIs(dialog.result, True)

    def test_confirmed_restart_starts_background_terminate(self) -> None:
        dialog, mb, threading_mock, run = self._saved(ok=True, answer=True)

        mb.askyesno.assert_called_once()
        threading_mock.Thread.assert_called_once()
        threading_mock.Thread.return_value.start.assert_called_once()
        run.assert_not_called()  # 実際の実行はスレッド側 (モック) のみ
        dialog.destroy.assert_not_called()  # 再起動の完了後に閉じる

    def test_failed_save_shows_error_and_never_asks_to_restart(self) -> None:
        dialog, mb, threading_mock, _ = self._saved(ok=False, answer=True)

        mb.showerror.assert_called_once()
        mb.askyesno.assert_not_called()
        threading_mock.Thread.assert_not_called()
        dialog._set_form_enabled.assert_called_once_with(True)

    def test_closed_window_neither_prompts_nor_restarts(self) -> None:
        _, mb, threading_mock, _ = self._saved(ok=True, answer=True, exists=False)

        mb.askyesno.assert_not_called()
        threading_mock.Thread.assert_not_called()

    def test_terminate_command_runs_for_the_edited_distro(self) -> None:
        dialog = self._make_dialog()
        with (
            patch(f"{self.MODULE}.messagebox") as mb,
            patch(f"{self.MODULE}.threading") as threading_mock,
        ):
            mb.askyesno.return_value = True
            wslmgr.DistroConfDialog._on_saved(dialog, True, "", {})
            target = threading_mock.Thread.call_args.kwargs["target"]
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stderr=b"")
            target()  # 実際の wsl は呼ばれず、subprocess.run のモックに記録される

        self.assertEqual(run.call_args.args[0], ["wsl", "--terminate", "Ubuntu"])
        dialog.after.assert_called_once()

    def test_failed_terminate_warns_and_closes(self) -> None:
        dialog = self._make_dialog()
        with patch(f"{self.MODULE}.messagebox") as mb:
            wslmgr.DistroConfDialog._on_terminated(dialog, 1, "busy")

        mb.showwarning.assert_called_once()
        dialog.destroy.assert_called_once()

    def test_successful_terminate_closes_quietly(self) -> None:
        dialog = self._make_dialog()
        with patch(f"{self.MODULE}.messagebox") as mb:
            wslmgr.DistroConfDialog._on_terminated(dialog, 0, "")

        mb.showwarning.assert_not_called()
        dialog.destroy.assert_called_once()


@unittest.skipIf(wslmgr is None, f"wslmgr を import できません: {_IMPORT_ERROR}")
class KillProcessConfirmationTests(unittest.TestCase):
    """プロセスの終了 (TERM / KILL) は、確認してからバックグラウンドで ``kill`` を実行する。"""

    MODULE = "wslmgr_gui.dialogs.process"

    @staticmethod
    def _make_window(values: list | None = None) -> MagicMock:
        window = MagicMock()
        window._language = "en"
        window._t.side_effect = lambda key, **v: wsl_core.translate(key, "en", **v)
        window._distro_name = "Ubuntu"
        window._tree.item.return_value = {
            "values": values if values is not None else [4321, "root", "0.0", "1.0", "sleep 100"]
        }
        return window

    def _kill(self, signal: str, answer: bool, values: list | None = None) -> tuple:
        window = self._make_window(values)
        with (
            patch(f"{self.MODULE}.messagebox") as mb,
            patch(f"{self.MODULE}.threading") as threading_mock,
            patch("subprocess.run") as run,
        ):
            mb.askyesno.return_value = answer
            wslmgr.ProcessWindow._kill_process(window, "row", signal)
        return window, mb, threading_mock, run

    def test_declined_does_not_send_a_signal(self) -> None:
        _, mb, threading_mock, run = self._kill("KILL", False)

        mb.askyesno.assert_called_once()
        threading_mock.Thread.assert_not_called()
        run.assert_not_called()

    def test_confirmed_starts_background_kill(self) -> None:
        _, mb, threading_mock, run = self._kill("TERM", True)

        mb.askyesno.assert_called_once()
        threading_mock.Thread.assert_called_once()
        threading_mock.Thread.return_value.start.assert_called_once()
        run.assert_not_called()  # 実行はスレッド側 (モック) のみ

    def test_confirmation_names_the_process_and_differs_for_kill(self) -> None:
        _, mb_term, _, _ = self._kill("TERM", False)
        _, mb_kill, _, _ = self._kill("KILL", False)

        term_message = mb_term.askyesno.call_args.args[1]
        kill_message = mb_kill.askyesno.call_args.args[1]
        for message in (term_message, kill_message):
            self.assertIn("4321", message)
            self.assertIn("sleep 100", message)
        self.assertNotEqual(term_message, kill_message)  # 強制終了は別の文言で確認する

    def _command_for(self, signal: str) -> tuple[list[str], float]:
        window = self._make_window()
        with (
            patch(f"{self.MODULE}.messagebox") as mb,
            patch(f"{self.MODULE}.threading") as threading_mock,
        ):
            mb.askyesno.return_value = True
            wslmgr.ProcessWindow._kill_process(window, "row", signal)
            target = threading_mock.Thread.call_args.kwargs["target"]
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stderr=b"")
            target()  # 実際の wsl は呼ばれず、subprocess.run のモックに記録される
        return run.call_args.args[0], run.call_args.kwargs["timeout"]

    def test_kill_command_sends_kill_to_the_pid_inside_the_distro(self) -> None:
        command, timeout = self._command_for("KILL")

        self.assertEqual(command, ["wsl", "-d", "Ubuntu", "--", "kill", "-KILL", "4321"])
        self.assertEqual(timeout, 5.0)

    def test_term_command_sends_term_not_kill(self) -> None:
        # 穏やかな終了 (TERM) が、確認なく強制終了 (KILL) にすり替わらないこと
        command, _ = self._command_for("TERM")

        self.assertEqual(command, ["wsl", "-d", "Ubuntu", "--", "kill", "-TERM", "4321"])

    def test_empty_row_does_not_prompt_or_kill(self) -> None:
        _, mb, threading_mock, run = self._kill("KILL", True, values=[])

        mb.askyesno.assert_not_called()
        threading_mock.Thread.assert_not_called()
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
