Warning: truncated output (original token count: 48469)
Total output lines: 4683

"""
WSL Manager - WSL2 ディストリビューション管理ツール

WSL2 の個別ディストリビューションの起動・停止・管理を行う GUI アプリケーションです。
Windows 10/11 + WSL2 環境での使用を前提としています。
"""

from __future__ import annotations

import concurrent.futures
import os
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from collections.abc import Callable
from datetime import datetime
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import ClassVar

import wsl_core

try:
    import winreg
except ImportError:  # Windows 以外 (開発環境など)
    winreg = None  # type: ignore[assignment]


# ── Windows 専用フラグ ──────────────────────────────────────────────────────
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
CREATE_NEW_CONSOLE = 0x00000010 if sys.platform == "win32" else 0


class TreeviewSorter:
    """Treeview の列ヘッダクリックによるソート機能を提供するヘルパークラス。

    コンストラクタで全列のヘッダに ``command=`` を仕込み、クリックごとに
    昇順→降順をトグルします。``numeric_columns`` に含まれる列は数値ソート、
    それ以外は文字列(casefold)ソートを行います。
    """

    def __init__(self, tree: ttk.Treeview, numeric_columns: set[str]) -> None:
        self._tree = tree
        self._numeric_columns = numeric_columns
        # ソート状態: (列ID, 逆順フラグ) または None
        self._sort_col: str | None = None
        self._sort_reverse: bool = False
        # 各列の元のヘッダテキスト(マーカーなし)を保持
        self._orig_headings: dict[str, str] = {}
        for col in tree["columns"]:
            heading_info = tree.heading(col)
            orig_text = heading_info["text"]
            self._orig_headings[col] = orig_text
            tree.heading(col, command=lambda c=col: self._on_header_click(c))

    def _on_header_click(self, col: str) -> None:
        """ヘッダクリック時にソート状態を更新して並べ替えを実行します。"""
        if self._sort_col == col:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_col = col
            self._sort_reverse = False
        self._do_sort()

    def _do_sort(self) -> None:
        """現在のソート設定に従って行を並べ替えます。"""
        if self._sort_col is None:
            return
        col = self._sort_col
        reverse = self._sort_reverse
        tree = self._tree

        # ヘッダのマーカーを更新
        for c in tree["columns"]:
            base = self._orig_headings[c]
            if c == col:
                marker = " ▼" if reverse else " ▲"
                tree.heading(c, text=base + marker)
            else:
                tree.heading(c, text=base)

        # ソートキーを生成して並べ替える
        items = [(tree.set(iid, col), iid) for iid in tree.get_children("")]

        if col in self._numeric_columns:
            # 数値に変換できない値("-" など)は昇順・降順とも常に末尾に置く
            numeric_items = [x for x in items if wsl_core.is_numeric(x[0])]
            other_items = [x for x in items if not wsl_core.is_numeric(x[0])]
            numeric_items.sort(key=lambda item: float(item[0]), reverse=reverse)
            items = numeric_items + other_items
        else:
            items.sort(key=lambda item: item[0].casefold(), reverse=reverse)

        for index, (_, iid) in enumerate(items):
            tree.move(iid, "", index)

    def apply(self) -> None:
        """現在のソート設定を再適用します。未ソートなら何もしません。"""
        if self._sort_col is not None:
            self._do_sort()

    def get_state(self) -> tuple[str | None, bool]:
        """現在のソート状態を (列ID, 逆順フラグ) のタプルで返します。"""
        return (self._sort_col, self._sort_reverse)

    def set_state(self, col: str | None, reverse: bool) -> None:
        """ソート状態を外部から復元します。

        ``col`` が None または現在の列一覧に存在しない場合は未ソート状態に
        リセットします。この時点では並べ替えは行わず、状態の保持のみを
        行います (実際の並べ替えは後続の ``apply()`` 呼び出しで行われます)。
        """
        if col is None or col not in self._tree["columns"]:
            self._sort_col = None
            self._sort_reverse = False
        else:
            self._sort_col = col
            self._sort_reverse = reverse


def _iter_distro_registry() -> list[tuple[str, str]]:
    r"""レジストリから (DistributionName, BasePath) のペア一覧を取得します。

    HKCU\Software\Microsoft\Windows\CurrentVersion\Lxss 配下の各サブキーを走査し、
    BasePath は normalize_base_path で正規化済みの値を返します。
    """
    entries: list[tuple[str, str]] = []
    if winreg is None:
        return entries
    try:
        lxss = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Lxss",
        )
    except OSError:
        return entries
    with lxss:
        index = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(lxss, index)
            except OSError:
                break
            index += 1
            try:
                with winreg.OpenKey(lxss, subkey_name) as sub:
                    name, _ = winreg.QueryValueEx(sub, "DistributionName")
                    base_path, _ = winreg.QueryValueEx(sub, "BasePath")
            except OSError:
                continue
            entries.append((str(name), wsl_core.normalize_base_path(str(base_path))))
    return entries


def _get_distro_vhdx_sizes() -> dict[str, float]:
    """レジストリから各ディストリビューションの仮想ディスクサイズ (GB) を取得します。"""
    sizes: dict[str, float] = {}
    for name, base_path in _iter_distro_registry():
        vhdx_path = os.path.join(base_path, "ext4.vhdx")
        try:
            sizes[name] = os.path.getsize(vhdx_path) / (1024**3)
        except OSError:
            continue
    return sizes


def _get_distro_vhdx_path(name: str) -> str | None:
    """指定ディストリビューションの仮想ディスク (ext4.vhdx) の絶対パスを返します。"""
    for dname, base_path in _iter_distro_registry():
        if dname != name:
            continue
        vhdx_path = os.path.join(base_path, "ext4.vhdx")
        return vhdx_path if os.path.exists(vhdx_path) else None
    return None


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


class InstallDialog(tk.Toplevel):
    """ディストリビューションのインストール用モーダルダイアログ。

    候補一覧の Listbox と手入力用 Entry を組み合わせたダイアログです。
    ``wait_window()`` で待機し、選択結果を ``self.result`` で取得します。
    """

    def __init__(self, parent: tk.Tk, candidates: list[str]) -> None:
        super().__init__(parent)
        self._language = getattr(parent, "_language", wsl_core.LANGUAGE_AUTO)
        self.title(self._t("gui.install.title"))
        self.resizable(False, False)
        self.result: str | None = None
        self._candidates = candidates
        self._build_ui()
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def _t(self, key: str, **values: object) -> str:
        return wsl_core.translate(key, self._language, **values)

    def _build_ui(self) -> None:
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text=self._t("gui.install.label")).pack(anchor=tk.W, pady=(0, 6))

        if self._candidates:
            list_frame = ttk.Frame(frame)
            list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

            vsb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL)
            self._listbox = tk.Listbox(
                list_frame,
                yscrollcommand=vsb.set,
                selectmode=tk.SINGLE,
                height=12,
                width=40,
                activestyle="dotbox",
            )
            vsb.configure(command=self._listbox.yview)
            self._listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            vsb.pack(side=tk.RIGHT, fill=tk.Y)

            for name in self._candidates:
                self._listbox.insert(tk.END, name)

            self._listbox.bind("<<ListboxSelect>>", self._on_listbox_select)
        else:
            ttk.Label(
                frame,
                text=self._t("gui.install.empty_list"),
                foreground="#888888",
            ).pack(anchor=tk.W, pady=(0, 8))
            self._listbox = None  # type: ignore[assignment]

        entry_frame = ttk.Frame(frame)
        entry_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(entry_frame, text=self._t("gui.common.name")).pack(side=tk.LEFT, padx=(0, 6))
        self._entry_var = tk.StringVar()
        ttk.Entry(entry_frame, textvariable=self._entry_var, width=36).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X)
        ttk.Button(
            btn_frame,
            text=self._t("gui.install.btn_install"),
            command=self._on_install,
            width=12,
        ).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(
            btn_frame,
            text=self._t("gui.common.cancel"),
            command=self._on_cancel,
            width=10,
        ).pack(side=tk.RIGHT)

    def _on_listbox_select(self, _event: tk.Event) -> None:  # type: ignore[type-arg]
        """Listbox の選択を Entry へ反映します。"""
        if self._listbox is None:
            return
        sel = self._listbox.curselection()
        if sel:
            self._entry_var.set(self._listbox.get(sel[0]))

    def _on_install(self) -> None:
        value = self._entry_var.get().strip()
        valid, reason = wsl_core.validate_distro_name(value)
        if not valid:
            messagebox.showwarning(self._t("gui.common.warning"), reason, parent=self)
            return
        self.result = value
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()


