"""刷新したメイン画面 (``WSLManager``) と、スレッド→UI キューの挙動を確認するテスト。

実際のウィンドウは作らない。``WSLManager`` のメソッドは ``MagicMock`` の ``self`` に対して
呼び、``UiQueue`` は ``after`` だけを持つ偽のルートで動かす。``wsl.exe`` も起動しない。
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import wsl_core

try:
    import tkinter as tk

    import wslmgr
    from wslmgr_gui import ui_queue
except ImportError as exc:  # tkinter が無い環境のみ
    wslmgr = None
    ui_queue = None  # type: ignore[assignment]
    _IMPORT_ERROR = str(exc)
else:
    _IMPORT_ERROR = ""


def _make_app(distro: dict | None = None) -> MagicMock:
    app = MagicMock()
    app._language = "en"
    app._t.side_effect = lambda key, **values: wsl_core.translate(key, "en", **values)
    app._selected_distro.return_value = distro
    app._selected_name.return_value = distro["name"] if distro else None
    return app


def _distro(**overrides: object) -> dict:
    distro = {"name": "Ubuntu", "state": "Stopped", "version": "2", "default": False, "ip": "-"}
    distro.update(overrides)
    return distro


class _FakeRoot:
    """``UiQueue`` が使う ``after`` / ``after_cancel`` / 例外報告だけを持つルート。"""

    def __init__(self) -> None:
        self.scheduled: list[tuple[int, object]] = []
        self.cancelled: list[str] = []
        self.reported: list[tuple] = []

    def after(self, ms: int, fn: object) -> str:
        self.scheduled.append((ms, fn))
        return f"job-{len(self.scheduled)}"

    def after_cancel(self, job: str) -> None:
        self.cancelled.append(job)

    def report_callback_exception(self, *exc: object) -> None:
        self.reported.append(exc)

    def run_next(self) -> None:
        _ms, fn = self.scheduled.pop(0)
        fn()  # type: ignore[operator]


@unittest.skipIf(wslmgr is None, f"wslmgr を import できません: {_IMPORT_ERROR}")
class UiQueueTests(unittest.TestCase):
    def test_posted_callbacks_run_only_when_the_main_thread_drains(self) -> None:
        root = _FakeRoot()
        queue = ui_queue.UiQueue(root)  # type: ignore[arg-type]
        calls: list[str] = []

        queue.post(None, lambda: calls.append("a"))
        queue.post(None, lambda: calls.append("b"))
        self.assertEqual(calls, [])  # 積んだだけでは実行しない (ワーカーは Tk に触れない)

        root.run_next()

        self.assertEqual(calls, ["a", "b"])
        self.assertEqual(len(root.scheduled), 1)  # 次の確認を予約し直す

    def test_a_modal_callback_does_not_block_later_results(self) -> None:
        # コールバックがモーダルダイアログを開いても (ネストしたイベントループ)、
        # 次の確認は予約済みなので、ほかの結果は反映され続ける
        root = _FakeRoot()
        queue = ui_queue.UiQueue(root)  # type: ignore[arg-type]
        calls: list[str] = []

        def modal() -> None:
            queue.post(None, lambda: calls.append("while the dialog is open"))
            root.run_next()  # ダイアログ表示中に Tk が次の確認を実行する
            calls.append("dialog closed")

        queue.post(None, modal)
        root.run_next()

        self.assertEqual(calls, ["while the dialog is open", "dialog closed"])
        self.assertEqual(len(root.scheduled), 1)  # 予約は常に 1 つだけ

    def test_callbacks_for_destroyed_widgets_are_dropped(self) -> None:
        root = _FakeRoot()
        queue = ui_queue.UiQueue(root)  # type: ignore[arg-type]
        widget = MagicMock()
        widget.winfo_exists.return_value = False
        fn = MagicMock()

        queue.post(widget, fn)
        root.run_next()

        fn.assert_not_called()

    def test_a_failing_callback_does_not_stop_the_queue(self) -> None:
        root = _FakeRoot()
        queue = ui_queue.UiQueue(root)  # type: ignore[arg-type]
        calls: list[str] = []

        def boom() -> None:
            raise ValueError("bug")

        queue.post(None, boom)
        queue.post(None, lambda: calls.append("after"))
        root.run_next()

        self.assertEqual(calls, ["after"])
        self.assertEqual(len(root.reported), 1)
        self.assertIs(root.reported[0][0], ValueError)

    def test_close_cancels_polling_and_ignores_later_posts(self) -> None:
        root = _FakeRoot()
        queue = ui_queue.UiQueue(root)  # type: ignore[arg-type]
        fn = MagicMock()

        queue.close()
        queue.post(None, fn)

        self.assertEqual(root.cancelled, ["job-1"])
        fn.assert_not_called()

    def test_post_to_ui_uses_the_queue_of_the_widgets_root(self) -> None:
        root = _FakeRoot()
        queue = ui_queue.install(root)  # type: ignore[arg-type]
        widget = MagicMock()
        widget._root.return_value = root
        widget.winfo_exists.return_value = True
        fn = MagicMock()

        ui_queue.post_to_ui(widget, fn)

        widget.after.assert_not_called()
        root.run_next()
        fn.assert_called_once()
        self.assertIs(ui_queue.install(root), queue)  # 2 回目は同じキューを返す

    def test_post_to_ui_falls_back_to_after_without_a_queue(self) -> None:
        widget = MagicMock()
        widget._root.return_value = object()  # キューを持たないルート
        fn = MagicMock()

        ui_queue.post_to_ui(widget, fn)

        widget.after.assert_called_once_with(0, fn)

    def test_post_to_ui_ignores_a_destroyed_window(self) -> None:
        widget = MagicMock()
        widget._root.return_value = object()
        widget.after.side_effect = tk.TclError("application has been destroyed")

        ui_queue.post_to_ui(widget, MagicMock())  # 例外を投げない


@unittest.skipIf(wslmgr is None, f"wslmgr を import できません: {_IMPORT_ERROR}")
class ActionStateTests(unittest.TestCase):
    def test_buttons_and_menu_items_follow_the_selected_distribution(self) -> None:
        app = _make_app(_distro(state="Running"))
        start, stop = MagicMock(), MagicMock()
        app._toolbar_buttons = {"start": start, "stop": stop}
        menu = MagicMock()
        app._menu_items = [(menu, 3, "start"), (menu, 4, "stop")]

        wslmgr.WSLManager._update_action_states(app)

        start.state.assert_called_once_with(["disabled"])
        stop.state.assert_called_once_with(["!disabled"])
        menu.entryconfigure.assert_any_call(3, state=tk.DISABLED)
        menu.entryconfigure.assert_any_call(4, state=tk.NORMAL)
        app._detail_panel.show.assert_called_once()

    def test_everything_is_disabled_without_a_selection(self) -> None:
        app = _make_app(None)
        button = MagicMock()
        app._toolbar_buttons = {"terminal": button}
        app._menu_items = []

        wslmgr.WSLManager._update_action_states(app)

        button.state.assert_called_once_with(["disabled"])
        app._detail_panel.show.assert_called_once()
        self.assertIsNone(app._detail_panel.show.call_args.args[0])

    def test_selected_distro_is_looked_up_by_the_selected_row(self) -> None:
        app = MagicMock()
        app._all_distros = [{"name": "Ubuntu"}, {"name": "Debian"}]
        app._selected_name.return_value = "Debian"
        app._distro_by_name.side_effect = lambda name: wslmgr.WSLManager._distro_by_name(
            app, name
        )

        self.assertEqual(wslmgr.WSLManager._selected_distro(app), {"name": "Debian"})


@unittest.skipIf(wslmgr is None, f"wslmgr を import できません: {_IMPORT_ERROR}")
class StartDistroTests(unittest.TestCase):
    def test_start_runs_a_harmless_command_in_the_background(self) -> None:
        app = _make_app(_distro(state="Stopped"))

        wslmgr.WSLManager._start_distro(app)

        app._run_wsl_cmd.assert_called_once()
        self.assertEqual(app._run_wsl_cmd.call_args.args[0], ["-d", "Ubuntu", "--", "true"])

    def test_start_does_nothing_for_a_running_distribution(self) -> None:
        app = _make_app(_distro(state="Running"))

        wslmgr.WSLManager._start_distro(app)

        app._run_wsl_cmd.assert_not_called()

    @patch("wslmgr.messagebox")
    def test_start_without_selection_warns(self, mb: MagicMock) -> None:
        app = _make_app(None)

        wslmgr.WSLManager._start_distro(app)

        mb.showwarning.assert_called_once()
        app._run_wsl_cmd.assert_not_called()


@unittest.skipIf(wslmgr is None, f"wslmgr を import できません: {_IMPORT_ERROR}")
class RunWslCommandTests(unittest.TestCase):
    """``_run_wsl_cmd``: 失敗はステータスバーだけでなくエラーダイアログでも知らせる。"""

    def _run(self, completed: MagicMock | Exception) -> MagicMock:
        app = _make_app(_distro())
        with (
            patch("wslmgr.threading.Thread") as thread,
            patch("wslmgr.subprocess.run") as run,
        ):
            if isinstance(completed, Exception):
                run.side_effect = completed
            else:
                run.return_value = completed
            wslmgr.WSLManager._run_wsl_cmd(app, ["--terminate", "Ubuntu"], "ok", "failed")
            app._begin_busy.assert_called_once()
            thread.call_args.kwargs["target"]()  # ワーカーの処理をこのスレッドで実行
        # ワーカーは UI を直接触らず、メインスレッドへの依頼だけを行う
        app._show_error.assert_not_called()
        done = app._call_soon_safe.call_args.args[0]
        done()
        return app

    def test_success_updates_the_status_and_refreshes(self) -> None:
        app = self._run(MagicMock(returncode=0, stdout=b"", stderr=b""))

        app._set_status.assert_called_once_with("ok")
        app._show_error.assert_not_called()
        app._end_busy.assert_called_once()
        app._refresh.assert_called_once()

    def test_failure_shows_an_error_dialog_with_wsl_output(self) -> None:
        stderr = "There is no distribution with the supplied name.".encode("utf-16-le")
        app = self._run(MagicMock(returncode=1, stdout=b"", stderr=stderr))

        app._show_error.assert_called_once_with(
            "failed", "There is no distribution with the supplied name."
        )
        app._end_busy.assert_called_once()

    def test_failure_falls_back_to_stdout(self) -> None:
        app = self._run(MagicMock(returncode=1, stdout="busy".encode("utf-16-le"), stderr=b""))

        self.assertEqual(app._show_error.call_args.args[1], "busy")

    def test_missing_wsl_exe_is_reported(self) -> None:
        app = self._run(FileNotFoundError("wsl"))

        app._show_error.assert_called_once()


@unittest.skipIf(wslmgr is None, f"wslmgr を import できません: {_IMPORT_ERROR}")
class RefreshResultTests(unittest.TestCase):
    def test_error_without_a_previous_list_shows_the_error_state(self) -> None:
        app = _make_app()
        app._refresh_pending = False
        app._refresh_error = None
        app._all_distros = []

        wslmgr.WSLManager._apply_refresh_result(app, [], "wsl.exe was not found.", None)

        self.assertEqual(app._refresh_error, "wsl.exe was not found.")
        self.assertEqual(app._all_distros, [])
        self.assertIn("wsl.exe was not found.", app._set_status.call_args.args[0])
        app._render_distros.assert_called_once()

    def test_a_temporary_error_keeps_the_previous_list(self) -> None:
        # 一時的なタイムアウトで一覧が消え、すべての操作が無効になるのを避ける
        app = _make_app()
        app._refresh_pending = False
        app._refresh_error = None
        previous = [{"name": "Ubuntu", "state": "Running"}]
        app._all_distros = previous

        wslmgr.WSLManager._apply_refresh_result(app, [], "WSL did not respond in time.", None)

        self.assertIs(app._all_distros, previous)
        self.assertIsNone(app._refresh_error)
        self.assertIn("WSL did not respond in time.", app._set_status.call_args.args[0])
        app._resource_history.record_refresh.assert_not_called()

    def test_success_records_history_and_time(self) -> None:
        app = _make_app()
        app._refresh_pending = False
        distros = [{"name": "Ubuntu", "state": "Running"}]

        wslmgr.WSLManager._apply_refresh_result(app, distros, None, "Ubuntu")

        self.assertIsNone(app._refresh_error)
        self.assertIs(app._all_distros, distros)
        app._resource_history.record_refresh.assert_called_once_with(distros)
        self.assertIsNotNone(app._last_refresh)
        app._render_distros.assert_called_once_with("Ubuntu")

    def test_a_pending_refresh_runs_after_the_current_one(self) -> None:
        app = _make_app()
        app._refresh_pending = True

        wslmgr.WSLManager._apply_refresh_result(app, [], None, None)

        self.assertFalse(app._refresh_pending)
        app._refresh.assert_called_once()


@unittest.skipIf(wslmgr is None, f"wslmgr を import できません: {_IMPORT_ERROR}")
class ShortcutAndMiscTests(unittest.TestCase):
    def test_shortcuts_are_bound_to_the_main_window_only(self) -> None:
        # bind_all だとダイアログ内のキー操作 (例: Delete) でもメイン画面の操作が走ってしまう
        app = _make_app()

        wslmgr.WSLManager._bind_shortcuts(app)

        app.bind_all.assert_not_called()
        bound = {call.args[0] for call in app.bind.call_args_list}
        self.assertTrue({"<F5>", "<Control-f>", "<Control-e>", "<Control-n>"} <= bound)
        self.assertNotIn("<Delete>", bound)  # Delete は一覧 (Treeview) にだけバインドする

    def test_double_click_on_a_heading_does_not_open_a_terminal(self) -> None:
        app = _make_app(_distro())
        app._tree.identify_region.return_value = "heading"

        wslmgr.WSLManager._on_tree_double_click(app, MagicMock(x=5, y=5))

        app._open_terminal.assert_not_called()

    def test_double_click_on_a_row_opens_a_terminal(self) -> None:
        app = _make_app(_distro())
        app._tree.identify_region.return_value = "cell"
        app._tree.identify_row.return_value = "Ubuntu"

        wslmgr.WSLManager._on_tree_double_click(app, MagicMock(x=5, y=30))

        app._open_terminal.assert_called_once()

    def test_copy_ip_copies_only_a_known_address(self) -> None:
        app = _make_app(_distro(ip="172.20.0.5"))
        wslmgr.WSLManager._copy_ip_address(app)
        app.clipboard_append.assert_called_once_with("172.20.0.5")

        app = _make_app(_distro(ip="-"))
        wslmgr.WSLManager._copy_ip_address(app)
        app.clipboard_append.assert_not_called()

    @patch("wslmgr.messagebox")
    def test_show_error_uses_a_dialog_and_the_status_bar(self, mb: MagicMock) -> None:
        app = _make_app()

        wslmgr.WSLManager._show_error(app, "Failed.", "details")

        mb.showerror.assert_called_once()
        self.assertIn("details", mb.showerror.call_args.args[1])
        self.assertIs(mb.showerror.call_args.kwargs["parent"], app)
        app._set_status.assert_called_once()

    def test_busy_indicator_is_reference_counted(self) -> None:
        app = _make_app()
        app._busy_count = 0

        wslmgr.WSLManager._begin_busy(app)
        wslmgr.WSLManager._begin_busy(app)
        wslmgr.WSLManager._end_busy(app)
        app._busy_bar.pack_forget.assert_not_called()  # まだ 1 件残っている
        wslmgr.WSLManager._end_busy(app)

        app._show_busy_bar.assert_called_once()
        app._busy_bar.pack_forget.assert_called_once()
        self.assertEqual(app._busy_count, 0)


if __name__ == "__main__":
    unittest.main()
