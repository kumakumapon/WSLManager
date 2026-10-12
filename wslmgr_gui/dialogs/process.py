"""WSL2 ディストリビューションのプロセス一覧ウィンドウ。"""

from __future__ import annotations

import subprocess
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import wsl_core
from wslmgr_gui.widgets import TreeviewSorter
from wslmgr_gui.winutil import CREATE_NO_WINDOW


class ProcessWindow(tk.Toplevel):
    """WSL2 ディストリビューションのプロセス一覧ウィンドウ。"""

    REFRESH_INTERVAL = 3000  # ms

    def __init__(self, parent: tk.Tk, distro_name: str) -> None:
        super().__init__(parent)
        self._language = getattr(parent, "_language", wsl_core.LANGUAGE_AUTO)
        self._distro_name = distro_name
        self.title(self._t("gui.process.title", name=distro_name))
        self.geometry("750x480")
        self.minsize(500, 350)
        self._refresh_job: str | None = None
        self._auto_refresh_var = tk.BooleanVar(value=True)
        self._filter_var = tk.StringVar()
        self._all_processes: list[dict] = []
        self._build_ui()
        self._filter_var.trace_add("write", lambda *_: self._render_processes())
        self._do_refresh()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _t(self, key: str, **values: object) -> str:
        return wsl_core.translate(key, self._language, **values)

    @staticmethod
    def _fetch_processes(distro_name: str) -> tuple[list[dict], str | None]:
        """指定ディストリビューション内のプロセス一覧を取得します。"""
        try:
            result = subprocess.run(
                [
                    "wsl",
                    "-d",
                    distro_name,
                    "--",
                    "sh",
                    "-lc",
                    "ps -eo pid,user,pcpu,rss,comm --sort=-pcpu 2>/dev/null"
                    " || ps -eo pid,user,pcpu,rss,comm",
                ],
                capture_output=True,
                creationflags=CREATE_NO_WINDOW,
                timeout=5.0,
            )
        except subprocess.TimeoutExpired:
            return [], "タイムアウトしました。"
        except OSError as e:
            return [], str(e)

        if result.returncode != 0:
            stderr = wsl_core.decode_wsl_output(result.stderr).strip()
            return [], stderr or "プロセス一覧の取得に失敗しました。"

        processes = wsl_core.parse_process_list(wsl_core.decode_wsl_output(result.stdout))
        return processes, None

    def _build_ui(self) -> None:
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        toolbar = ttk.Frame(main_frame)
        toolbar.pack(fill=tk.X, pady=(0, 8))

        ttk.Button(
            toolbar,
            text=self._t("gui.common.refresh"),
            command=self._do_refresh,
            width=8,
        ).pack(side=tk.LEFT, padx=2)
        ttk.Checkbutton(
            toolbar,
            text=self._t("gui.process.auto_refresh"),
            variable=self._auto_refresh_var,
            command=self._toggle_auto_refresh,
        ).pack(side=tk.LEFT, padx=8)

        ttk.Label(toolbar, text=self._t("gui.common.filter")).pack(side=tk.LEFT, padx=(8, 2))
        ttk.Entry(toolbar, textvariable=self._filter_var, width=16).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            toolbar,
            text=self._t("gui.common.filter_clear"),
            width=2,
            command=lambda: self._filter_var.set(""),
        ).pack(side=tk.LEFT, padx=2)

        self._count_var = tk.StringVar(value="")
        ttk.Label(toolbar, textvariable=self._count_var).pack(side=tk.RIGHT, padx=5)

        tree_frame = ttk.Frame(main_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("pid", "user", "cpu", "memory", "command")
        self._tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")
        self._tree.heading("pid", text=self._t("gui.process.col_pid"))
        self._tree.heading("user", text=self._t("gui.process.col_user"))
        self._tree.heading("cpu", text=self._t("gui.process.col_cpu"))
        self._tree.heading("memory", text=self._t("gui.process.col_memory"))
        self._tree.heading("command", text=self._t("gui.process.col_command"))

        self._tree.column("pid", width=70, minwidth=60, anchor=tk.CENTER)
        self._tree.column("user", width=120, minwidth=80)
        self._tree.column("cpu", width=80, minwidth=70, anchor=tk.CENTER)
        self._tree.column("memory", width=110, minwidth=80, anchor=tk.CENTER)
        self._tree.column("command", width=340, minwidth=150)

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # 列クリックソート
        self._sorter = TreeviewSorter(self._tree, numeric_columns={"pid", "cpu", "memory"})

        # 右クリックコンテキストメニュー(プロセス終了)
        self._tree.bind("<Button-3>", self._show_process_context_menu)

        self._status_var = tk.StringVar(value=self._t("gui.process.loading"))
        ttk.Label(
            main_frame,
            textvariable=self._status_var,
            relief=tk.SUNKEN,
            anchor=tk.W,
            padding=(4, 2),
        ).pack(fill=tk.X, pady=(8, 0))

    def _do_refresh(self) -> None:
        if self._refresh_job:
            self.after_cancel(self._refresh_job)
            self._refresh_job = None
        self._status_var.set(self._t("gui.process.refreshing"))
        distro = self._distro_name

        def _run() -> None:
            processes, err = self._fetch_processes(distro)
            self.after(0, lambda: self._apply_result(processes, err))

        threading.Thread(target=_run, daemon=True).start()

    def _apply_result(self, processes: list[dict], err: str | None) -> None:
        if err:
            for item in self._tree.get_children():
                self._tree.delete(item)
            self._status_var.set(self._t("gui.process.error", error=err))
        else:
            self._all_processes = processes
            self._render_processes()
            self._status_var.set(self._t("gui.process.refreshed"))

        if self._auto_refresh_var.get():
            self._refresh_job = self.after(self.REFRESH_INTERVAL, self._do_refresh)

    def _render_processes(self) -> None:
        """フィルタを適用してプロセス一覧を再描画します。"""
        filter_text = self._filter_var.get().casefold()

        for item in self._tree.get_children():
            self._tree.delete(item)

        displayed = 0
        for p in self._all_processes:
            if filter_text and (
                filter_text not in str(p["pid"]).casefold()
                and filter_text not in p["user"].casefold()
                and filter_text not in p["command"].casefold()
            ):
                continue
            self._tree.insert(
                "",
                tk.END,
                values=(p["pid"], p["user"], p["cpu"], p["memory"], p["command"]),
            )
            displayed += 1

        total = len(self._all_processes)
        if filter_text and displayed != total:
            self._count_var.set(
                self._t("gui.process.count_filtered", displayed=displayed, total=total)
            )
        else:
            self._count_var.set(self._t("gui.process.count", count=total))

        self._sorter.apply()

    def _show_process_context_menu(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        """右クリックでプロセス終了のコンテキストメニューを表示します。"""
        row = self._tree.identify_row(event.y)
        if not row:
            return
        self._tree.selection_set(row)
        self._tree.focus(row)

        menu = tk.Menu(self, tearoff=0)
        menu.add_command(
            label=self._t("gui.process.kill_term"),
            command=lambda: self._kill_process(row, "TERM"),
        )
        menu.add_command(
            label=self._t("gui.process.kill_kill"),
            command=lambda: self._kill_process(row, "KILL"),
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _kill_process(self, iid: str, signal: str) -> None:
        """選択行のプロセスにシグナルを送信します。

        Args:
            iid: Treeview のアイテム ID。
            signal: 送信するシグナル名("TERM" または "KILL")。
        """
        values = self._tree.item(iid)["values"]
        if not values:
            return
        pid = str(values[0])
        command = str(values[4])

        if signal == "KILL":
            confirm_msg = self._t("gui.process.kill_confirm_kill", pid=pid, command=command)
        else:
            confirm_msg = self._t("gui.process.kill_confirm_term", pid=pid, command=command)

        if not messagebox.askyesno(self._t("gui.common.confirm"), confirm_msg, parent=self):
            return

        distro = self._distro_name

        def _run() -> None:
            try:
                result = subprocess.run(
                    ["wsl", "-d", distro, "--", "kill", f"-{signal}", pid],
                    capture_output=True,
                    creationflags=CREATE_NO_WINDOW,
                    timeout=5.0,
                )
            except subprocess.TimeoutExpired:

                def _on_timeout() -> None:
                    try:
                        if self.winfo_exists():
                            self._status_var.set(self._t("gui.process.timeout"))
                    except tk.TclError:
                        pass

                self.after(0, _on_timeout)
                return
            except OSError as e:
                err_msg = str(e)

                def _on_oserror() -> None:
                    try:
                        if self.winfo_exists():
                            self._status_var.set(self._t("gui.process.error", error=err_msg))
                    except tk.TclError:
                        pass

                self.after(0, _on_oserror)
                return

            if result.returncode != 0:
                stderr = wsl_core.decode_wsl_output(result.stderr).strip()
                err_msg = stderr or f"終了コード {result.returncode}"

                def _on_fail() -> None:
                    try:
                        if self.winfo_exists():
                            self._status_var.set(self._t("gui.process.error", error=err_msg))
                    except tk.TclError:
                        pass

                self.after(0, _on_fail)
            else:

                def _on_success() -> None:
                    try:
                        if self.winfo_exists():
                            self._status_var.set(self._t("gui.process.kill_success", pid=pid))
                            self._do_refresh()
                    except tk.TclError:
                        pass

                self.after(0, _on_success)

        threading.Thread(target=_run, daemon=True).start()

    def _toggle_auto_refresh(self) -> None:
        if self._auto_refresh_var.get():
            if not self._refresh_job:
                self._refresh_job = self.after(self.REFRESH_INTERVAL, self._do_refresh)
        else:
            if self._refresh_job:
                self.after_cancel(self._refresh_job)
                self._refresh_job = None

    def _on_close(self) -> None:
        if self._refresh_job:
            self.after_cancel(self._refresh_job)
        self.destroy()