class WslConfigDialog(tk.Toplevel):
    """.wslconfig ファイルを GUI で編集するモーダルダイアログ。

    ``wait_window()`` で待機し、保存成功時に ``self.result = True`` を返します。
    """

    # [wsl2] セクションで編集するキーの定義
    # (キー名, ラベルテキスト, ウィジェット種別, Combobox 選択肢 or None)
    _WSL2_FIELDS: ClassVar[list[tuple[str, str, str, list[str] | None]]] = [
        ("memory", "memory", "entry", None),
        ("processors", "processors", "entry", None),
        ("swap", "swap", "entry", None),
        ("swapFile", "swapFile", "entry", None),
        ("networkingMode", "networkingMode", "combo", ["", "NAT", "mirrored"]),
        ("localhostForwarding", "localhostForwarding", "combo", ["", "true", "false"]),
        ("nestedVirtualization", "nestedVirtualization", "combo", ["", "true", "false"]),
        ("guiApplications", "guiApplications", "combo", ["", "true", "false"]),
        ("kernel", "kernel", "entry", None),
        ("kernelCommandLine", "kernelCommandLine", "entry", None),
        ("vmIdleTimeout", "vmIdleTimeout", "entry", None),
        ("dnsTunneling", "dnsTunneling", "combo", ["", "true", "false"]),
        ("firewall", "firewall", "combo", ["", "true", "false"]),
        ("autoProxy", "autoProxy", "combo", ["", "true", "false"]),
    ]

    def __init__(self, parent: tk.Tk) -> None:
        super().__init__(parent)
        self.title(
            wsl_core.translate(
                "gui.wslconfig.title", getattr(parent, "_language", wsl_core.LANGUAGE_AUTO)
            )
        )
        self.resizable(True, False)
        self.result: bool | None = None
        self._path = os.path.expanduser("~/.wslconfig")
        self._sections: dict[str, dict[str, str]] = {}
        try:
            self._load_config()
        except wsl_core.WslConfigParseError as e:
            messagebox.showerror(
                "読み込みエラー",
                f".wslconfig のパースに失敗したためエディタを開けません:\n{self._path}\n\n{e}\n\n"
                "既存の設定を保護するため、ファイルを手動で修正してから再度開いてください。",
                parent=parent,
            )
            self.destroy()
            return
        self._build_ui()
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def _load_config(self) -> None:
        """設定ファイルを読み込み self._sections を初期化します。

        パース失敗時は :class:`wsl_core.WslConfigParseError` を送出し、
        呼び出し側 (__init__) はエラーダイアログを表示してダイアログを閉じます。
        """
        self._sections = {}
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            raise wsl_core.WslConfigParseError(f"読み込みに失敗しました: {e}") from e
        self._sections = wsl_core.parse_wslconfig(text)

    def _build_ui(self) -> None:
        frame = ttk.Frame(self, padding=14)
        frame.pack(fill=tk.BOTH, expand=True)

        # 説明ラベル
        info_frame = ttk.Frame(frame)
        info_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(
            info_frame,
            text="未設定（空欄）の項目は .wslconfig に書き込まれません。",
            foreground="#555555",
        ).pack(anchor=tk.W)
        ttk.Label(
            info_frame,
            text="変更の反映には WSL の全停止 (wsl --shutdown) が必要です。",
            foreground="#555555",
        ).pack(anchor=tk.W)
        ttk.Label(
            info_frame,
            text=(
                "※ 保存時にコメント行は保持されません。"
                "コメントを残したい場合は直接編集してください。"
            ),
            foreground="#885500",
        ).pack(anchor=tk.W)

        # パス表示
        ttk.Label(frame, text=f"編集ファイル: {self._path}", foreground="#777777").pack(
            anchor=tk.W, pady=(0, 8)
        )

        ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(0, 10))

        # [wsl2] フォーム
        ttk.Label(frame, text="[wsl2]", font=("", 10, "bold")).pack(anchor=tk.W, pady=(0, 6))

        form_frame = ttk.Frame(frame)
        form_frame.pack(fill=tk.X)

        wsl2 = self._sections.get("wsl2", {})
        self._field_vars: dict[str, tk.StringVar] = {}

        for row_idx, (key, label, widget_type, combo_values) in enumerate(self._WSL2_FIELDS):
            ttk.Label(form_frame, text=label, width=22, anchor=tk.W).grid(
                row=row_idx, column=0, sticky=tk.W, padx=(0, 8), pady=3
            )
            var = tk.StringVar(value=wsl2.get(key, ""))
            self._field_vars[key] = var
            if widget_type == "combo" and combo_values is not None:
                widget: tk.Widget = ttk.Combobox(
                    form_frame,
                    textvariable=var,
                    values=combo_values,
                    width=22,
                    state="readonly",
                )
            else:
                widget = ttk.Entry(form_frame, textvariable=var, width=24)
            widget.grid(row=row_idx, column=1, sticky=tk.W, pady=3)

        ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(12, 10))

        # ボタン行
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="保存", command=self._on_save, width=10).pack(
            side=tk.RIGHT, padx=(4, 0)
        )
        ttk.Button(btn_frame, text="キャンセル", command=self._on_cancel, width=10).pack(
            side=tk.RIGHT
        )

    def _on_save(self) -> None:
        """フォームの内容を検証して .wslconfig に書き込みます。"""
        validators = {
            "memory": wsl_core.validate_memory_string,
            "processors": wsl_core.validate_processors_string,
            "swap": wsl_core.validate_swap_string,
        }
        for key, validate_fn in validators.items():
            val = self._field_vars[key].get().strip()
            valid, reason = validate_fn(val)
            if not valid:
                messagebox.showwarning("入力エラー", reason, parent=self)
                return

        # 既存セクション・キーを保持しつつ [wsl2] を更新
        new_sections: dict[str, dict[str, str]] = {s: dict(kv) for s, kv in self._sections.items()}
        wsl2 = new_sections.setdefault("wsl2", {})
        for key, var in self._field_vars.items():
            wsl2[key] = var.get().strip()

        if not wsl_core.save_wslconfig(self._path, new_sections):
            messagebox.showerror(
                "保存エラー", f".wslconfig の書き込みに失敗しました:\n{self._path}", parent=self
            )
            return

        self.result = True
        messagebox.showinfo(
            "保存しました",
            f".wslconfig を保存しました。\n反映には WSL の全停止が必要です。\n({self._path})",
            parent=self,
        )
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()


class DistroConfDialog(tk.Toplevel):
    """ディストリビューションごとの ``/etc/wsl.conf`` を GUI で編集するモーダルダイアログ。

    読み込みは ``wsl -d <distro> -u root cat /etc/wsl.conf``、書き込みは
    ``wsl -d <distro> -u root sh -c 'cat > /etc/wsl.conf'`` (標準入力経由) で行い、
    いずれもバックグラウンドスレッドで実行して UI をブロックしません。
    停止中のディストロは読み書きのために WSL 側で一時的に起動されます。
    保存成功時は ``self.result = True`` を設定します。
    """

    # (セクション, キー, ラベル, ウィジェット種別, Combobox 選択肢 or None)
    _FIELDS: ClassVar[list[tuple[str, str, str, str, list[str] | None]]] = [
        ("boot", "systemd", "systemd", "combo", ["", "true", "false"]),
        ("boot", "command", "command", "entry", None),
        ("user", "default", "default", "entry", None),
        ("automount", "enabled", "enabled", "combo", ["", "true", "false"]),
        ("automount", "root", "root", "entry", None),
        ("network", "hostname", "hostname", "entry", None),
        ("network", "generateResolvConf", "generateResolvConf", "combo", ["", "true", "false"]),
        ("interop", "enabled", "enabled", "combo", ["", "true", "false"]),
        ("interop", "appendWindowsPath", "appendWindowsPath", "combo", ["", "true", "false"]),
    ]

    # (セクション, キー) -> バリデータ関数 (未登録のキーは検証なし)
    _VALIDATORS: ClassVar[dict[tuple[str, str], Callable[[str], tuple[bool, str]]]] = {
        ("boot", "systemd"): wsl_core.validate_wslconf_bool,
        ("user", "default"): wsl_core.validate_linux_username,
        ("automount", "enabled"): wsl_core.validate_wslconf_bool,
        ("automount", "root"): wsl_core.validate_mount_root,
        ("network", "hostname"): wsl_core.validate_hostname,
        ("network", "generateResolvConf"): wsl_core.validate_wslconf_bool,
        ("interop", "enabled"): wsl_core.validate_wslconf_bool,
        ("interop", "appendWindowsPath"): wsl_core.validate_wslconf_bool,
    }

    def __init__(self, parent: tk.Tk, distro_name: str) -> None:
        super().__init__(parent)
        self._app = parent
        self._distro = distro_name
        self._busy = False
        self._sections: dict[str, dict[str, str]] = {}
        self.result: bool | None = None
        self.title(
            wsl_core.translate(
                "gui.distroconf.title",
                getattr(parent, "_language", wsl_core.LANGUAGE_AUTO),
                name=distro_name,
            )
        )
        self.resizable(True, False)
        self._build_ui()
        self._set_form_enabled(False)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.grab_set()
        self._load_config()

    def _build_ui(self) -> None:
        frame = ttk.Frame(self, padding=14)
        frame.pack(fill=tk.BOTH, expand=True)

        info_frame = ttk.Frame(frame)
        info_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(
            info_frame,
            text="未設定（空欄）の項目は wsl.conf に書き込まれません。",
            foreground="#555555",
        ).pack(anchor=tk.W)
        ttk.Label(
            info_frame,
            text="変更の反映には対象ディストロの再起動 (wsl --terminate) が必要です。",
            foreground="#555555",
        ).pack(anchor=tk.W)
        ttk.Label(
            info_frame,
            text="停止中のディストロは読み書きのために一時的に起動されます。",
            foreground="#555555",
        ).pack(anchor=tk.W)
        ttk.Label(
            info_frame,
            text="コメント行（# で始まる行）は保存時に保持されません。",
            foreground="#555555",
        ).pack(anchor=tk.W)

        ttk.Label(
            frame,
            text=f"編集対象: {self._distro} の /etc/wsl.conf",
            foreground="#777777",
        ).pack(anchor=tk.W, pady=(0, 8))

        ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(0, 10))

        form_frame = ttk.Frame(frame)
        form_frame.pack(fill=tk.X)

        self._field_vars: dict[tuple[str, str], tk.StringVar] = {}
        self._widgets: list[tuple[tk.Widget, str]] = []
        row_idx = 0
        current_section: str | None = None
        for section, key, label, widget_type, combo_values in self._FIELDS:
            if section != current_section:
                current_section = section
                ttk.Label(form_frame, text=f"[{section}]", font=("", 10, "bold")).grid(
                    row=row_idx,
                    column=0,
                    columnspan=2,
                    sticky=tk.W,
                    pady=(8 if row_idx else 0, 4),
                )
                row_idx += 1
            ttk.Label(form_frame, text=label, width=22, anchor=tk.W).grid(
                row=row_idx, column=0, sticky=tk.W, padx=(0, 8), pady=3
            )
            var = tk.StringVar(value="")
            self._field_vars[(section, key)] = var
            if widget_type == "combo" and combo_values is not None:
                widget: tk.Widget = ttk.Combobox(
                    form_frame,
                    textvariable=var,
                    values=combo_values,
                    width=22,
                    state="readonly",
                )
            else:
                widget = ttk.Entry(form_frame, textvariable=var, width=24)
            widget.grid(row=row_idx, column=1, sticky=tk.W, pady=3)
            self._widgets.append((widget, widget_type))
            row_idx += 1

        ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(12, 10))

        self._status_var = tk.StringVar(value="読み込み中…")
        ttk.Label(
            frame,
            textvariable=self._status_var,
            relief=tk.SUNKEN,
            anchor=tk.W,
            padding=(4, 2),
        ).pack(fill=tk.X, pady=(0, 10))

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X)
        self._save_btn = ttk.Button(btn_frame, text="保存", command=self._on_save, width=10)
        self._save_btn.pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(btn_frame, text="キャンセル", command=self._on_cancel, width=10).pack(
            side=tk.RIGHT
        )

    def _set_form_enabled(self, enabled: bool) -> None:
        """フォームの各ウィジェットの有効/無効を切り替えます。"""
        for widget, widget_type in self._widgets:
            try:
                if enabled:
                    widget.configure(state="readonly" if widget_type == "combo" else "normal")
                else:
                    widget.configure(state=tk.DISABLED)
            except tk.TclError:
                pass
        try:
            self._save_btn.configure(state=tk.NORMAL if enabled else tk.DISABLED)
        except tk.TclError:
            pass

    def _load_config(self) -> None:
        """/etc/wsl.conf をバックグラウンドスレッドで読み込みます。"""
        distro = self._distro

        def _run() -> tuple[bool, str]:
            try:
                result = subprocess.run(
                    ["wsl", "-d", distro, "-u", "root", "cat", "/etc/wsl.conf"],
                    capture_output=True,
                    creationflags=CREATE_NO_WINDOW,
                    timeout=20.0,
                )
            except subprocess.TimeoutExpired:
                return False, "タイムアウトしました。"
            except OSError as e:
                return False, str(e)
            if result.returncode != 0:
                # ファイルが存在しない場合なども含め、非0終了は空扱いにする
                return True, ""
            return True, wsl_core.decode_wsl_output(result.stdout)

        def _run_and_apply() -> None:
            ok, text_or_err = _run()
            self.after(0, lambda: self._on_loaded(ok, text_or_err))

        threading.Thread(target=_run_and_apply, daemon=True).start()

    def _on_loaded(self, ok: bool, text_or_err: str) -> None:
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        if not ok:
            messagebox.showerror(
                "読み込みエラー",
                f"「{self._distro}」の wsl.conf 読み込みに失敗しました:\n{text_or_err}",
                parent=self,
            )
            self.destroy()
            return
        try:
            self._sections = wsl_core.parse_wslconfig(text_or_err)
        except wsl_core.WslConfigParseError as e:
            messagebox.showerror(
                "パースエラー",
                f"「{self._distro}」の /etc/wsl.conf をパースできませんでした:\n{e}\n\n"
                "既存の設定を保護するため、ファイルを手動で修正してから再度開いてください。",
                parent=self,
            )
            self.destroy()
            return
        for (section, key), var in self._field_vars.items():
            var.set(self._sections.get(section, {}).get(key, ""))
        self._set_form_enabled(True)
        self._status_var.set("読み込み完了。")

    def _on_save(self) -> None:
        """フォームの内容を検証して /etc/wsl.conf に書き込みます。"""
        if self._busy:
            return
        for (section, key), var in self._field_vars.items():
            validator = self._VALIDATORS.get((section, key))
            if validator is None:
                continue
            val = var.get().strip()
            valid, reason = validator(val)
            if not valid:
                messagebox.showwarning("入力エラー", reason, parent=self)
                return

        # 既存セクション・キーを保持しつつ編集対象のキーだけ上書き/削除する
        new_sections: dict[str, dict[str, str]] = {s: dict(kv) for s, kv in self._sections.items()}
        for (section, key), var in self._field_vars.items():
            value = var.get().strip()
            sec = new_sections.setdefault(section, {})
            if value:
                sec[key] = value
            else:
                sec.pop(key, None)

        text = wsl_core.dump_wslconfig(new_sections)

        self._busy = True
        self._set_form_enabled(False)
        self._status_var.set("保存中…")
        distro = self._distro

        def _run() -> tuple[bool, str]:
            try:
                result = subprocess.run(
                    ["wsl", "-d", distro, "-u", "root", "sh", "-c", "cat > /etc/wsl.conf"],
                    input=text.encode("utf-8"),
                    capture_output=True,
                    creationflags=CREATE_NO_WINDOW,
                    timeout=20.0,
                )
            except subprocess.TimeoutExpired:
                return False, "タイムアウトしました。"
            except OSError as e:
                return False, str(e)
            if result.returncode != 0:
                err = wsl_core.decode_wsl_output(result.stderr).strip()
                return False, err or f"エラー (終了コード {result.returncode})"
            return True, ""

        def _run_and_apply() -> None:
            ok, err = _run()
            self.after(0, lambda: self._on_saved(ok, err, new_sections))

        threading.Thread(target=_run_and_apply, daemon=True).start()

    def _on_saved(self, ok: bool, err: str, new_sections: dict[str, dict[str, str]]) -> None:
        self._busy = False
        try:
            exists = self.winfo_exists()
        except tk.TclError:
            exists = False

        if not ok:
            self._log_operation_safe(f"保存失敗: {err}")
            if exists:
                self._set_form_enabled(True)
                self._status_var.set(f"保存に失敗しました: {err}")
                messagebox.showerror(
                    "保存エラー",
                    f"wsl.conf の書き込みに失敗しました:\n{err}",
                    parent=self,
                )
            return

        self._sections = new_sections
        self.result = True
        self._log_operation_safe("保存")

        if not exists:
            return

        restart = messagebox.askyesno(
            "保存しました",
            (
                f"「{self._distro}」の wsl.conf を保存しました。\n\n"
                "変更を反映するには対象ディストロの再起動 (wsl --terminate) が必要です。\n"
                "今すぐ再起動しますか？"
            ),
            parent=self,
        )
        if not restart:
            self.destroy()
            return

        self._status_var.set("再起動中…")
        distro = self._distro

        def _run_terminate() -> tuple[int, str]:
            try:
                result = subprocess.run(
                    ["wsl", "--terminate", distro],
                    capture_output=True,
                    creationflags=CREATE_NO_WINDOW,
                    timeout=20.0,
                )
            except subprocess.TimeoutExpired:
                return -1, "タイムアウトしました。"
            except OSError as e:
                return -1, str(e)
            return result.returncode, wsl_core.decode_wsl_output(result.stderr).strip()

        def _run_and_finish() -> None:
            rc, msg = _run_terminate()
            self.after(0, lambda: self._on_terminated(rc, msg))

        threading.Thread(target=_run_and_finish, daemon=True).start()

    def _on_terminated(self, rc: int, msg: str) -> None:
        self._log_operation_safe("再起動" if rc == 0 else f"再起動失敗: {msg or '不明なエラー'}")
        try:
            exists = self.winfo_exists()
        except tk.TclError:
            exists = False
        if rc != 0 and exists:
            messagebox.showwarning(
                "再起動エラー",
                f"「{self._distro}」の再起動に失敗しました:\n{msg or '不明なエラー'}",
                parent=self,
            )
        if exists:
            self.destroy()

    def _log_operation_safe(self, result: str) -> None:
        """親アプリの操作ログに記録します（親に _log_operation がない場合は無視）。"""
        log_fn = getattr(self._app, "_log_operation", None)
        if callable(log_fn):
            log_fn("ディストロ設定", self._distro, result)

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()


class DiskOptimizeDialog(tk.Toplevel):
    """WSL2 仮想ディスク (ext4.vhdx) の最適化ダイアログ。

    2 つの最適化手段を提供します。

    * スパース VHD 化 (``wsl --manage --set-sparse true``): 以降ディスクが
      自動的に縮小されるようにします。管理者権限は不要です。
    * diskpart による即時圧縮: 未使用領域を解放してファイルサイズを縮小します。
      対象ディストロを停止する必要があり、diskpart の ``compact`` には
      管理者権限が必要な場合があります。

    どちらの処理もバックグラウンドスレッドで実行し、UI をブロックしません。
    """

    def __init__(self, parent: tk.Tk, distro_name: str, vhdx_path: str) -> None:
        super().__init__(parent)
        self._distro = distro_name
        self._vhdx = vhdx_path
        self._busy = False
        self.title(
            wsl_core.translate(
                "gui.optimize.title",
                getattr(parent, "_language", wsl_core.LANGUAGE_AUTO),
                name=distro_name,
            )
        )
        self.resizable(False, False)
        self._build_ui()
        self._update_size()
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _current_size_gb(self) -> float | None:
        """現在の vhdx ファイルサイズ (GB) を返します。取得不可なら None。"""
        try:
            return os.path.getsize(self._vhdx) / (1024**3)
        except OSError:
            return None

    def _update_size(self) -> None:
        size = self._current_size_gb()
        self._size_var.set(f"{size:.2f} GB" if size is not None else "取得不可")

    def _build_ui(self) -> None:
        frame = ttk.Frame(self, padding=14)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame, text=f"ディストリビューション: {self._distro}", font=("", 10, "bold")
        ).pack(anchor=tk.W)
        ttk.Label(frame, text=f"仮想ディスク: {self._vhdx}", foreground="#777777").pack(
            anchor=tk.W, pady=(2, 8)
        )

        size_row = ttk.Frame(frame)
        size_row.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(size_row, text="現在のサイズ:").pack(side=tk.LEFT)
        self._size_var = tk.StringVar(value="…")
        ttk.Label(size_row, textvariable=self._size_var, font=("", 10, "bold")).pack(
            side=tk.LEFT, padx=(6, 0)
        )

        ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(0, 10))

        # スパース化
        ttk.Label(frame, text="スパース VHD 化（推奨）", font=("", 10, "bold")).pack(anchor=tk.W)
        ttk.Label(
            frame,
            text="有効化すると以降ディスクが自動的に縮小されます。管理者権限は不要です。",
            foreground="#555555",
            wraplength=440,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(0, 4))
        self._sparse_btn = ttk.Button(frame, text="スパース化を有効にする", command=self._do_sparse)
        self._sparse_btn.pack(anchor=tk.W, pady=(0, 10))

        ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(0, 10))

        # diskpart 圧縮
        ttk.Label(frame, text="今すぐ圧縮（diskpart）", font=("", 10, "bold")).pack(anchor=tk.W)
        ttk.Label(
            frame,
            text=(
                "未使用領域を解放してファイルを縮小します。対象ディストロを停止します。\n"
                "diskpart の実行には管理者権限が必要な場合があります。"
            ),
            foreground="#555555",
            wraplength=440,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(0, 4))
        self._compact_btn = ttk.Button(frame, text="今すぐ圧縮する", command=self._do_compact)
        self._compact_btn.pack(anchor=tk.W, pady=(0, 10))

        ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(0, 8))

        self._status_var = tk.StringVar(value="")
        ttk.Label(
            frame,
            textvariable=self._status_var,
            relief=tk.SUNKEN,
            anchor=tk.W,
            padding=(4, 2),
        ).pack(fill=tk.X)

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btn_row, text="閉じる", command=self._on_close, width=10).pack(side=tk.RIGHT)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = tk.DISABLED if busy else tk.NORMAL
        try:
            self._sparse_btn.configure(state=state)
            self._compact_btn.configure(state=state)
        except tk.TclError:
            pass

    def _set_status_safe(self, msg: str) -> None:
        try:
            if self.winfo_exists():
                self._status_var.set(msg)
        except tk.TclError:
            pass

    def _run_cmd(self, args: list[str], timeout: float = 60.0) -> tuple[int, str]:
        """コマンドを実行し (returncode, メッセージ) を返します。例外時は rc=-1。"""
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                creationflags=CREATE_NO_WINDOW,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return -1, "タイムアウトしました。"
        except OSError as e:
            return -1, str(e)
        msg = (
            wsl_core.decode_wsl_output(result.stderr).strip()
            or wsl_core.decode_wsl_output(result.stdout).strip()
        )
        return result.returncode, msg

    def _do_sparse(self) -> None:
        if self._busy:
            return
        if not messagebox.askyesno(
            "確認",
            f"「{self._distro}」のスパース VHD を有効化しますか？\n"
            "（対象ディストロは停止されます）",
            parent=self,
        ):
            return
        self._set_busy(True)
        self._set_status_safe("スパース化を実行中…")
        distro = self._distro

        def _run() -> None:
            # 対象ディストロを停止してから set-sparse を実行（停止失敗は無視）
            self._run_cmd(["wsl", "--terminate", distro])
            rc, err = self._run_cmd(["wsl", "--manage", distro, "--set-sparse", "true"])

            def _done() -> None:
                if rc == 0:
                    self._set_status_safe("スパース化を有効にしました。")
                    self._update_size()
                else:
                    self._set_status_safe(f"スパース化に失敗しました: {err or '不明なエラー'}")
                self._set_busy(False)

            self.after(0, _done)

        threading.Thread(target=_run, daemon=True).start()

    def _do_compact(self) -> None:
        if self._busy:
            return
        if not messagebox.askyesno(
            "確認",
            (
                f"「{self._distro}」の仮想ディスクを diskpart で圧縮しますか？\n\n"
                "・対象ディストロを停止します\n"
                "・数分かかることがあります\n"
                "・管理者権限が必要な場合があります"
            ),
            parent=self,
        ):
            return
        self._set_busy(True)
        self._set_status_safe("圧縮中…（数分かかる場合があります）")
        distro = self._distro
        vhdx = self._vhdx
        before = self._current_size_gb()

        def _run() -> None:
            # 対象ディストロを停止してファイルハンドルを解放
            self._run_cmd(["wsl", "--terminate", distro])
            script = wsl_core.build_diskpart_compact_script(vhdx)
            script_path: str | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    "w", suffix=".txt", delete=False, encoding="ascii", errors="replace"
                ) as tf:
                    tf.write(script)
                    script_path = tf.name
                rc, err = self._run_cmd(["diskpart", "/s", script_path], timeout=600.0)
            except OSError as e:
                rc, err = -1, str(e)
            finally:
                if script_path:
                    try:
                        os.remove(script_path)
                    except OSError:
                        pass

            def _done() -> None:
                if rc == 0:
                    after = self._current_size_gb()
                    if before is not None and after is not None:
                        saved = before - after
                        self._set_status_safe(
                            f"圧縮完了: {before:.2f} GB → {after:.2f} GB（{saved:.2f} GB 削減）"
                        )
                    else:
                        self._set_status_safe("圧縮が完了しました。")
                    self._update_size()
                else:
                    self._set_status_safe(
                        f"圧縮に失敗しました: {err or '不明なエラー'}"
                        "（管理者権限が必要な場合があります）"
                    )
                self._set_busy(False)

            self.after(0, _done)

        threading.Thread(target=_run, daemon=True).start()

    def _on_close(self) -> None:
        if self._busy and not messagebox.askyesno(
            "確認",
            "処理中です。閉じてもよろしいですか？\n（バックグラウンド処理は継続します）",
            parent=self,
        ):
            return
        self.destroy()


class DistroDetailDialog(tk.Toplevel):
    """ディストリビューションの詳細情報を表示するダイアログ。

    OS 情報 (/etc/os-release)、稼働時間 (uptime)、IP アドレス一覧、
    ディスク使用状況 (df) をバックグラウンドで取得して表示します。
    """

    def __init__(self, parent: tk.Tk, distro_name: str) -> None:
        super().__init__(parent)
        self._distro = distro_name
        self.title(
            wsl_core.translate(
                "gui.detail.title",
                getattr(parent, "_language", wsl_core.LANGUAGE_AUTO),
                name=distro_name,
            )
        )
        self.geometry("560x520")
        self.minsize(450, 400)
        self._build_ui()
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._fetch_all()

    def _build_ui(self) -> None:
        main = ttk.Frame(self, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text=self._distro, font=("", 13, "bold")).pack(anchor=tk.W, pady=(0, 8))

        # OS 情報セクション
        self._os_frame = self._section(main, "OS 情報")
        self._os_labels: dict[str, tk.StringVar] = {}
        for key, label in [
            ("PRETTY_NAME", "OS"),
            ("VERSION_ID", "バージョン"),
            ("ID", "ID"),
        ]:
            var = tk.StringVar(value="取得中…")
            self._os_labels[key] = var
            self._info_row(self._os_frame, label, var)

        self._uptime_var = tk.StringVar(value="取得中…")
        self._info_row(self._os_frame, "稼働時間", self._uptime_var)

        # ネットワークセクション
        net_frame = self._section(main, "ネットワーク")
        self._ip_var = tk.StringVar(value="取得中…")
        self._info_row(net_frame, "IPアドレス", self._ip_var)

        # ディスクセクション
        disk_frame = self._section(main, "ディスク使用量")
        self._vhdx_var = tk.StringVar(value="取得中…")
        self._info_row(disk_frame, "仮想ディスク", self._vhdx_var)

        # df テーブル
        df_tree_frame = ttk.Frame(disk_frame)
        df_tree_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        cols = ("filesystem", "size", "used", "avail", "use_pct", "mount")
        self._df_tree = ttk.Treeview(
            df_tree_frame,
            columns=cols,
            show="headings",
            selectmode="none",
            height=5,
        )
        for cid, text, w in [
            ("filesystem", "ファイルシステム", 130),
            ("size", "サイズ", 80),
            ("used", "使用", 80),
            ("avail", "空き", 80),
            ("use_pct", "使用率", 60),
            ("mount", "マウント先", 100),
        ]:
            self._df_tree.heading(cid, text=text)
            self._df_tree.column(
                cid,
                width=w,
                minwidth=50,
                anchor=tk.CENTER if cid != "filesystem" and cid != "mount" else tk.W,
            )
        vsb = ttk.Scrollbar(df_tree_frame, orient=tk.VERTICAL, command=self._df_tree.yview)
        self._df_tree.configure(yscrollcommand=vsb.set)
        self._df_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # ステータス
        self._status_var = tk.StringVar(value="情報を取得中…")
        ttk.Label(
            main,
            textvariable=self._status_var,
            relief=tk.SUNKEN,
            anchor=tk.W,
            padding=(4, 2),
        ).pack(fill=tk.X, pady=(8, 0))

        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(btn_frame, text="更新", command=self._fetch_all, width=8).pack(
            side=tk.RIGHT, padx=(4, 0)
        )
        ttk.Button(btn_frame, text="閉じる", command=self.destroy, width=8).pack(side=tk.RIGHT)

    @staticmethod
    def _section(parent: ttk.Frame, title: str) -> ttk.Frame:
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(6, 4))
        ttk.Label(parent, text=title, font=("", 10, "bold")).pack(anchor=tk.W, pady=(0, 2))
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.BOTH, expand=True, padx=(8, 0))
        return frame

    @staticmethod
    def _info_row(parent: ttk.Frame, label: str, var: tk.StringVar) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=1)
        ttk.Label(row, text=f"{label}:", width=14, anchor=tk.W).pack(side=tk.LEFT)
        ttk.Label(row, textvariable=var, anchor=tk.W).pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _fetch_all(self) -> None:
        self._status_var.set("情報を取得中…")
        distro = self._distro

        def _run() -> dict:
            data: dict = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                fut_os = pool.submit(self._cmd, distro, "cat /etc/os-release 2>/dev/null")
                fut_up = pool.submit(self._cmd, distro, "uptime -p 2>/dev/null || uptime")
                fut_ip = pool.submit(self._cmd, distro, "hostname -I 2>/dev/null")
                fut_df = pool.submit(self._cmd, distro, "df -B1 2>/dev/null || df -k")

                data["os"] = wsl_core.parse_os_release(fut_os.result())
                data["uptime"] = wsl_core.parse_uptime(fut_up.result())
                data["ips"] = wsl_core.parse_ip_addresses(fut_ip.result())
                data["df"] = wsl_core.parse_disk_usage(fut_df.result())

            vhdx = _get_distro_vhdx_path(distro)
            if vhdx:
                try:
                    size = os.path.getsize(vhdx) / (1024**3)
                    data["vhdx"] = f"{size:.2f} GB ({os.path.ba…18469 tokens truncated…            default_mark = "★" if d["default"] else ""
            state_jp = (
                self.STATE_JP.get(d["state"], d["state"]) if self._language == "ja" else d["state"]
            )
            version_str = f"WSL{d['version']}" if d["version"] else ""
            tag = "running" if d["state"] == "Running" else "stopped"
            iid = self._tree.insert(
                "",
                tk.END,
                values=(
                    default_mark,
                    d["name"],
                    state_jp,
                    version_str,
                    d["cpu"],
                    d["memory"],
                    d["disk"],
                    d.get("ip", "-"),
                ),
                tags=(tag,),
            )
            if d["name"] == selected:
                select_iid = iid

        # ソート状態を再適用
        self._sorter.apply()

        # 直前の選択を復元、なければ先頭を選択
        if select_iid:
            self._tree.selection_set(select_iid)
            self._tree.see(select_iid)
        elif self._tree.get_children():
            self._tree.selection_set(self._tree.get_children()[0])

    def _selected_name(self) -> str | None:
        sel = self._tree.selection()
        if not sel:
            return None
        values = self._tree.item(sel[0])["values"]
        return str(values[1]) if values else None

    def _set_status(self, msg: str) -> None:
        self._status_var.set(msg)

    def _check_log_writer_health(self) -> None:
        """#35: ログ書き込みのキュー溢れ/失敗を検知し、初回のみステータスバーに警告表示します。

        定期更新 (自動更新タイマー / 手動更新) のタイミングで呼び出す想定です。
        メインスレッドから ``self._log_writer`` のプロパティを読むだけなので、
        既存の GUI 更新パターン (メインスレッドから触る) を踏襲しています。
        """
        if self._log_writer_warning_shown:
            return
        dropped = self._log_writer.dropped_count
        write_errors = self._log_writer.write_error_count
        if dropped > 0 or write_errors > 0:
            self._log_writer_warning_shown = True
            self._set_status(
                "警告: 操作ログの書き込みに問題が発生しています"
                f"（キュー溢れによる破棄: {dropped} 件 / 書き込み失敗: {write_errors} 件）"
            )

    def _call_soon_safe(self, fn: callable) -> None:
        """バックグラウンドスレッドから UI 更新を安全にスケジュールします。

        長時間コマンドの実行中にウィンドウが閉じられると ``self`` は destroy
        済みになり、素の ``after(0, ...)`` は ``tk.TclError`` を送出します。
        スレッド内での例外は誰も捕まえないため、スケジュール時と実行時の
        両方をここでガードします。ウィンドウが既に無い場合は黙って捨てます。
        """

        def _guarded() -> None:
            try:
                if self.winfo_exists():
                    fn()
            except tk.TclError:
                pass

        try:
            self.after(0, _guarded)
        except (tk.TclError, RuntimeError):
            # destroy 済み、または mainloop 終了後にスケジュールしようとした場合
            pass

    def _set_status_safe(self, msg: str) -> None:
        """バックグラウンドスレッドからステータスバーを更新します。"""
        self._call_soon_safe(lambda: self._set_status(msg))

    # ── 操作ログ ─────────────────────────────────────────────────────────

    def _load_persisted_log(self) -> None:
        """ログファイルから過去の操作ログを読み込みます。"""
        try:
            if os.path.exists(self._log_file):
                with open(self._log_file, encoding="utf-8") as f:
                    entries = wsl_core.deserialize_log_entries(f.read())
                for entry in entries[-1000:]:
                    self._operation_log.append(wsl_core.format_log_entry_from_dict(entry))
        except OSError:
            pass

    def _persist_log_entry(self, operation: str, target: str, result: str) -> None:
        """操作ログ1件をファイルに追記します（実際の書き込みは別スレッド）。

        呼び出しはキューへの投入のみで完了するため、イベントループを
        ブロックしません。書き込み失敗は :class:`wsl_core.AsyncLogWriter`
        側で無視されます。
        """
        self._log_writer.submit(operation, target, result, source="gui")

    def _log_operation(self, operation: str, target: str, result: str) -> None:
        """操作ログにエントリを追加し、ファイルにも永続化します。

        Args:
            operation: 操作名（例: "停止"）。
            target: 操作対象（例: ディストリビューション名）。
            result: 結果（例: "実行"）。
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] {operation} | {target} | {result}"
        self._operation_log.append(entry)
        # 最大 1000 件を超えたら古いエントリを削除
        if len(self._operation_log) > 1000:
            self._operation_log = self._operation_log[-1000:]
        self._persist_log_entry(operation, target, result)

    def _show_log_viewer(self) -> None:
        """操作ログビューアーダイアログを開きます。"""
        dialog: LogViewerDialog | None = None

        def _clear() -> None:
            # キューに残った書き込みを先に片付けないと、削除直後に
            # 書き戻されて「消したログが復活する」ように見えてしまう
            self._log_writer.flush()
            _deleted, failed = wsl_core.delete_log_files(self._log_dir)
            self._operation_log.clear()
            if failed:
                messagebox.showwarning(
                    "警告",
                    "一部のログファイルを削除できませんでした。\n"
                    "他のプロセスが使用中の可能性があります:\n" + "\n".join(failed),
                    parent=dialog if dialog is not None else self,
                )

        dialog = LogViewerDialog(self, self._operation_log, _clear)

    # ── WSL コマンド実行 ──────────────────────────────────────────────────

    def _run_wsl_cmd(
        self,
        args: list[str],
        success_msg: str,
        error_msg: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        """WSL コマンドをバックグラウンドスレッドで実行し、完了後にリストを更新します。"""

        def _run() -> None:
            try:
                result = subprocess.run(
                    ["wsl", *args],
                    capture_output=True,
                    creationflags=CREATE_NO_WINDOW,
                    timeout=timeout,
                )
                if result.returncode == 0:
                    self._set_status_safe(success_msg)
                else:
                    stderr = wsl_core.decode_wsl_output(result.stderr).strip()
                    msg = error_msg or stderr or f"エラー (終了コード {result.returncode})"
                    self._set_status_safe(msg)
            except subprocess.TimeoutExpired:
                self._set_status_safe("WSL の応答がタイムアウトしました。")
            except OSError as e:
                self._set_status_safe(str(e))
            finally:
                self._call_soon_safe(self._refresh)

        threading.Thread(target=_run, daemon=True).start()

    # ── ボタンアクション ──────────────────────────────────────────────────

    def _start_distro(self) -> None:
        """選択したディストリビューションのターミナルを開きます（起動を兼ねます）。"""
        self._open_terminal()

    def _stop_distro(self) -> None:
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                self._t("gui.common.warning"), self._t("gui.msg.select_distro"), parent=self
            )
            return
        if not messagebox.askyesno(
            self._t("gui.common.confirm"), self._t("gui.confirm.stop", name=name), parent=self
        ):
            return
        self._log_operation("停止", name, "実行")
        status_msg = f"「{name}」を停止中…" if self._language == "ja" else f"Stopping '{name}'..."
        self._set_status(status_msg)
        ok_msg = f"「{name}」を停止しました。" if self._language == "ja" else f"Stopped '{name}'."
        err_msg = (
            f"「{name}」の停止に失敗しました。"
            if self._language == "ja"
            else f"Failed to stop '{name}'."
        )
        self._run_wsl_cmd(["--terminate", name], ok_msg, err_msg)

    def _shutdown_all(self) -> None:
        if not messagebox.askyesno(
            self._t("gui.common.confirm"), self._t("gui.confirm.shutdown"), parent=self
        ):
            return
        self._log_operation("全停止", "全ディストリビューション", "実行")
        status_msg = (
            "WSL を全停止中…" if self._language == "ja" else "Shutting down all distributions..."
        )
        self._set_status(status_msg)
        ok_msg = (
            "WSL を全停止しました。" if self._language == "ja" else "Shut down all distributions."
        )
        err_msg = (
            "WSL の全停止に失敗しました。"
            if self._language == "ja"
            else "Failed to shut down all distributions."
        )
        self._run_wsl_cmd(["--shutdown"], ok_msg, err_msg)

    def _set_default(self) -> None:
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                self._t("gui.common.warning"), self._t("gui.msg.select_distro"), parent=self
            )
            return
        self._log_operation("デフォルト設定", name, "実行")
        status_msg = (
            f"「{name}」をデフォルトに設定中…"
            if self._language == "ja"
            else f"Setting '{name}' as default..."
        )
        self._set_status(status_msg)
        self._run_wsl_cmd(
            ["--set-default", name],
            self._t("gui.msg.set_default_success", name=name),
            self._t("gui.msg.set_default_failed", error=""),
        )

    def _open_terminal(self) -> None:
        """選択したディストリビューションのターミナルウィンドウを開きます。

        Windows Terminal (wt.exe) が利用可能な場合はそちらを優先し、
        ない場合は cmd.exe にフォールバックします。
        """
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                self._t("gui.common.warning"), self._t("gui.msg.select_distro"), parent=self
            )
            return
        # wsl --list の出力から得た名前はこのアプリの作成時バリデーションを
        # 経由していない可能性がある (他ツールでの登録等)。cmd.exe/wt.exe の
        # コマンドラインインタプリタに渡す前に必ず再検証する。
        valid, reason = wsl_core.validate_distro_name(name)
        if not valid:
            messagebox.showerror(
                self._t("gui.common.error"),
                f"「{name}」はターミナル起動時に使用できない名前です: {reason}",
                parent=self,
            )
            return
        try:
            # Windows Terminal を優先
            subprocess.Popen(
                ["wt.exe", "wsl", "-d", name],
                creationflags=CREATE_NO_WINDOW,
            )
            self._log_operation("ターミナル起動", name, "Windows Terminal")
            self._set_status(f"「{name}」のターミナルを開きました (Windows Terminal)。")
            return
        except FileNotFoundError:
            pass
        except OSError:
            pass

        # cmd.exe にフォールバック
        try:
            subprocess.Popen(
                ["cmd.exe", "/k", "wsl", "-d", name],
                creationflags=CREATE_NEW_CONSOLE,
            )
            self._log_operation("ターミナル起動", name, "コマンド プロンプト")
            self._set_status(f"「{name}」のターミナルを開きました (コマンド プロンプト)。")
        except OSError as e:
            self._set_status(f"ターミナルを開けませんでした: {e}")

    def _on_tree_return(self, _event: object = None) -> None:
        """Treeview 上で Return キーが押されたときの処理。

        ダブルクリックと同じくターミナルを開くが、選択行が無い状態で
        Enter を押しても警告ダイアログは出さず、何もしない
        （空撃ちを無害な no-op にする）。
        """
        if not self._selected_name():
            return
        self._open_terminal()

    def _show_detail(self) -> None:
        """選択したディストリビューションの詳細情報ダイアログを開きます。"""
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                "警告", "ディストリビューションを選択してください。", parent=self
            )
            return
        DistroDetailDialog(self, name)

    def _show_processes(self) -> None:
        """選択したディストリビューションのプロセス一覧ウィンドウを開きます。"""
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                self._t("gui.common.warning"), self._t("gui.msg.select_distro"), parent=self
            )
            return

        sel = self._tree.selection()
        if sel:
            state_val = self._tree.item(sel[0])["values"][2]
            if state_val not in ("実行中", "Running"):
                messagebox.showwarning(
                    self._t("gui.common.warning"),
                    f"「{name}」は停止中です。起動してからプロセスを確認してください。"
                    if self._language == "ja"
                    else f"'{name}' is stopped. Please start it before checking processes.",
                    parent=self,
                )
                return

        self._process_windows = {k: v for k, v in self._process_windows.items() if v.winfo_exists()}

        existing = self._process_windows.get(name)
        if existing and existing.winfo_exists():
            existing.lift()
            existing.focus_set()
            return

        win = ProcessWindow(self, name)
        self._process_windows[name] = win

    def _clone_distro(self) -> None:
        """選択したディストリビューションを複製します（エクスポート→インポートを自動実行）。"""
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                "警告", "ディストリビューションを選択してください。", parent=self
            )
            return

        existing = [d["name"] for d in self._all_distros]
        version = next((str(d["version"]) for d in self._all_distros if d["name"] == name), "")

        new_name = simpledialog.askstring(
            "複製",
            "新しいディストリビューション名を入力してください。",
            initialvalue=wsl_core.default_clone_name(name, existing),
            parent=self,
        )
        if new_name is None:
            return
        new_name = new_name.strip()
        valid, reason = wsl_core.validate_clone_name(new_name, existing)
        if not valid:
            messagebox.showwarning("警告", reason, parent=self)
            return

        install_path = filedialog.askdirectory(title="複製先フォルダを選択")
        if not install_path:
            return

        if not messagebox.askyesno(
            "確認",
            (
                "次の内容で複製します。\n\n"
                f"複製元: {name}\n"
                f"複製先の名前: {new_name}\n"
                f"複製先フォルダ: {install_path}\n\n"
                "複製中は一時 tar ファイルが複製先フォルダに作成され、"
                "完了後に削除されます。"
            ),
            parent=self,
        ):
            return

        self._log_operation("複製", name, f"→ {new_name}")
        self._set_status(f"「{name}」を複製中… (1/2 エクスポート)")
        self._run_clone_cmd(name, new_name, install_path, version)

    def _run_clone_cmd(self, name: str, new_name: str, install_path: str, version: str) -> None:
        """複製処理（エクスポート→インポート）をバックグラウンドスレッドで実行します。"""

        def _run() -> None:
            try:
                fd, tmp_tar = tempfile.mkstemp(
                    prefix=f"{new_name}-clone-", suffix=".tar", dir=install_path
                )
                os.close(fd)
            except OSError as e:
                self._set_status_safe(str(e))
                return

            try:
                try:
                    export_result = subprocess.run(
                        ["wsl", "--export", name, tmp_tar],
                        capture_output=True,
                        creationflags=CREATE_NO_WINDOW,
                        timeout=3600,
                    )
                except subprocess.TimeoutExpired:
                    self._set_status_safe("複製処理がタイムアウトしました。")
                    return
                except OSError as e:
                    self._set_status_safe(str(e))
                    return

                if export_result.returncode != 0:
                    stderr = wsl_core.decode_wsl_output(export_result.stderr).strip()
                    msg = stderr or f"「{name}」のエクスポートに失敗しました。"
                    self._set_status_safe(msg)
                    return

                self._set_status_safe(f"「{name}」を複製中… (2/2 インポート)")

                import_args = ["wsl", "--import", new_name, install_path, tmp_tar]
                if version in ("1", "2"):
                    import_args += ["--version", version]

                try:
                    import_result = subprocess.run(
                        import_args,
                        capture_output=True,
                        creationflags=CREATE_NO_WINDOW,
                        timeout=3600,
                    )
                except subprocess.TimeoutExpired:
                    self._set_status_safe("複製処理がタイムアウトしました。")
                    return
                except OSError as e:
                    self._set_status_safe(str(e))
                    return

                if import_result.returncode != 0:
                    stderr = wsl_core.decode_wsl_output(import_result.stderr).strip()
                    msg = stderr or f"「{new_name}」のインポートに失敗しました。"
                    self._set_status_safe(msg)
                    return

                self._set_status_safe(f"「{name}」を「{new_name}」として複製しました。")
            finally:
                try:
                    os.remove(tmp_tar)
                except OSError:
                    pass
                self._call_soon_safe(self._refresh)

        threading.Thread(target=_run, daemon=True).start()

    def _export_distro_image(self) -> None:
        """選択したディストリビューションをエクスポートします（tar または VHD 形式）。"""
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                "警告", "ディストリビューションを選択してください。", parent=self
            )
            return

        use_vhd = messagebox.askyesno(
            "エクスポート形式",
            "VHD 形式でエクスポートしますか？\n「いいえ」を選ぶと tar 形式でエクスポートします。",
            parent=self,
        )

        if use_vhd:
            export_path = filedialog.asksaveasfilename(
                title="エクスポート先を選択",
                defaultextension=".vhdx",
                initialfile=f"{name}.vhdx",
                filetypes=[("VHDX image", "*.vhdx"), ("All files", "*.*")],
            )
        else:
            export_path = filedialog.asksaveasfilename(
                title="エクスポート先を選択",
                defaultextension=".tar",
                initialfile=f"{name}.tar",
                filetypes=[("Tar archive", "*.tar"), ("All files", "*.*")],
            )
        if not export_path:
            return

        if os.path.exists(export_path) and not messagebox.askyesno(
            "確認", f"既存ファイルを上書きしますか？\n{export_path}", parent=self
        ):
            return

        partial_path = wsl_core.partial_write_path(export_path)
        # 前回失敗して残った部分ファイルがあれば掃除する（wsl --export は既存ファイルを拒否する）
        wsl_core.discard_partial_write(partial_path)

        cmd_args = ["--export", name, partial_path]
        if use_vhd:
            cmd_args.append("--vhd")

        # 元 VHDX のサイズを進捗率の分母 (上限の目安) として使う
        total_bytes: int | None = None
        vhdx_path = _get_distro_vhdx_path(name)
        if vhdx_path:
            try:
                total_bytes = os.path.getsize(vhdx_path)
            except OSError:
                total_bytes = None

        self._log_operation("エクスポート", name, export_path)
        self._set_status(f"「{name}」をエクスポート中…")

        def _on_done(returncode: int, stderr_text: str, cancelled: bool) -> None:
            if cancelled:
                wsl_core.discard_partial_write(partial_path)
                self._log_operation("エクスポート", name, "キャンセル")
                self._set_status(f"「{name}」のエクスポートをキャンセルしました。")
            elif returncode == 0:
                if wsl_core.finalize_partial_write(partial_path, export_path):
                    self._set_status(f"「{name}」をエクスポートしました。")
                else:
                    wsl_core.discard_partial_write(partial_path)
                    self._set_status(
                        f"「{name}」のエクスポートに失敗しました（一時ファイルの移動に失敗）。"
                    )
            else:
                wsl_core.discard_partial_write(partial_path)
                self._set_status(stderr_text or f"「{name}」のエクスポートに失敗しました。")
            self._refresh()

        TransferProgressDialog(
            self,
            "エクスポート",
            f"「{name}」をエクスポート中…",
            cmd_args,
            partial_path,
            total_bytes,
            _on_done,
        )

    # ── スナップショット ─────────────────────────────────────────────────

    def _snapshot_dir(self) -> str:
        """スナップショットの保存先ディレクトリを返します（設定優先、未設定時はデフォルト）。"""
        return self._settings.get("snapshot_dir") or wsl_core.get_default_snapshot_dir()

    def _create_snapshot(self) -> None:
        """選択したディストリビューションのスナップショット (tar + メタデータ) を作成します。"""
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                "警告", "ディストリビューションを選択してください。", parent=self
            )
            return

        comment = simpledialog.askstring(
            "スナップショット作成",
            f"「{name}」のスナップショットを作成します。\nコメント (任意):",
            parent=self,
        )
        if comment is None:
            return

        snap_dir = self._snapshot_dir()
        try:
            os.makedirs(snap_dir, exist_ok=True)
        except OSError as e:
            messagebox.showerror("エラー", str(e), parent=self)
            return

        timestamp = time.strftime(wsl_core.SNAPSHOT_TIMESTAMP_FORMAT)
        created_at = datetime.now().isoformat(timespec="seconds")
        basename = wsl_core.build_snapshot_basename(name, timestamp)
        tar_path = os.path.join(snap_dir, basename + ".tar")
        json_path = os.path.join(snap_dir, basename + ".json")

        wsl_version = next((str(d["version"]) for d in self._all_distros if d["name"] == name), "2")

        # 元 VHDX のサイズを進捗率の分母 (上限の目安) として使う
        total_bytes: int | None = None
        vhdx_path = _get_distro_vhdx_path(name)
        if vhdx_path:
            try:
                total_bytes = os.path.getsize(vhdx_path)
            except OSError:
                total_bytes = None

        partial_tar = wsl_core.partial_write_path(tar_path)
        # 前回失敗して残った部分ファイルがあれば掃除する（wsl --export は既存ファイルを拒否する）
        wsl_core.discard_partial_write(partial_tar)

        self._log_operation("スナップショット作成", name, tar_path)
        self._set_status(f"「{name}」のスナップショットを作成中…")

        def _on_done(returncode: int, stderr_text: str, cancelled: bool) -> None:
            if cancelled:
                wsl_core.discard_partial_write(partial_tar)
                self._log_operation("スナップショット作成", name, "キャンセル")
                self._set_status(f"「{name}」のスナップショット作成をキャンセルしました。")
            elif returncode == 0:
                if not wsl_core.finalize_partial_write(partial_tar, tar_path):
                    wsl_core.discard_partial_write(partial_tar)
                    self._set_status(
                        f"「{name}」のスナップショット作成に失敗しました"
                        "（一時ファイルの移動に失敗）。"
                    )
                else:
                    try:
                        size = os.path.getsize(tar_path)
                    except OSError:
                        size = 0
                    metadata = wsl_core.build_snapshot_metadata(
                        name, wsl_version, comment, size, created_at, basename + ".tar"
                    )
                    if not wsl_core.write_snapshot_metadata(json_path, metadata):
                        self._set_status(
                            f"「{name}」のスナップショットを作成しましたが、"
                            "メタデータの保存に失敗しました。"
                        )
                    else:
                        self._set_status(f"「{name}」のスナップショットを作成しました。")
            else:
                wsl_core.discard_partial_write(partial_tar)
                self._set_status(stderr_text or f"「{name}」のスナップショット作成に失敗しました。")
            self._refresh()

        TransferProgressDialog(
            self,
            "スナップショット作成",
            f"「{name}」のスナップショットを作成中…",
            ["--export", name, partial_tar],
            partial_tar,
            total_bytes,
            _on_done,
        )

    def _open_snapshot_manager(self) -> None:
        """スナップショット管理ダイアログを開きます。"""
        SnapshotManagerDialog(self)

    def _open_container_manager(self) -> None:
        """Open the read-only WSL Containers management dialog."""
        ContainerManagerDialog(self)

    def _get_online_distros(self) -> tuple[list[str], str | None]:
        """``wsl --list --online`` からインストール可能なディストロ名を取得します。"""
        try:
            result = subprocess.run(
                ["wsl", "--list", "--online"],
                capture_output=True,
                creationflags=CREATE_NO_WINDOW,
                timeout=60.0,
            )
        except subprocess.TimeoutExpired:
            return [], "オンライン一覧の取得がタイムアウトしました。"
        except FileNotFoundError:
            return [], "wsl.exe が見つかりません。WSL2 がインストールされているか確認してください。"
        except OSError as e:
            return [], f"WSL の実行に失敗しました: {e}"

        if result.returncode != 0:
            stderr = wsl_core.decode_wsl_output(result.stderr).strip()
            return [], stderr or "インストール可能な一覧取得に失敗しました。"

        names = wsl_core.parse_online_distros(wsl_core.decode_wsl_output(result.stdout))
        return names, None

    def _install_distro(self) -> None:
        """公式配布ディストリビューションを個別インストールします。

        バックグラウンドで ``wsl --list --online`` を取得しつつ UI フリーズを防ぎます。
        取得完了後に :class:`InstallDialog` を表示します。
        """
        self._set_status("インストール可能な一覧を取得中…")

        def _fetch() -> None:
            candidates, err = self._get_online_distros()
            self._call_soon_safe(lambda: self._open_install_dialog(candidates, err))

        threading.Thread(target=_fetch, daemon=True).start()

    def _open_install_dialog(self, candidates: list[str], err: str | None) -> None:
        """``_install_distro`` のバックグラウンド取得完了後にダイアログを開きます。"""
        if err:
            self._set_status(err)

        dialog = InstallDialog(self, candidates)
        self.wait_window(dialog)

        name = dialog.result
        if name is None:
            self._set_status("インストールをキャンセルしました。")
            return

        if not messagebox.askyesno("確認", f"「{name}」をインストールしますか？", parent=self):
            return

        self._set_status(f"「{name}」をインストール中…")
        self._run_wsl_cmd(
            ["--install", "-d", name, "--no-launch"],
            f"「{name}」をインストールしました。初回起動時に初期セットアップ（ユーザー作成）が実行されます。",
            f"「{name}」のインストールに失敗しました。",
        )

    def _uninstall_distro(self) -> None:
        """選択したディストリビューションを個別アンインストールします。"""
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                self._t("gui.common.warning"), self._t("gui.msg.select_distro"), parent=self
            )
            return

        if not messagebox.askyesno(
            self._t("gui.common.confirm"),
            self._t("gui.confirm.unregister", name=name),
            parent=self,
        ):
            return

        confirm_name = simpledialog.askstring(
            self._t("gui.common.confirm"),
            (
                "誤操作防止のため、削除するディストリビューション名を\n"
                f"正確に入力してください: {name}"
                if self._language == "ja"
                else f"To prevent mistakes, please re-enter the exact distribution name:\n{name}"
            ),
            parent=self,
        )
        if confirm_name is None:
            return

        if confirm_name.strip() != name:
            messagebox.showwarning(
                self._t("gui.common.warning"),
                "入力された名前が一致しないため、アンインストールを中止しました。"
                if self._language == "ja"
                else "Uninstallation cancelled because the entered name did not match.",
                parent=self,
            )
            return

        self._log_operation("アンインストール", name, "実行")
        status_msg = (
            f"「{name}」をアンインストール中…"
            if self._language == "ja"
            else f"Unregistering '{name}'..."
        )
        self._set_status(status_msg)
        self._run_wsl_cmd(
            ["--unregister", name],
            self._t("gui.msg.unregister_success", name=name),
            self._t("gui.msg.unregister_failed", error=""),
        )

    def _import_distro_image(self) -> None:
        """tar/vhdx 形式のディストリビューションイメージをインポートします。"""
        distro_name = simpledialog.askstring(
            "インポート", "新しいディストリビューション名を入力してください。", parent=self
        )
        if distro_name is None:
            return
        distro_name = distro_name.strip()
        valid, reason = wsl_core.validate_distro_name(distro_name)
        if not valid:
            messagebox.showwarning("警告", reason, parent=self)
            return

        image_path = filedialog.askopenfilename(
            title="インポートするイメージを選択",
            filetypes=[
                ("WSL image files", "*.tar *.tar.gz *.tgz *.vhd *.vhdx"),
                ("All files", "*.*"),
            ],
        )
        if not image_path:
            return

        install_path = filedialog.askdirectory(title="インストール先フォルダを選択")
        if not install_path:
            return

        is_wsl2 = messagebox.askyesno(
            "WSL バージョン",
            "WSL2 としてインポートしますか？\n「いいえ」を選ぶと WSL1 としてインポートします。",
            parent=self,
        )
        version = "2" if is_wsl2 else "1"

        if not messagebox.askyesno(
            "確認",
            (
                "次の内容でインポートします。\n\n"
                f"名前: {distro_name}\n"
                f"イメージ: {image_path}\n"
                f"保存先: {install_path}\n"
                f"バージョン: WSL{version}"
            ),
            parent=self,
        ):
            return

        # 入力イメージのサイズを分母に、インストール先 ext4.vhdx の成長を監視する
        # (WSL1 は vhdx を使わないため経過時間のみの表示になる)
        total_bytes: int | None = None
        watch_path: str | None = None
        if version == "2":
            try:
                total_bytes = os.path.getsize(image_path)
            except OSError:
                total_bytes = None
            watch_path = os.path.join(install_path, "ext4.vhdx")

        self._log_operation("インポート", distro_name, image_path)
        self._set_status(f"「{distro_name}」をインポート中…")

        def _on_done(returncode: int, stderr_text: str, cancelled: bool) -> None:
            if cancelled:
                self._log_operation("インポート", distro_name, "キャンセル")
                self._set_status(f"「{distro_name}」のインポートをキャンセルしました。")
                if messagebox.askyesno(
                    "確認",
                    (
                        "インポートを中断したため、不完全な登録が残っている\n"
                        f"可能性があります。「{distro_name}」の登録を解除しますか？"
                    ),
                    parent=self,
                ):
                    self._run_wsl_cmd(
                        ["--unregister", distro_name],
                        f"「{distro_name}」の登録を解除しました。",
                        f"「{distro_name}」の登録解除に失敗しました。",
                    )
                    return
            elif returncode == 0:
                self._set_status(f"「{distro_name}」をインポートしました。")
            else:
                self._set_status(stderr_text or f"「{distro_name}」のインポートに失敗しました。")
            self._refresh()

        TransferProgressDialog(
            self,
            "インポート",
            f"「{distro_name}」をインポート中…",
            [
                "--import",
                distro_name,
                install_path,
                image_path,
                "--version",
                version,
            ],
            watch_path,
            total_bytes,
            _on_done,
        )

    def _open_wslconfig(self) -> None:
        """.wslconfig エディタダイアログを開きます。"""
        dialog = WslConfigDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            self._set_status(".wslconfig を保存しました。反映には全停止が必要です。")

    def _open_distro_conf(self) -> None:
        """選択したディストリビューションの wsl.conf エディタダイアログを開きます。"""
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                "警告", "ディストリビューションを選択してください。", parent=self
            )
            return
        dialog = DistroConfDialog(self, name)
        self.wait_window(dialog)
        if dialog.result:
            self._set_status(f"「{name}」の wsl.conf を保存しました。")
            self._refresh()

    def _show_context_menu(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        """右クリックでディストリビューション操作のコンテキストメニューを表示します。"""
        row = self._tree.identify_row(event.y)
        if not row:
            return
        self._tree.selection_set(row)
        self._tree.focus(row)

        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label=self._t("gui.context.terminal"), command=self._open_terminal)
        menu.add_command(label=self._t("gui.context.details"), command=self._show_detail)
        menu.add_command(label=self._t("gui.context.processes"), command=self._show_processes)
        menu.add_command(label=self._t("gui.context.explorer"), command=self._open_in_explorer)
        menu.add_command(label=self._t("gui.context.copy_ip"), command=self._copy_ip_address)
        menu.add_separator()
        menu.add_command(label=self._t("gui.context.stop"), command=self._stop_distro)
        menu.add_command(label=self._t("gui.context.set_default"), command=self._set_default)
        menu.add_command(label=self._t("gui.context.convert"), command=self._convert_version)
        menu.add_command(label=self._t("gui.context.optimize"), command=self._open_disk_optimize)
        menu.add_command(label=self._t("gui.context.distro_conf"), command=self._open_distro_conf)
        menu.add_separator()
        menu.add_command(label=self._t("gui.context.clone"), command=self._clone_distro)
        menu.add_command(label=self._t("gui.context.snapshot"), command=self._create_snapshot)
        menu.add_command(label=self._t("gui.context.export"), command=self._export_distro_image)
        menu.add_command(label=self._t("gui.context.unregister"), command=self._uninstall_distro)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _open_disk_optimize(self) -> None:
        """選択したディストリビューションのディスク最適化ダイアログを開きます。"""
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                "警告", "ディストリビューションを選択してください。", parent=self
            )
            return
        vhdx = _get_distro_vhdx_path(name)
        if not vhdx:
            messagebox.showinfo(
                "ディスク最適化",
                (
                    f"「{name}」の仮想ディスク (ext4.vhdx) が見つかりません。\n"
                    "WSL1 か、ディスク情報を取得できない構成の可能性があります。"
                ),
                parent=self,
            )
            return
        DiskOptimizeDialog(self, name, vhdx)

    def _open_in_explorer(self) -> None:
        """選択したディストリビューションのファイルシステムをエクスプローラーで開きます。"""
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                "警告", "ディストリビューションを選択してください。", parent=self
            )
            return
        try:
            subprocess.Popen(
                ["explorer.exe", f"\\\\wsl.localhost\\{name}"],
                creationflags=CREATE_NO_WINDOW,
            )
            self._set_status(f"「{name}」をエクスプローラーで開きました。")
        except OSError as e:
            self._set_status(f"エクスプローラーを開けませんでした: {e}")

    def _copy_ip_address(self) -> None:
        """選択したディストリビューションのIPアドレスをクリップボードにコピーします。"""
        sel = self._tree.selection()
        if not sel:
            return
        values = self._tree.item(sel[0])["values"]
        if not values or len(values) < 8:
            return
        ip = str(values[7])  # index 7 = ip column
        if ip and ip != "-":
            self.clipboard_clear()
            self.clipboard_append(ip)
            self._set_status(f"IPアドレスをコピーしました: {ip}")
        else:
            self._set_status("IPアドレスが取得できていません。")

    def _convert_version(self) -> None:
        """選択したディストリビューションの WSL バージョンを変換します(WSL1↔WSL2)。"""
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                self._t("gui.common.warning"), self._t("gui.msg.select_distro"), parent=self
            )
            return

        sel = self._tree.selection()
        current_version_str = ""
        if sel:
            values = self._tree.item(sel[0])["values"]
            if values and len(values) > 3:
                current_version_str = str(values[3])  # index 3: "WSL1" or "WSL2"

        if current_version_str == "WSL1":
            current = "1"
            target = "2"
        elif current_version_str == "WSL2":
            current = "2"
            target = "1"
        else:
            current = "?"
            target = "2"

        if current == "?":
            confirm_msg = self._t("gui.confirm.convert", name=name, target=target)
        else:
            if self._language == "ja":
                confirm_msg = (
                    f"「{name}」を WSL{current} から WSL{target} に変換しますか？\n"
                    "（変換には数分かかる場合があります）"
                )
            else:
                confirm_msg = (
                    f"Convert '{name}' from WSL{current} to WSL{target}?\n"
                    "(This conversion may take several minutes)"
                )

        if not messagebox.askyesno(self._t("gui.common.confirm"), confirm_msg, parent=self):
            return

        self._log_operation("バージョン変換", name, f"WSL{target}")
        status_msg = (
            f"「{name}」を WSL{target} に変換中…"
            if self._language == "ja"
            else f"Converting '{name}' to WSL{target}..."
        )
        self._set_status(status_msg)

        def _on_done(returncode: int, stderr_text: str, cancelled: bool) -> None:
            if cancelled:
                self._log_operation("バージョン変換", name, "キャンセル")
                self._set_status(
                    f"「{name}」の WSL バージョン変換を中断しました。"
                    if self._language == "ja"
                    else f"Cancelled WSL version conversion for '{name}'."
                )
            elif returncode == 0:
                self._set_status(self._t("gui.msg.convert_success", name=name, version=target))
            else:
                self._set_status(stderr_text or self._t("gui.msg.convert_failed", error=""))
            self._refresh()

        # ``--set-version`` は大きなディストリビューションで数分〜数十分かかるため
        # 固定タイムアウトの _run_wsl_cmd ではなく Popen ベースの進捗ダイアログを使う。
        # 進捗を監視できる出力ファイルは無いので watch_path は None（経過時間表示）。
        TransferProgressDialog(
            self,
            "WSL バージョン変換",
            f"「{name}」を WSL{target} に変換しています…",
            ["--set-version", name, target],
            None,
            None,
            _on_done,
            cancel_prompt=(
                "変換をキャンセルしますか？\n"
                "変換の中断はディストリビューションが不完全な状態で"
                "残る可能性があります。"
            ),
        )

    def _open_mount(self) -> None:
        """ディスクのマウントダイアログを開きます。"""
        WslMountDialog(self)

    def _open_unmount(self) -> None:
        """ディスクのアンマウントダイアログを開きます。"""
        WslUnmountDialog(self)

    def _execute_mount(self, disk: str, mount_args: list[str]) -> None:
        """ディスクのマウントコマンドを実行します。"""
        self._set_status(f"「{disk}」をマウント中…")

        def _run() -> None:
            res = wsl_core.run_wsl(mount_args, timeout=60.0, creationflags=CREATE_NO_WINDOW)

            def _done() -> None:
                if res.returncode == 0:
                    self._log_operation("マウント", disk, "成功")
                    self._set_status(f"「{disk}」をマウントしました。")
                    messagebox.showinfo(
                        "マウント完了", f"「{disk}」を正常にマウントしました。", parent=self
                    )
                else:
                    msg = res.stderr.strip() or "マウントに失敗しました。"
                    self._log_operation("マウント", disk, f"失敗: {msg}")
                    self._set_status(f"マウント失敗: {msg}")
                    messagebox.showerror(
                        "マウントエラー",
                        f"「{disk}」のマウントに失敗しました:\n{msg}\n\n"
                        "管理者権限が必要な場合があります。",
                        parent=self,
                    )

            self._call_soon_safe(_done)

        threading.Thread(target=_run, daemon=True).start()

    def _execute_unmount(self, disk: str | None, unmount_args: list[str]) -> None:
        """ディスクのアンマウントコマンドを実行します。"""
        target = disk or "すべてのマウントディスク"
        self._set_status(f"「{target}」をアンマウント中…")

        def _run() -> None:
            res = wsl_core.run_wsl(unmount_args, timeout=30.0, creationflags=CREATE_NO_WINDOW)

            def _done() -> None:
                if res.returncode == 0:
                    self._log_operation("アンマウント", target, "成功")
                    self._set_status(f"「{target}」をアンマウントしました。")
                    messagebox.showinfo(
                        "アンマウント完了",
                        f"「{target}」を正常にアンマウントしました。",
                        parent=self,
                    )
                else:
                    msg = res.stderr.strip() or "アンマウントに失敗しました。"
                    self._log_operation("アンマウント", target, f"失敗: {msg}")
                    self._set_status(f"アンマウント失敗: {msg}")
                    messagebox.showerror(
                        "アンマウントエラー",
                        f"「{target}」のアンマウントに失敗しました:\n{msg}\n\n"
                        "管理者権限が必要な場合があります。",
                        parent=self,
                    )

            self._call_soon_safe(_done)

        threading.Thread(target=_run, daemon=True).start()

    def _show_wsl_version(self) -> None:
        """WSL のバージョン情報を取得してダイアログに表示します。"""
        label_map = {
            "wsl": "WSL バージョン",
            "kernel": "カーネル バージョン",
            "wslg": "WSLg バージョン",
            "msrdc": "MSRDC バージョン",
            "direct3d": "Direct3D バージョン",
            "dxcore": "DXCore バージョン",
            "windows": "Windows バージョン",
        }

        def _run() -> None:
            try:
                result = subprocess.run(
                    ["wsl", "--version"],
                    capture_output=True,
                    creationflags=CREATE_NO_WINDOW,
                    timeout=10.0,
                )
                output = wsl_core.decode_wsl_output(result.stdout)
                info = wsl_core.parse_wsl_version(output)
            except Exception:
                info = {}

            def _show() -> None:
                lines = []
                for key, label in label_map.items():
                    value = info.get(key)
                    if value is not None:
                        lines.append(f"{label}: {value}")
                capability = wsl_core.wslc_capability(str(info.get("wsl", "")))
                lines.append("")
                lines.append(
                    "WSL Containers: Available"
                    if capability["available"]
                    else f"WSL Containers: {capability['reason']}"
                )
                unparsed = info.get("_unparsed_lines")
                if unparsed:
                    lines.append("")
                    lines.append("【その他の情報】")
                    lines.extend(unparsed)
                if not lines:
                    lines = ["WSL のバージョン情報を取得できませんでした。"]
                WslVersionDialog(self, lines, self._update_wsl)

            self._call_soon_safe(_show)

        threading.Thread(target=_run, daemon=True).start()

    def _update_wsl(self) -> None:
        """WSL 本体（wsl.exe / カーネル）の更新確認・実行フローを開始します。"""
        running_distros = [d["name"] for d in self._all_distros if d["state"] == "Running"]

        dialog = WslUpdateConfirmDialog(self, running_distros)
        self.wait_window(dialog)
        if dialog.result is None:
            return

        pre_release = bool(dialog.result.get("pre_release", False))
        self._run_wsl_update_cmd(pre_release)

    def _run_wsl_update_cmd(self, pre_release: bool) -> None:
        """``wsl --update`` をバックグラウンドスレッドで実行します。"""
        args = ["--update"]
        if pre_release:
            args.append("--pre-release")

        self._set_status("WSL を更新中…（数分かかる場合があります）")

        def _on_done(returncode: int, stderr_text: str, cancelled: bool) -> None:
            target = "wsl" + ("(--pre-release)" if pre_release else "")
            if cancelled:
                self._log_operation("WSL 更新", target, "キャンセル")
                self._set_status("WSL の更新をキャンセルしました。")
            elif returncode == 0:
                self._log_operation("WSL 更新", target, "成功")
                self._set_status("WSL の更新が完了しました。")
                messagebox.showinfo("WSL 更新", "WSL の更新が完了しました。", parent=self)
            else:
                msg = stderr_text or "WSL の更新に失敗しました。"
                self._log_operation("WSL 更新", target, f"失敗: {msg}")
                self._set_status(f"WSL 更新失敗: {msg}")
                messagebox.showerror("WSL 更新エラー", msg, parent=self)

        TransferProgressDialog(
            self,
            "WSL 更新",
            "WSL を更新しています…（数分かかる場合があります）",
            args,
            None,
            None,
            _on_done,
            cancel_prompt="WSL の更新をキャンセルしますか？",
        )

    def _show_about(self) -> None:
        """アプリケーション情報を表示します。"""
        messagebox.showinfo(
            "WSL Manager について",
            f"WSL Manager v{wsl_core.__version__}\n\n"
            "WSL2 ディストリビューション管理ツール\n"
            "Windows 10/11 + WSL2 環境用\n\n"
            "GitHub: https://github.com/kumakumapon/WSLManager",
            parent=self,
        )

    # ── 自動更新 ─────────────────────────────────────────────────────────

    def _toggle_auto_refresh(self) -> None:
        if self._auto_refresh_var.get():
            self._schedule_auto_refresh()
        else:
            if self._refresh_job:
                self.after_cancel(self._refresh_job)
                self._refresh_job = None
        self._save_settings()

    def _schedule_auto_refresh(self) -> None:
        self._refresh()
        self._refresh_job = self.after(5000, self._schedule_auto_refresh)

    # ── テーマ切り替え ────────────────────────────────────────────────────

    def _change_theme(self, theme_name: str) -> None:
        """ttk テーマを切り替えます。"""
        try:
            style = ttk.Style(self)
            style.theme_use(theme_name)
            self._current_theme = theme_name
            self._set_status(f"テーマを「{theme_name}」に変更しました。")
            self._save_settings()
        except tk.TclError:
            self._set_status(f"テーマ「{theme_name}」の適用に失敗しました。")

    def _change_language(self, language: str) -> None:
        """Persist a language preference for the next application launch."""
        self._settings["language"] = wsl_core.normalize_language(language)
        self._save_settings()
        self._set_status(self._t("gui.language_changed"))

    # ── 設定の保存 ───────────────────────────────────────────────────────

    def _save_settings(self) -> None:
        """現在の UI 状態を設定ファイルに保存します。失敗しても例外は投げません。"""
        sort_col, sort_desc = self._sorter.get_state()
        settings = {
            "theme": self._current_theme,
            "auto_refresh": self._auto_refresh_var.get(),
            "window_geometry": self.geometry(),
            "sort_column": sort_col,
            "sort_desc": sort_desc,
            "snapshot_dir": self._settings.get("snapshot_dir"),
            "language": self._settings.get("language", wsl_core.LANGUAGE_AUTO),
        }
        wsl_core.save_settings(self._settings_path, settings)

    # ── ウィンドウ終了 ────────────────────────────────────────────────────

    def on_closing(self) -> None:
        # 実行中のエクスポート/インポート等があれば、確認の上でプロセスを
        # 終了させてから閉じる (#26: 放置すると wsl.exe が孤児化する)。
        live_transfers = [d for d in self._transfer_dialogs if d.winfo_exists()]
        if live_transfers:
            if not messagebox.askyesno(
                "確認",
                f"実行中の処理が {len(live_transfers)} 件あります。中断して終了しますか？\n"
                "中断すると、処理中だったファイルが不完全な状態で残る場合があります。",
                parent=self,
            ):
                return
            for dialog in live_transfers:
                # 1件の force_cancel が予期せぬ例外を送出しても、他のダイアログの
                # 終了処理とアプリの終了処理自体は続行する。
                try:
                    dialog.force_cancel()
                except OSError:
                    pass
        if self._refresh_job:
            self.after_cancel(self._refresh_job)
        self._save_settings()
        # キューに残った操作ログを書き終えてからライタスレッドを終了させる
        self._log_writer.stop()
        self.destroy()


# ── エントリポイント ──────────────────────────────────────────────────────────


def main() -> None:
    if sys.platform != "win32":
        # Windows 以外では起動できない旨を伝えて終了
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "エラー",
            "WSL Manager は Windows 環境でのみ動作します。\nWindows 10/11 上で実行してください。",
            parent=root,
        )
        root.destroy()
        sys.exit(1)

    # 高DPI 対応
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    # 多重起動防止 (Named Mutex)
    try:
        import ctypes

        mutex_name = "Global\\WSLManager_SingleInstance_Mutex"
        ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
        if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            hwnd = ctypes.windll.user32.FindWindowW(None, "WSL Manager")
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                ctypes.windll.user32.SetForegroundWindow(hwnd)
            sys.exit(0)
    except Exception:
        pass

    app = WSLManager()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()


if __name__ == "__main__":
    main()
