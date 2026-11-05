"""
WSL Manager - WSL ディストリビューション管理ツール (GUI)

WSL ディストリビューションの起動・停止・バックアップ・設定を 1 画面で行う
tkinter アプリケーションです。Windows 10/11 + WSL 環境での使用を前提としています。

画面構成:
    - ツールバー: よく使う操作 (起動・停止・ターミナル・追加・更新) と検索
    - 一覧: インストール済みディストリビューション (列クリックで並べ替え)
    - 詳細パネル: 選択中のディストリビューションの情報と、すべての操作ボタン
    - ステータスバー: 処理中の表示、結果メッセージ、件数、最終更新時刻

操作は選択中のディストリビューションの状態に応じて有効/無効が切り替わります
(:func:`wsl_core.action_availability`)。破壊的な操作は従来どおり確認を経由します。
"""

from __future__ import annotations

import functools
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from collections.abc import Callable
from datetime import datetime
from tkinter import messagebox, simpledialog, ttk
from typing import Literal

import wsl_core
from wslmgr_gui import resources, ui_queue
from wslmgr_gui.app.operation_log import OperationLogMixin
from wslmgr_gui.app.resource_history import ResourceHistoryMixin
from wslmgr_gui.app.settings import SettingsMixin
from wslmgr_gui.detail_panel import DetailPanel
from wslmgr_gui.dialogs.containers import ContainerManagerDialog
from wslmgr_gui.dialogs.disk_optimize import DiskOptimizeDialog
from wslmgr_gui.dialogs.distro_conf import DistroConfDialog
from wslmgr_gui.dialogs.distro_detail import DistroDetailDialog
from wslmgr_gui.dialogs.forms import CloneDialog, ExportDialog, ImportDialog
from wslmgr_gui.dialogs.install import InstallDialog
from wslmgr_gui.dialogs.mount import WslMountDialog, WslUnmountDialog
from wslmgr_gui.dialogs.process import ProcessWindow
from wslmgr_gui.dialogs.snapshot import SnapshotManagerDialog
from wslmgr_gui.dialogs.transfer import TransferProgressDialog
from wslmgr_gui.dialogs.wsl_config import WslConfigDialog
from wslmgr_gui.dialogs.wsl_update import WslUpdateConfirmDialog
from wslmgr_gui.dialogs.wsl_version import WslVersionDialog
from wslmgr_gui.distro_data import get_distros
from wslmgr_gui.style import apply_styles, configure_tree_tags
from wslmgr_gui.widgets import TreeviewSorter
from wslmgr_gui.winutil import (
    CREATE_NEW_CONSOLE,
    CREATE_NO_WINDOW,
    _get_distro_vhdx_path,
)

PROJECT_URL = "https://github.com/kumakumapon/WSLManager"

# 一覧の列 (ID, 翻訳キー, 幅, 最小幅, 配置)
_Anchor = Literal["w", "center", "e"]
_COLUMNS: tuple[tuple[str, str, int, int, _Anchor], ...] = (
    ("default", "gui.column.default", 64, 44, tk.CENTER),
    ("name", "gui.column.name", 200, 120, tk.W),
    ("state", "gui.column.state", 96, 80, tk.W),
    ("version", "gui.column.version", 70, 60, tk.CENTER),
    ("cpu", "gui.column.cpu", 70, 56, tk.E),
    ("memory", "gui.column.memory", 96, 76, tk.E),
    ("disk", "gui.column.disk", 96, 76, tk.E),
    ("ip", "gui.column.ip", 130, 96, tk.W),
)


def _warn_no_selection(app: WSLManager) -> None:
    """ディストリビューションが選択されていないことを知らせます。"""
    messagebox.showwarning(
        app._t("gui.common.warning"), app._t("gui.msg.select_distro"), parent=app
    )


def _file_size(path: str | None) -> int | None:
    if not path:
        return None
    try:
        return os.path.getsize(path)
    except OSError:
        return None


class WSLManager(OperationLogMixin, ResourceHistoryMixin, SettingsMixin, tk.Tk):
    """WSL ディストリビューション管理メインウィンドウ。"""

    DEFAULT_GEOMETRY = "1100x680"
    MIN_SIZE = (860, 540)

    def __init__(self) -> None:
        super().__init__()
        self.title("WSL Manager")
        self.geometry(self.DEFAULT_GEOMETRY)
        self.minsize(*self.MIN_SIZE)
        # ワーカースレッドからの画面更新はすべてこのキューを経由させる
        self._ui_queue = ui_queue.install(self)

        self._refresh_job: str | None = None
        self._refresh_in_progress = False
        self._refresh_pending = False
        self._refresh_error: str | None = None
        self._loaded_once = False
        self._last_refresh: datetime | None = None
        self._busy_count = 0
        self._process_windows: dict[str, ProcessWindow] = {}
        self._transfer_dialogs: list[TransferProgressDialog] = []
        self._all_distros: list[dict] = []
        self._resource_history = wsl_core.ResourceHistory()
        self._resource_history_visible = False
        self._history_layouts: dict[str, wsl_core.ChartLayout] = {}
        self._operation_log: list[str] = []
        self._log_dir = wsl_core.get_default_log_dir()
        self._log_file = os.path.join(self._log_dir, "operations.jsonl")
        # ログ書き込みは Tk のイベントループを塞がないよう専用スレッドに委譲する
        self._log_writer = wsl_core.AsyncLogWriter(self._log_dir)
        # #35: ログ書き込みキューの溢れ/書き込み失敗を一度だけステータスバーに通知するためのフラグ
        self._log_writer_warning_shown = False
        self._load_persisted_log()
        self._settings_path = wsl_core.get_default_settings_path()
        self._settings = wsl_core.load_settings(self._settings_path)
        self._language = wsl_core.resolve_language(self._settings["language"])
        self._auto_refresh_ms = int(self._settings["auto_refresh_interval"]) * 1000
        if self._settings["window_geometry"]:
            try:
                self.geometry(self._settings["window_geometry"])
            except tk.TclError:
                pass

        # 画面を作り直しても (言語切替) 値を保つ変数
        self._filter_var = tk.StringVar()
        self._auto_refresh_var = tk.BooleanVar(value=self._settings["auto_refresh"])
        self._detail_visible_var = tk.BooleanVar(value=self._settings["detail_panel"])
        self._history_visible_var = tk.BooleanVar(value=False)
        self._interval_var = tk.IntVar(value=self._settings["auto_refresh_interval"])
        self._language_var = tk.StringVar(value=self._settings["language"])

        self._apply_window_icon()
        self._setup_theme()
        self._reapply_styles()
        self._build_ui()
        self._bind_shortcuts()
        self._filter_var.trace_add("write", lambda *_: self._render_distros())
        if self._settings["auto_refresh"]:
            self._schedule_auto_refresh()
        else:
            self._refresh()

    # ── 初期化 ─────────────────────────────────────────────────────────────

    def _t(self, key: str, **values: object) -> str:
        """Translate text used by the main application shell."""
        return wsl_core.translate(key, self._language, **values)

    def _apply_window_icon(self) -> None:
        """ウィンドウ (とタスクバー) のアイコンを設定します。見つからなければ既定のまま。"""
        ico = resources.resource_path("assets", "wslmanager.ico")
        png = resources.resource_path("assets", "wslmanager.png")
        if sys.platform == "win32" and os.path.exists(ico):
            try:
                # default= を付けると、以降に開くダイアログにも同じアイコンが付く
                self.iconbitmap(default=ico)
                return
            except tk.TclError:
                pass  # ICO を読めない Tk では PNG で設定する
        if os.path.exists(png):
            try:
                self._icon_image = tk.PhotoImage(file=png)
                self.iconphoto(True, self._icon_image)
            except tk.TclError:
                pass

    def _setup_theme(self) -> None:
        """利用可能な ttk テーマを検出し、保存済みのテーマがあれば適用します。"""
        style = ttk.Style(self)
        self._available_themes = sorted(style.theme_names())
        self._current_theme = style.theme_use()
        saved_theme = self._settings["theme"]
        if saved_theme and saved_theme in self._available_themes:
            try:
                style.theme_use(saved_theme)
                self._current_theme = saved_theme
            except tk.TclError:
                pass
        self._theme_var = tk.StringVar(value=self._current_theme)

    def _reapply_styles(self) -> None:
        """名前付きスタイルを (テーマ変更後にも) 登録し直します。"""
        self._fonts = apply_styles(self)
        tree = getattr(self, "_tree", None)
        if tree is not None:
            configure_tree_tags(tree)

    # ── UI 構築 ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._main_frame = ttk.Frame(self, padding=(8, 6, 8, 4))
        self._main_frame.pack(fill=tk.BOTH, expand=True)

        self._menu_items: list[tuple[tk.Menu, int, str]] = []
        self._toolbar_buttons: dict[str, ttk.Button] = {}
        self._build_menubar()
        self._build_toolbar(self._main_frame)
        self._build_statusbar(self._main_frame)
        self._build_body(self._main_frame)
        self._build_resource_history_panel(self._list_frame)
        if self._resource_history_visible:
            self._set_resource_history_visible(True)
        self._apply_detail_visibility()
        self._update_action_states()

    def _rebuild_ui(self) -> None:
        """表示言語の切り替え後に、メニュー・ツールバー・一覧・パネルを作り直します。

        選択行・並べ替え・検索語・パネルの表示状態は引き継ぎます。
        """
        selected = self._selected_name()
        sort_state = self._sorter.get_state()
        old_menubar = self._menubar
        self._main_frame.destroy()
        self._build_ui()
        old_menubar.destroy()
        self._sorter.set_state(*sort_state)
        self._render_distros(selected)
        self._draw_resource_history()
        self._show_last_refresh()

    def _add_menu_command(
        self,
        menu: tk.Menu,
        label_key: str,
        command: Callable[[], None],
        accelerator: str | None = None,
        action: str | None = None,
    ) -> None:
        """メニュー項目を追加します。``action`` を渡すと選択状態で有効/無効が切り替わります。"""
        options: dict[str, object] = {"label": self._t(label_key), "command": command}
        if accelerator:
            options["accelerator"] = accelerator
        menu.add_command(**options)  # type: ignore[arg-type]
        if action is not None:
            index = menu.index(tk.END)
            if index is not None:
                self._menu_items.append((menu, int(index), action))

    def _build_menubar(self) -> None:
        """メニューバーを構築してウィンドウに設定します。"""
        menubar = tk.Menu(self)
        add = self._add_menu_command

        # ── ファイル ──
        file_menu = tk.Menu(menubar, tearoff=0)
        add(file_menu, "gui.action.install", self._install_distro, "Ctrl+N")
        add(file_menu, "gui.action.import", self._import_distro_image, "Ctrl+I")
        add(file_menu, "gui.action.snapshots", self._open_snapshot_manager)
        file_menu.add_separator()
        add(file_menu, "gui.action.exit", self.on_closing, "Alt+F4")
        menubar.add_cascade(label=self._t("gui.menu.file"), menu=file_menu)

        # ── ディストリビューション (選択中の 1 件に対する操作) ──
        distro_menu = tk.Menu(menubar, tearoff=0)
        add(distro_menu, "gui.action.start_terminal", self._open_terminal, "Enter", "terminal")
        add(distro_menu, "gui.action.start", self._start_distro, "Ctrl+Shift+S", "start")
        add(distro_menu, "gui.action.stop", self._stop_distro, "Delete", "stop")
        add(distro_menu, "gui.action.explorer", self._open_in_explorer, None, "explorer")
        add(distro_menu, "gui.action.copy_ip", self._copy_ip_address, None, "copy_ip")
        distro_menu.add_separator()
        add(distro_menu, "gui.action.snapshot", self._create_snapshot, "Ctrl+S", "snapshot")
        add(distro_menu, "gui.action.export", self._export_distro_image, "Ctrl+E", "export")
        add(distro_menu, "gui.action.clone", self._clone_distro, None, "clone")
        distro_menu.add_separator()
        add(distro_menu, "gui.action.set_default", self._set_default, None, "set_default")
        add(distro_menu, "gui.action.convert", self._convert_version, None, "convert")
        add(distro_menu, "gui.action.distro_conf", self._open_distro_conf, None, "distro_conf")
        add(distro_menu, "gui.action.optimize", self._open_disk_optimize, None, "optimize")
        distro_menu.add_separator()
        add(distro_menu, "gui.action.details", self._show_detail, "Ctrl+D", "details")
        add(distro_menu, "gui.action.processes", self._show_processes, "Ctrl+P", "processes")
        distro_menu.add_separator()
        add(distro_menu, "gui.action.unregister", self._uninstall_distro, None, "unregister")
        menubar.add_cascade(label=self._t("gui.menu.distribution"), menu=distro_menu)

        # ── WSL (全体に対する操作) ──
        wsl_menu = tk.Menu(menubar, tearoff=0)
        add(wsl_menu, "gui.action.shutdown", self._shutdown_all, "Ctrl+Shift+Q")
        wsl_menu.add_separator()
        add(wsl_menu, "gui.action.wsl_config", self._open_wslconfig, "Ctrl+,")
        add(wsl_menu, "gui.action.mount", self._open_mount)
        add(wsl_menu, "gui.action.unmount", self._open_unmount)
        add(wsl_menu, "gui.action.containers", self._open_container_manager)
        wsl_menu.add_separator()
        add(wsl_menu, "gui.action.wsl_version", self._show_wsl_version)
        add(wsl_menu, "gui.action.update_wsl", self._update_wsl)
        menubar.add_cascade(label=self._t("gui.menu.wsl"), menu=wsl_menu)

        # ── 表示 ──
        view_menu = tk.Menu(menubar, tearoff=0)
        add(view_menu, "gui.action.refresh", self._refresh, "F5")
        view_menu.add_checkbutton(
            label=self._t("gui.view.detail_panel"),
            variable=self._detail_visible_var,
            command=self._toggle_detail_panel,
        )
        view_menu.add_checkbutton(
            label=self._t("gui.view.history"),
            variable=self._history_visible_var,
            command=lambda: self._set_resource_history_visible(self._history_visible_var.get()),
        )
        view_menu.add_separator()
        view_menu.add_checkbutton(
            label=self._t("gui.auto_refresh"),
            variable=self._auto_refresh_var,
            command=self._toggle_auto_refresh,
        )
        interval_menu = tk.Menu(view_menu, tearoff=0)
        for seconds in wsl_core.AUTO_REFRESH_INTERVALS:
            interval_menu.add_radiobutton(
                label=self._t("gui.view.interval_seconds", seconds=seconds),
                variable=self._interval_var,
                value=seconds,
                command=functools.partial(self._set_auto_refresh_interval, seconds),
            )
        view_menu.add_cascade(label=self._t("gui.view.interval"), menu=interval_menu)
        view_menu.add_separator()
        theme_menu = tk.Menu(view_menu, tearoff=0)
        self._theme_var.set(self._current_theme)
        for theme_name in self._available_themes:
            theme_menu.add_radiobutton(
                label=theme_name,
                variable=self._theme_var,
                value=theme_name,
                command=functools.partial(self._change_theme, theme_name),
            )
        view_menu.add_cascade(label=self._t("gui.action.theme"), menu=theme_menu)
        language_menu = tk.Menu(view_menu, tearoff=0)
        self._language_var.set(self._settings["language"])
        for language in (wsl_core.LANGUAGE_AUTO, *wsl_core.SUPPORTED_LANGUAGES):
            language_menu.add_radiobutton(
                label=self._t(f"language.{language}"),
                variable=self._language_var,
                value=language,
                command=functools.partial(self._change_language, language),
            )
        view_menu.add_cascade(label=self._t("gui.menu.language"), menu=language_menu)
        view_menu.add_separator()
        add(view_menu, "gui.action.log", self._show_log_viewer, "Ctrl+L")
        menubar.add_cascade(label=self._t("gui.menu.view"), menu=view_menu)

        # ── ヘルプ ──
        help_menu = tk.Menu(menubar, tearoff=0)
        add(help_menu, "gui.action.shortcuts", self._show_shortcuts, "F1")
        add(help_menu, "gui.action.cli_help", self._show_cli_help)
        add(help_menu, "gui.action.project_page", self._open_project_page)
        help_menu.add_separator()
        add(help_menu, "gui.action.about", self._show_about)
        menubar.add_cascade(label=self._t("gui.menu.help"), menu=help_menu)

        self.config(menu=menubar)
        self._menubar = menubar

    def _bind_shortcuts(self) -> None:
        """メイン画面のキーボードショートカット。

        ルートウィンドウ (``self``) にバインドするので、別ウィンドウのダイアログで
        キーを押しても反応しない (以前は ``bind_all`` で、ダイアログ内の Delete キーでも
        メイン画面のディストリビューションが停止されかけた)。
        """

        def _key(handler: Callable[[], None]) -> Callable[[tk.Event], str]:  # type: ignore[type-arg]
            def _on_key(_event: tk.Event) -> str:  # type: ignore[type-arg]
                handler()
                return "break"

            return _on_key

        bindings: dict[str, Callable[[], None]] = {
            "<F5>": self._refresh,
            "<Control-r>": self._refresh,
            "<Control-n>": self._install_distro,
            "<Control-i>": self._import_distro_image,
            "<Control-e>": self._export_distro_image,
            "<Control-s>": self._create_snapshot,
            "<Control-d>": self._show_detail,
            "<Control-p>": self._show_processes,
            "<Control-comma>": self._open_wslconfig,
            "<Control-l>": self._show_log_viewer,
            "<Control-f>": self._focus_search,
            "<Control-Shift-S>": self._start_distro,
            "<Control-Shift-Q>": self._shutdown_all,
            "<F1>": self._show_shortcuts,
        }
        for sequence, handler in bindings.items():
            self.bind(sequence, _key(handler))

    def _build_toolbar(self, parent: ttk.Frame) -> None:
        """よく使う操作を 1 行に並べたツールバー (右端に検索)。"""
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill=tk.X, pady=(0, 6))

        def _button(action: str, label_key: str, command: Callable[[], None]) -> None:
            button = ttk.Button(
                toolbar, text=self._t(label_key), command=command, style="Toolbar.TButton"
            )
            button.pack(side=tk.LEFT, padx=(0, 4))
            self._toolbar_buttons[action] = button

        _button("start", "gui.toolbar.start", self._start_distro)
        _button("stop", "gui.toolbar.stop", self._stop_distro)
        _button("terminal", "gui.toolbar.terminal", self._open_terminal)
        _button("explorer", "gui.toolbar.explorer", self._open_in_explorer)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=2)

        add_button = ttk.Menubutton(
            toolbar, text=self._t("gui.toolbar.add"), style="Toolbar.TButton"
        )
        add_menu = tk.Menu(add_button, tearoff=0)
        add_menu.add_command(label=self._t("gui.action.install"), command=self._install_distro)
        add_menu.add_command(label=self._t("gui.action.import"), command=self._import_distro_image)
        add_button.configure(menu=add_menu)
        add_button.pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(
            toolbar,
            text=self._t("gui.toolbar.snapshots"),
            command=self._open_snapshot_manager,
            style="Toolbar.TButton",
        ).pack(side=tk.LEFT, padx=(0, 4))

        ttk.Button(
            toolbar,
            text=self._t("gui.toolbar.refresh"),
            command=self._refresh,
            style="Toolbar.TButton",
        ).pack(side=tk.RIGHT)
        clear = ttk.Button(toolbar, text="×", width=2, command=lambda: self._filter_var.set(""))
        clear.pack(side=tk.RIGHT, padx=(2, 8))
        self._search_entry = ttk.Entry(toolbar, textvariable=self._filter_var, width=22)
        self._search_entry.pack(side=tk.RIGHT)
        self._search_entry.bind("<Escape>", lambda _e: self._filter_var.set(""))
        self._search_entry.bind("<Down>", lambda _e: self._focus_tree())
        ttk.Label(toolbar, text=self._t("gui.toolbar.search")).pack(side=tk.RIGHT, padx=(0, 4))

    def _build_body(self, parent: ttk.Frame) -> None:
        """一覧 (左) と詳細パネル (右) を分割ペインに並べます。"""
        self._paned = ttk.Panedwindow(parent, orient=tk.HORIZONTAL)
        self._paned.pack(fill=tk.BOTH, expand=True)

        self._list_frame = ttk.Frame(self._paned)
        self._build_treeview(self._list_frame)
        self._paned.add(self._list_frame, weight=1)

        commands: dict[str, Callable[[], None]] = {
            "terminal": self._open_terminal,
            "start": self._start_distro,
            "stop": self._stop_distro,
            "explorer": self._open_in_explorer,
            "processes": self._show_processes,
            "copy_ip": self._copy_ip_address,
            "snapshot": self._create_snapshot,
            "export": self._export_distro_image,
            "clone": self._clone_distro,
            "set_default": self._set_default,
            "convert": self._convert_version,
            "distro_conf": self._open_distro_conf,
            "optimize": self._open_disk_optimize,
            "details": self._show_detail,
            "unregister": self._uninstall_distro,
        }
        self._detail_panel = DetailPanel(self._paned, self._t, commands)

    def _build_treeview(self, parent: ttk.Frame) -> None:
        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        # リソース履歴パネルはこの一覧の下に差し込む (ResourceHistoryMixin)
        self._history_anchor = tree_frame

        cols = tuple(column[0] for column in _COLUMNS)
        self._tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")
        for col_id, key, width, minwidth, anchor in _COLUMNS:
            self._tree.heading(col_id, text=self._t(key), anchor=anchor)
            self._tree.column(
                col_id,
                width=width,
                minwidth=minwidth,
                anchor=anchor,
                stretch=col_id in ("name", "ip"),
            )

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self._tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        # ダブルクリック / Enter でターミナルを開く。Delete で停止 (確認あり)。
        # フィルタ入力欄で誤発火しないよう、Treeview に直接バインドする。
        self._tree.bind("<Double-1>", self._on_tree_double_click)
        self._tree.bind("<Return>", self._on_tree_return)
        self._tree.bind("<Delete>", lambda _e: self._stop_distro())
        self._tree.bind("<Button-3>", self._show_context_menu)
        self._tree.bind("<Shift-F10>", self._show_context_menu_for_selection)
        # アプリケーションキーの keysym は Windows では App、X11 では Menu
        for keysym in ("<App>", "<Menu>"):
            try:
                self._tree.bind(keysym, self._show_context_menu_for_selection)
            except tk.TclError:
                pass
        self._tree.bind("<<TreeviewSelect>>", lambda _e: self._on_selection_changed())

        configure_tree_tags(self._tree)

        self._sorter = TreeviewSorter(
            self._tree, numeric_columns={"cpu", "memory", "disk"}, on_sorted=self._apply_stripes
        )
        self._sorter.set_state(self._settings["sort_column"], self._settings["sort_desc"])

        # 一覧が空のとき・取得に失敗したときに一覧の上へ重ねる案内
        self._empty_frame = ttk.Frame(tree_frame, padding=20)
        self._empty_title = ttk.Label(self._empty_frame, style="Empty.TLabel", justify=tk.CENTER)
        self._empty_title.pack()
        self._empty_detail = ttk.Label(
            self._empty_frame, style="Muted.TLabel", justify=tk.CENTER, wraplength=460
        )
        self._empty_detail.pack(pady=(6, 10))
        self._empty_buttons = ttk.Frame(self._empty_frame)
        self._empty_buttons.pack()

    def _build_statusbar(self, parent: ttk.Frame) -> None:
        self._statusbar = ttk.Frame(parent)
        self._statusbar.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0))
        ttk.Separator(self._statusbar, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(0, 3))

        self._busy_bar = ttk.Progressbar(self._statusbar, mode="indeterminate", length=90)
        self._status_var = tk.StringVar(value=self._t("gui.status.ready"))
        self._status_label = ttk.Label(self._statusbar, textvariable=self._status_var, anchor=tk.W)
        self._status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._updated_var = tk.StringVar(value="")
        ttk.Label(self._statusbar, textvariable=self._updated_var, style="Muted.TLabel").pack(
            side=tk.RIGHT
        )
        self._summary_var = tk.StringVar(value="")
        ttk.Label(self._statusbar, textvariable=self._summary_var).pack(side=tk.RIGHT, padx=12)
        if self._busy_count > 0:
            self._show_busy_bar()

    # ── 詳細パネル ─────────────────────────────────────────────────────────

    def _apply_detail_visibility(self) -> None:
        panes = self._paned.panes()
        visible = str(self._detail_panel) in [str(p) for p in panes]
        if self._detail_visible_var.get() and not visible:
            self._paned.add(self._detail_panel, weight=0)
        elif not self._detail_visible_var.get() and visible:
            self._paned.forget(self._detail_panel)

    def _toggle_detail_panel(self) -> None:
        self._apply_detail_visibility()
        self._settings["detail_panel"] = bool(self._detail_visible_var.get())
        self._save_settings()

    # ── 選択と操作の有効/無効 ───────────────────────────────────────────────

    def _selected_name(self) -> str | None:
        sel = self._tree.selection()
        return str(sel[0]) if sel else None

    def _distro_by_name(self, name: str | None) -> dict | None:
        if name is None:
            return None
        return next((d for d in self._all_distros if d["name"] == name), None)

    def _selected_distro(self) -> dict | None:
        """選択中のディストリビューション (一覧取得時の dict)。未選択なら None。"""
        return self._distro_by_name(self._selected_name())

    def _on_selection_changed(self) -> None:
        self._update_action_states()

    def _update_action_states(self) -> None:
        """選択中のディストリビューションに合わせて、ボタン・メニューの有効/無効を更新します。"""
        distro = self._selected_distro()
        availability = wsl_core.action_availability(distro)
        for action, button in self._toolbar_buttons.items():
            button.state(["!disabled"] if availability.get(action) else ["disabled"])
        for menu, index, action in self._menu_items:
            try:
                menu.entryconfigure(
                    index, state=tk.NORMAL if availability.get(action) else tk.DISABLED
                )
            except tk.TclError:
                pass
        self._detail_panel.show(distro, availability)

    def _focus_search(self) -> None:
        self._search_entry.focus_set()
        self._search_entry.select_range(0, tk.END)

    def _focus_tree(self) -> None:
        self._tree.focus_set()
        children = self._tree.get_children()
        if children and not self._tree.selection():
            self._tree.selection_set(children[0])
        if self._tree.selection():
            self._tree.focus(self._tree.selection()[0])

    # ── ツリービュー更新 ──────────────────────────────────────────────────

    def _refresh(self) -> None:
        if self._refresh_in_progress:
            self._refresh_pending = True
            return

        selected = self._selected_name()
        self._refresh_in_progress = True
        self._updated_var.set(self._t("gui.status.refreshing"))
        if not self._loaded_once:
            self._show_empty_state()

        language = self._language

        def _run() -> None:
            distros, err = get_distros(language)
            self._call_soon_safe(lambda: self._apply_refresh_result(distros, err, selected))

        threading.Thread(target=_run, daemon=True).start()

    def _apply_refresh_result(
        self, distros: list[dict], err: str | None, selected: str | None
    ) -> None:
        self._refresh_in_progress = False
        self._loaded_once = True
        if err and self._all_distros and self._refresh_error is None:
            # 取得済みの一覧は残し、失敗はステータスバーで知らせる。一時的なタイムアウトで
            # 一覧が消えて、すべての操作が使えなくなるのを避ける。
            self._set_status(self._t("gui.status.refresh_failed", error=err))
        elif err:
            self._refresh_error = err
            self._all_distros = []
            self._set_status(self._t("gui.status.refresh_failed", error=err))
            self._updated_var.set("")
        else:
            self._refresh_error = None
            self._all_distros = distros
            self._resource_history.record_refresh(distros)
            self._last_refresh = datetime.now()
            self._show_last_refresh()
        self._render_distros(selected)
        self._draw_resource_history()

        if self._refresh_pending:
            self._refresh_pending = False
            self._refresh()
        self._check_log_writer_health()

    def _render_distros(self, selected: str | None = None) -> None:
        """フィルタを適用してツリービューを再描画します。

        ``self._all_distros`` のみを参照し、subprocess 等の重い処理は行いません。
        フィルタ入力のたびに呼ばれるため、軽量に保つこと。
        """
        if selected is None:
            selected = self._selected_name()

        self._tree.delete(*self._tree.get_children())
        filter_text = self._filter_var.get().strip().casefold()
        running_label = "● " + self._t("gui.state.running")
        stopped_label = "○ " + self._t("gui.state.stopped")

        for d in self._all_distros:
            if filter_text and filter_text not in d["name"].casefold():
                continue
            running = d["state"] == "Running"
            if d["state"] in ("Running", "Stopped"):
                state_text = running_label if running else stopped_label
            else:  # Installing / Converting など
                state_text = "◌ " + str(d["state"])
            self._tree.insert(
                "",
                tk.END,
                iid=d["name"],
                values=(
                    "★" if d["default"] else "",
                    d["name"],
                    state_text,
                    f"WSL{d['version']}" if d["version"] else "",
                    d["cpu"],
                    d["memory"],
                    d["disk"],
                    d.get("ip", "-"),
                ),
                tags=("running" if running else "stopped",),
            )

        self._sorter.apply()  # 並べ替えたときは on_sorted で縞模様も付け直す
        self._apply_stripes()

        children = self._tree.get_children()
        if selected and self._tree.exists(selected):
            self._tree.selection_set(selected)
            self._tree.see(selected)
        elif children:
            self._tree.selection_set(children[0])
        self._update_empty_state(bool(children))
        self._update_summary()
        self._update_action_states()

    def _apply_stripes(self) -> None:
        """並べ替え後の表示順で、1 行おきに背景色を付けます。"""
        for index, iid in enumerate(self._tree.get_children()):
            tags = [t for t in self._tree.item(iid, "tags") if t != "stripe"]
            if index % 2 == 1:
                tags.append("stripe")
            self._tree.item(iid, tags=tags)

    def _show_last_refresh(self) -> None:
        if self._last_refresh is None or self._refresh_error:
            self._updated_var.set("")
            return
        self._updated_var.set(
            self._t("gui.status.updated_at", time=self._last_refresh.strftime("%H:%M:%S"))
        )

    def _update_summary(self) -> None:
        if not self._loaded_once or self._refresh_error:
            self._summary_var.set("")
            return
        count = len(self._all_distros)
        running = sum(1 for d in self._all_distros if d["state"] == "Running")
        summary = self._t("gui.status.summary", count=count, running=running)
        filter_text = self._filter_var.get().strip()
        if filter_text:
            shown = len(self._tree.get_children())
            summary += "  " + self._t("gui.status.filtered", shown=shown)
        self._summary_var.set(summary)

    # ── 空の一覧の案内 ─────────────────────────────────────────────────────

    def _show_empty_state(self) -> None:
        self._update_empty_state(False)

    def _update_empty_state(self, has_rows: bool) -> None:
        """一覧が空のときに、理由と次に取れる操作を一覧の上に表示します。"""
        if has_rows:
            self._empty_frame.place_forget()
            return
        for child in self._empty_buttons.winfo_children():
            child.destroy()
        if not self._loaded_once:
            title, detail, buttons = self._t("gui.empty.loading"), "", []
        elif self._refresh_error:
            title = self._t("gui.empty.error_title")
            detail = self._refresh_error + "\n\n" + self._t("gui.empty.error_hint")
            buttons = [("gui.empty.retry", self._refresh)]
        elif self._all_distros:  # フィルタで 0 件
            title = self._t("gui.empty.no_match", text=self._filter_var.get().strip())
            detail = ""
            buttons = [("gui.empty.clear_filter", lambda: self._filter_var.set(""))]
        else:
            title = self._t("gui.empty.none_title")
            detail = self._t("gui.empty.none_hint")
            buttons = [
                ("gui.action.install", self._install_distro),
                ("gui.action.import", self._import_distro_image),
            ]
        self._empty_title.configure(text=title)
        self._empty_detail.configure(text=detail)
        if detail:
            self._empty_detail.pack(pady=(6, 10), before=self._empty_buttons)
        else:
            self._empty_detail.pack_forget()
        for key, command in buttons:
            ttk.Button(self._empty_buttons, text=self._t(key), command=command).pack(
                side=tk.LEFT, padx=4
            )
        self._empty_frame.place(relx=0.5, rely=0.4, anchor=tk.CENTER)
        self._empty_frame.lift()

    # ── ステータス・処理中表示 ─────────────────────────────────────────────

    def _set_status(self, msg: str) -> None:
        self._status_var.set(msg)

    def _show_busy_bar(self) -> None:
        self._busy_bar.pack(side=tk.LEFT, padx=(0, 8), before=self._status_label)
        self._busy_bar.start(15)

    def _begin_busy(self) -> None:
        """時間のかかる処理の開始を記録し、ステータスバーに処理中の表示を出します。"""
        self._busy_count += 1
        if self._busy_count == 1:
            self._show_busy_bar()

    def _end_busy(self) -> None:
        self._busy_count = max(0, self._busy_count - 1)
        if self._busy_count == 0:
            self._busy_bar.stop()
            self._busy_bar.pack_forget()

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
                self._t("gui.status.log_warning", dropped=dropped, errors=write_errors)
            )

    def _call_soon_safe(self, fn: Callable[[], None]) -> None:
        """バックグラウンドスレッドから UI 更新を安全にスケジュールします。

        実際の実行はメインスレッドが :mod:`wslmgr_gui.ui_queue` のキューから取り出して
        行います。ウィンドウが既に閉じられていれば黙って捨てます。
        """
        ui_queue.post_to_ui(self, fn)

    def _set_status_safe(self, msg: str) -> None:
        """バックグラウンドスレッドからステータスバーを更新します。"""
        self._call_soon_safe(lambda: self._set_status(msg))

    def _show_error(self, message: str, detail: str = "") -> None:
        """失敗をステータスバーとエラーダイアログの両方で知らせます (見落とし防止)。"""
        self._set_status(message if not detail else f"{message} {detail}")
        text = message if not detail else f"{message}\n\n{detail}"
        messagebox.showerror(self._t("gui.common.error"), text, parent=self)

    # ── WSL コマンド実行 ──────────────────────────────────────────────────

    def _run_wsl_cmd(
        self,
        args: list[str],
        success_msg: str,
        error_msg: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        """WSL コマンドをバックグラウンドスレッドで実行し、完了後にリストを更新します。

        失敗した場合はエラーダイアログでも知らせます。
        """
        self._begin_busy()

        def _run() -> None:
            ok = False
            detail = ""
            try:
                result = subprocess.run(
                    ["wsl", *args],
                    capture_output=True,
                    creationflags=CREATE_NO_WINDOW,
                    timeout=timeout,
                )
                ok = result.returncode == 0
                if not ok:
                    # wsl.exe はエラーを標準出力に書くことがある
                    detail = (
                        wsl_core.decode_wsl_output(result.stderr).strip()
                        or wsl_core.decode_wsl_output(result.stdout).strip()
                        or self._t("gui.msg.exit_code", code=result.returncode)
                    )
            except subprocess.TimeoutExpired:
                detail = self._t("gui.msg.timeout")
            except OSError as e:
                detail = str(e)

            def _done() -> None:
                self._end_busy()
                if ok:
                    self._set_status(success_msg)
                else:
                    self._show_error(error_msg or self._t("gui.msg.command_failed"), detail)
                self._refresh()

            self._call_soon_safe(_done)

        threading.Thread(target=_run, daemon=True).start()

    # ── 起動・停止・ターミナル ───────────────────────────────────────────

    def _start_distro(self) -> None:
        """選択したディストリビューションをバックグラウンドで起動します (画面は開きません)。"""
        distro = self._selected_distro()
        if distro is None:
            _warn_no_selection(self)
            return
        name = distro["name"]
        if distro.get("state") == "Running":
            self._set_status(self._t("gui.msg.already_running", name=name))
            return
        self._log_operation("起動", name, "実行")
        self._set_status(self._t("gui.msg.starting", name=name))
        self._run_wsl_cmd(
            ["-d", name, "--", "true"],
            self._t("gui.msg.started", name=name),
            self._t("gui.msg.start_failed", name=name),
            timeout=120.0,
        )

    def _stop_distro(self) -> None:
        distro = self._selected_distro()
        if distro is None:
            _warn_no_selection(self)
            return
        name = distro["name"]
        if not messagebox.askyesno(
            self._t("gui.common.confirm"), self._t("gui.confirm.stop", name=name), parent=self
        ):
            return
        self._log_operation("停止", name, "実行")
        self._set_status(self._t("gui.msg.stopping", name=name))
        self._run_wsl_cmd(
            ["--terminate", name],
            self._t("gui.msg.stopped", name=name),
            self._t("gui.msg.stop_failed", name=name),
        )

    def _shutdown_all(self) -> None:
        if not messagebox.askyesno(
            self._t("gui.common.confirm"), self._t("gui.confirm.shutdown"), parent=self
        ):
            return
        self._log_operation("全停止", "全ディストリビューション", "実行")
        self._set_status(self._t("gui.msg.shutting_down"))
        self._run_wsl_cmd(
            ["--shutdown"],
            self._t("gui.msg.shutdown_done"),
            self._t("gui.msg.shutdown_failed"),
        )

    def _set_default(self) -> None:
        distro = self._selected_distro()
        if distro is None:
            _warn_no_selection(self)
            return
        name = distro["name"]
        self._log_operation("デフォルト設定", name, "実行")
        self._set_status(self._t("gui.msg.setting_default", name=name))
        self._run_wsl_cmd(
            ["--set-default", name],
            self._t("gui.msg.set_default_success", name=name),
            self._t("gui.msg.set_default_failed", name=name),
        )

    def _open_terminal(self) -> None:
        """選択したディストリビューションのターミナルウィンドウを開きます。

        Windows Terminal (wt.exe) が利用可能な場合はそちらを優先し、
        ない場合は cmd.exe にフォールバックします。
        """
        distro = self._selected_distro()
        if distro is None:
            _warn_no_selection(self)
            return
        name = distro["name"]
        # wsl --list の出力から得た名前はこのアプリの作成時バリデーションを
        # 経由していない可能性がある (他ツールでの登録等)。cmd.exe/wt.exe の
        # コマンドラインインタプリタに渡す前に必ず再検証する。
        valid, reason = wsl_core.validate_distro_name(name, language=self._language)
        if not valid:
            messagebox.showerror(
                self._t("gui.common.error"),
                self._t("gui.msg.terminal_bad_name", name=name, reason=reason),
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
            self._set_status(self._t("gui.msg.terminal_opened", name=name, app="Windows Terminal"))
            self._refresh_soon()
            return
        except OSError:
            pass

        # cmd.exe にフォールバック
        try:
            subprocess.Popen(
                ["cmd.exe", "/k", "wsl", "-d", name],
                creationflags=CREATE_NEW_CONSOLE,
            )
            self._log_operation("ターミナル起動", name, "コマンド プロンプト")
            self._set_status(self._t("gui.msg.terminal_opened", name=name, app="cmd.exe"))
            self._refresh_soon()
        except OSError as e:
            self._show_error(self._t("gui.msg.terminal_failed"), str(e))

    def _refresh_soon(self, delay_ms: int = 2500) -> None:
        """ターミナル起動直後など、少し待ってから状態を取り直します (起動を一覧へ反映)。"""
        try:
            self.after(delay_ms, self._refresh)
        except tk.TclError:
            pass

    def _on_tree_return(self, _event: object = None) -> str | None:
        """Treeview 上で Return キーが押されたときの処理。

        ダブルクリックと同じくターミナルを開くが、選択行が無い状態で
        Enter を押しても警告ダイアログは出さず、何もしない
        （空撃ちを無害な no-op にする）。
        """
        if not self._selected_name():
            return None
        self._open_terminal()
        return "break"

    def _on_tree_double_click(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        """行の上でのダブルクリックだけをターミナル起動にします (見出しのクリックは除く)。"""
        if self._tree.identify_region(event.x, event.y) not in ("cell", "tree"):
            return
        if self._tree.identify_row(event.y):
            self._open_terminal()

    def _show_detail(self) -> None:
        """選択したディストリビューションの詳細情報ダイアログを開きます。"""
        distro = self._selected_distro()
        if distro is None:
            _warn_no_selection(self)
            return
        DistroDetailDialog(self, distro["name"])

    def _show_processes(self) -> None:
        """選択したディストリビューションのプロセス一覧ウィンドウを開きます。"""
        distro = self._selected_distro()
        if distro is None:
            _warn_no_selection(self)
            return
        name = distro["name"]
        if distro.get("state") != "Running":
            messagebox.showwarning(
                self._t("gui.common.warning"),
                self._t("gui.msg.processes_need_running", name=name),
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

    # ── 複製・エクスポート・インポート ─────────────────────────────────────

    def _existing_names(self) -> list[str]:
        return [d["name"] for d in self._all_distros]

    def _clone_distro(self) -> None:
        """選択したディストリビューションを複製します（エクスポート→インポートを自動実行）。"""
        distro = self._selected_distro()
        if distro is None:
            _warn_no_selection(self)
            return
        name = distro["name"]
        version = str(distro.get("version") or "")

        request = CloneDialog.ask(self, name, self._existing_names())
        if request is None:
            return
        # フォームで検証済みだが、コマンドラインに渡す前にもう一度確かめる
        valid, reason = wsl_core.validate_clone_name(
            request.name, self._existing_names(), language=self._language
        )
        if not valid:
            messagebox.showwarning(self._t("gui.common.warning"), reason, parent=self)
            return

        if not messagebox.askyesno(
            self._t("gui.common.confirm"),
            self._t(
                "gui.confirm.clone", name=name, new_name=request.name, folder=request.install_dir
            ),
            parent=self,
        ):
            return

        self._log_operation("複製", name, f"→ {request.name}")
        self._run_clone_cmd(name, request.name, request.install_dir, version)

    def _run_clone_cmd(self, name: str, new_name: str, install_path: str, version: str) -> None:
        """複製 (エクスポート→インポート) を進捗ダイアログ付きで順に実行します。

        一時 tar は複製先フォルダに作り、成功・失敗・キャンセルのいずれでも削除します。
        """
        try:
            os.makedirs(install_path, exist_ok=True)
        except OSError as e:
            self._show_error(self._t("gui.msg.folder_failed", path=install_path), str(e))
            return
        stamp = time.strftime("%Y%m%d-%H%M%S")
        tmp_tar = os.path.join(install_path, f"{new_name}-clone-{stamp}.tar")

        def _cleanup() -> None:
            wsl_core.discard_partial_write(tmp_tar)

        def _after_import(returncode: int, stderr_text: str, cancelled: bool) -> None:
            _cleanup()
            if cancelled:
                self._log_operation("複製", name, "キャンセル")
                self._set_status(self._t("gui.msg.clone_cancelled", name=name))
                self._offer_unregister_partial(new_name)
                return
            if returncode == 0:
                self._set_status(self._t("gui.msg.clone_done", name=name, new_name=new_name))
            else:
                self._show_error(self._t("gui.msg.import_failed", name=new_name), stderr_text)
            self._refresh()

        def _after_export(returncode: int, stderr_text: str, cancelled: bool) -> None:
            if cancelled or returncode != 0:
                _cleanup()
                if cancelled:
                    self._log_operation("複製", name, "キャンセル")
                    self._set_status(self._t("gui.msg.clone_cancelled", name=name))
                else:
                    self._show_error(self._t("gui.msg.export_failed", name=name), stderr_text)
                self._refresh()
                return
            self._set_status(self._t("gui.msg.clone_step", name=name, step="2/2"))
            TransferProgressDialog(
                self,
                self._t("gui.transfer.clone_title"),
                self._t("gui.transfer.clone_import", name=new_name),
                wsl_core.build_import_args(new_name, install_path, tmp_tar, version),
                os.path.join(install_path, "ext4.vhdx") if version != "1" else None,
                _file_size(tmp_tar),
                _after_import,
            )

        self._set_status(self._t("gui.msg.clone_step", name=name, step="1/2"))
        TransferProgressDialog(
            self,
            self._t("gui.transfer.clone_title"),
            self._t("gui.transfer.clone_export", name=name),
            ["--export", name, tmp_tar],
            tmp_tar,
            _file_size(_get_distro_vhdx_path(name)),
            _after_export,
        )

    def _offer_unregister_partial(self, distro_name: str) -> None:
        """中断したインポートで不完全な登録が残っていれば、登録解除を提案します。"""
        if messagebox.askyesno(
            self._t("gui.common.confirm"),
            self._t("gui.confirm.unregister_partial", name=distro_name),
            parent=self,
        ):
            self._run_wsl_cmd(
                ["--unregister", distro_name],
                self._t("gui.msg.unregister_success", name=distro_name),
                self._t("gui.msg.unregister_failed", name=distro_name),
            )
        else:
            self._refresh()

    def _export_distro_image(self) -> None:
        """選択したディストリビューションをエクスポートします（tar または VHD 形式）。"""
        distro = self._selected_distro()
        if distro is None:
            _warn_no_selection(self)
            return
        name = distro["name"]

        request = ExportDialog.ask(
            self, name, str(distro.get("version") or ""), self._settings.get("last_export_dir")
        )
        if request is None:
            return
        export_path, use_vhd = request.path, request.vhd

        if os.path.exists(export_path) and not messagebox.askyesno(
            self._t("gui.common.confirm"),
            self._t("gui.confirm.overwrite", path=export_path),
            parent=self,
        ):
            return

        export_dir = os.path.dirname(export_path)
        if export_dir:
            self._settings["last_export_dir"] = export_dir
            self._save_settings()

        partial_path = wsl_core.partial_write_path(export_path)
        # 前回失敗して残った部分ファイルがあれば掃除する（wsl --export は既存ファイルを拒否する）
        wsl_core.discard_partial_write(partial_path)

        # 元 VHDX のサイズを進捗率の分母 (上限の目安) として使う
        total_bytes = _file_size(_get_distro_vhdx_path(name))

        self._log_operation("エクスポート", name, export_path)
        self._set_status(self._t("gui.msg.exporting", name=name))

        def _on_done(returncode: int, stderr_text: str, cancelled: bool) -> None:
            if cancelled:
                wsl_core.discard_partial_write(partial_path)
                self._log_operation("エクスポート", name, "キャンセル")
                self._set_status(self._t("gui.msg.export_cancelled", name=name))
            elif returncode == 0:
                if wsl_core.finalize_partial_write(partial_path, export_path):
                    self._set_status(self._t("gui.msg.exported", name=name, path=export_path))
                else:
                    wsl_core.discard_partial_write(partial_path)
                    self._show_error(
                        self._t("gui.msg.export_failed", name=name),
                        self._t("gui.msg.move_failed"),
                    )
            else:
                wsl_core.discard_partial_write(partial_path)
                self._show_error(self._t("gui.msg.export_failed", name=name), stderr_text)
            self._refresh()

        TransferProgressDialog(
            self,
            self._t("gui.transfer.export_title"),
            self._t("gui.transfer.export_message", name=name),
            wsl_core.build_export_args(name, partial_path, use_vhd),
            partial_path,
            total_bytes,
            _on_done,
        )

    def _import_distro_image(self) -> None:
        """tar/vhdx 形式のディストリビューションイメージをインポートします。"""
        request = ImportDialog.ask(self, self._existing_names())
        if request is None:
            return
        distro_name = request.name
        # フォームで検証済みだが、コマンドラインに渡す前にもう一度確かめる
        valid, reason = wsl_core.validate_distro_name(distro_name, language=self._language)
        if not valid:
            messagebox.showwarning(self._t("gui.common.warning"), reason, parent=self)
            return
        image_path, install_path, version = request.image_path, request.install_dir, request.version

        if not messagebox.askyesno(
            self._t("gui.common.confirm"),
            self._t(
                "gui.confirm.import",
                name=distro_name,
                image=image_path,
                folder=install_path,
                version=version,
            ),
            parent=self,
        ):
            return

        try:
            os.makedirs(install_path, exist_ok=True)
        except OSError as e:
            self._show_error(self._t("gui.msg.folder_failed", path=install_path), str(e))
            return

        # 入力イメージのサイズを分母に、インストール先 ext4.vhdx の成長を監視する
        # (WSL1 は vhdx を使わないため経過時間のみの表示になる)
        total_bytes: int | None = None
        watch_path: str | None = None
        if version == "2":
            total_bytes = _file_size(image_path)
            watch_path = os.path.join(install_path, "ext4.vhdx")

        self._log_operation("インポート", distro_name, image_path)
        self._set_status(self._t("gui.msg.importing", name=distro_name))

        def _on_done(returncode: int, stderr_text: str, cancelled: bool) -> None:
            if cancelled:
                self._log_operation("インポート", distro_name, "キャンセル")
                self._set_status(self._t("gui.msg.import_cancelled", name=distro_name))
                if messagebox.askyesno(
                    self._t("gui.common.confirm"),
                    self._t("gui.confirm.unregister_partial", name=distro_name),
                    parent=self,
                ):
                    self._run_wsl_cmd(
                        ["--unregister", distro_name],
                        self._t("gui.msg.unregister_success", name=distro_name),
                        self._t("gui.msg.unregister_failed", name=distro_name),
                    )
                    return
            elif returncode == 0:
                self._set_status(self._t("gui.msg.imported", name=distro_name))
            else:
                self._show_error(self._t("gui.msg.import_failed", name=distro_name), stderr_text)
            self._refresh()

        TransferProgressDialog(
            self,
            self._t("gui.transfer.import_title"),
            self._t("gui.transfer.import_message", name=distro_name),
            wsl_core.build_import_args(distro_name, install_path, image_path, version),
            watch_path,
            total_bytes,
            _on_done,
        )

    # ── スナップショット ─────────────────────────────────────────────────

    def _snapshot_dir(self) -> str:
        """スナップショットの保存先ディレクトリを返します（設定優先、未設定時はデフォルト）。"""
        return self._settings.get("snapshot_dir") or wsl_core.get_default_snapshot_dir()

    def _create_snapshot(self) -> None:
        """選択したディストリビューションのスナップショット (tar + メタデータ) を作成します。"""
        distro = self._selected_distro()
        if distro is None:
            _warn_no_selection(self)
            return
        name = distro["name"]

        comment = simpledialog.askstring(
            self._t("gui.snapshot.create_title"),
            self._t("gui.snapshot.create_prompt", name=name, folder=self._snapshot_dir()),
            parent=self,
        )
        if comment is None:
            return

        snap_dir = self._snapshot_dir()
        try:
            os.makedirs(snap_dir, exist_ok=True)
        except OSError as e:
            messagebox.showerror(self._t("gui.common.error"), str(e), parent=self)
            return

        timestamp = time.strftime(wsl_core.SNAPSHOT_TIMESTAMP_FORMAT)
        created_at = datetime.now().isoformat(timespec="seconds")
        basename = wsl_core.build_snapshot_basename(name, timestamp)
        tar_path = os.path.join(snap_dir, basename + ".tar")
        json_path = os.path.join(snap_dir, basename + ".json")
        wsl_version = str(distro.get("version") or "2")

        # 元 VHDX のサイズを進捗率の分母 (上限の目安) として使う
        total_bytes = _file_size(_get_distro_vhdx_path(name))

        partial_tar = wsl_core.partial_write_path(tar_path)
        # 前回失敗して残った部分ファイルがあれば掃除する（wsl --export は既存ファイルを拒否する）
        wsl_core.discard_partial_write(partial_tar)

        self._log_operation("スナップショット作成", name, tar_path)
        self._set_status(self._t("gui.msg.snapshot_creating", name=name))

        def _on_done(returncode: int, stderr_text: str, cancelled: bool) -> None:
            if cancelled:
                wsl_core.discard_partial_write(partial_tar)
                self._log_operation("スナップショット作成", name, "キャンセル")
                self._set_status(self._t("gui.msg.snapshot_cancelled", name=name))
            elif returncode == 0:
                if not wsl_core.finalize_partial_write(partial_tar, tar_path):
                    wsl_core.discard_partial_write(partial_tar)
                    self._show_error(
                        self._t("gui.msg.snapshot_failed", name=name),
                        self._t("gui.msg.move_failed"),
                    )
                else:
                    size = _file_size(tar_path) or 0
                    metadata = wsl_core.build_snapshot_metadata(
                        name, wsl_version, comment, size, created_at, basename + ".tar"
                    )
                    if not wsl_core.write_snapshot_metadata(json_path, metadata):
                        self._set_status(self._t("gui.msg.snapshot_meta_failed", name=name))
                    else:
                        self._set_status(self._t("gui.msg.snapshot_created", name=name))
            else:
                wsl_core.discard_partial_write(partial_tar)
                self._show_error(self._t("gui.msg.snapshot_failed", name=name), stderr_text)
            self._refresh()

        TransferProgressDialog(
            self,
            self._t("gui.transfer.snapshot_title"),
            self._t("gui.transfer.snapshot_message", name=name),
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

    # ── インストール・登録解除 ─────────────────────────────────────────────

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
            return [], self._t("gui.msg.online_timeout")
        except FileNotFoundError:
            return [], self._t("gui.msg.wsl_missing")
        except OSError as e:
            return [], self._t("gui.msg.wsl_failed", error=e)

        if result.returncode != 0:
            stderr = wsl_core.decode_wsl_output(result.stderr).strip()
            return [], stderr or self._t("gui.msg.online_failed")

        names = wsl_core.parse_online_distros(wsl_core.decode_wsl_output(result.stdout))
        return names, None

    def _install_distro(self) -> None:
        """公式配布ディストリビューションを個別インストールします。

        バックグラウンドで ``wsl --list --online`` を取得しつつ UI フリーズを防ぎます。
        取得完了後に :class:`InstallDialog` を表示します。
        """
        self._set_status(self._t("gui.msg.online_loading"))
        self._begin_busy()

        def _fetch() -> None:
            candidates, err = self._get_online_distros()

            def _open() -> None:
                self._end_busy()
                self._open_install_dialog(candidates, err)

            self._call_soon_safe(_open)

        threading.Thread(target=_fetch, daemon=True).start()

    def _open_install_dialog(self, candidates: list[str], err: str | None) -> None:
        """``_install_distro`` のバックグラウンド取得完了後にダイアログを開きます。"""
        if err:
            self._set_status(err)
        else:
            self._set_status(self._t("gui.status.ready"))

        dialog = InstallDialog(self, candidates)
        self.wait_window(dialog)

        name = dialog.result
        if name is None:
            self._set_status(self._t("gui.msg.install_cancelled"))
            return

        if not messagebox.askyesno(
            self._t("gui.common.confirm"), self._t("gui.confirm.install", name=name), parent=self
        ):
            return

        self._run_install_cmd(name)

    def _run_install_cmd(self, name: str) -> None:
        """``wsl --install`` を進捗ダイアログ付きで実行します。

        ダウンロードを伴い数分かかることがあるため、固定タイムアウトの
        ``_run_wsl_cmd`` (以前は 60 秒で打ち切っていた) ではなく、キャンセル可能な
        進捗ダイアログで完了まで待ちます。
        """
        self._log_operation("インストール", name, "実行")
        self._set_status(self._t("gui.msg.installing", name=name))

        def _on_done(returncode: int, stderr_text: str, cancelled: bool) -> None:
            if cancelled:
                self._log_operation("インストール", name, "キャンセル")
                self._set_status(self._t("gui.msg.install_cancelled"))
            elif returncode == 0:
                self._set_status(self._t("gui.msg.installed", name=name))
            else:
                self._show_error(self._t("gui.msg.install_failed", name=name), stderr_text)
            self._refresh()

        TransferProgressDialog(
            self,
            self._t("gui.transfer.install_title"),
            self._t("gui.transfer.install_message", name=name),
            ["--install", "-d", name, "--no-launch"],
            None,
            None,
            _on_done,
            cancel_prompt=self._t("gui.transfer.install_cancel"),
        )

    def _uninstall_distro(self) -> None:
        """選択したディストリビューションを登録解除します (名前の再入力による二段階確認)。"""
        distro = self._selected_distro()
        if distro is None:
            _warn_no_selection(self)
            return
        name = distro["name"]

        if not messagebox.askyesno(
            self._t("gui.common.confirm"),
            self._t("gui.confirm.unregister", name=name),
            icon=messagebox.WARNING,
            parent=self,
        ):
            return

        confirm_name = simpledialog.askstring(
            self._t("gui.common.confirm"),
            self._t("gui.confirm.unregister_retype", name=name),
            parent=self,
        )
        if confirm_name is None:
            return

        if confirm_name.strip() != name:
            messagebox.showwarning(
                self._t("gui.common.warning"),
                self._t("gui.msg.unregister_mismatch"),
                parent=self,
            )
            return

        self._log_operation("アンインストール", name, "実行")
        self._set_status(self._t("gui.msg.unregistering", name=name))
        self._run_wsl_cmd(
            ["--unregister", name],
            self._t("gui.msg.unregister_success", name=name),
            self._t("gui.msg.unregister_failed", name=name),
        )

    # ── 設定ファイル ───────────────────────────────────────────────────────

    def _open_wslconfig(self) -> None:
        """.wslconfig エディタダイアログを開きます。"""
        dialog = WslConfigDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            self._set_status(self._t("gui.msg.wslconfig_saved"))

    def _open_distro_conf(self) -> None:
        """選択したディストリビューションの wsl.conf エディタダイアログを開きます。"""
        distro = self._selected_distro()
        if distro is None:
            _warn_no_selection(self)
            return
        name = distro["name"]
        dialog = DistroConfDialog(self, name)
        self.wait_window(dialog)
        if dialog.result:
            self._set_status(self._t("gui.msg.distroconf_saved", name=name))
            self._refresh()

    # ── コンテキストメニュー ───────────────────────────────────────────────

    def _show_context_menu(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        """右クリックでディストリビューション操作のコンテキストメニューを表示します。"""
        row = self._tree.identify_row(event.y)
        if not row:
            return
        self._tree.selection_set(row)
        self._tree.focus(row)
        self._popup_context_menu(event.x_root, event.y_root)

    def _show_context_menu_for_selection(self, _event: object = None) -> str:
        """キーボード (Shift+F10 / アプリケーションキー) でコンテキストメニューを開きます。"""
        selected = self._selected_name()
        if selected:
            bbox = self._tree.bbox(selected)
            x = self._tree.winfo_rootx() + (bbox[0] + 20 if bbox else 20)
            y = self._tree.winfo_rooty() + (bbox[1] + bbox[3] if bbox else 20)
            self._popup_context_menu(x, y)
        return "break"

    def _popup_context_menu(self, x: int, y: int) -> None:
        availability = wsl_core.action_availability(self._selected_distro())
        menu = tk.Menu(self, tearoff=0)

        def _add(key: str, command: Callable[[], None], action: str) -> None:
            menu.add_command(
                label=self._t(key),
                command=command,
                state=tk.NORMAL if availability.get(action) else tk.DISABLED,
            )

        _add("gui.context.terminal", self._open_terminal, "terminal")
        _add("gui.context.start", self._start_distro, "start")
        _add("gui.context.stop", self._stop_distro, "stop")
        _add("gui.context.explorer", self._open_in_explorer, "explorer")
        _add("gui.context.copy_ip", self._copy_ip_address, "copy_ip")
        menu.add_separator()
        _add("gui.context.snapshot", self._create_snapshot, "snapshot")
        _add("gui.context.export", self._export_distro_image, "export")
        _add("gui.context.clone", self._clone_distro, "clone")
        menu.add_separator()
        _add("gui.context.set_default", self._set_default, "set_default")
        _add("gui.context.convert", self._convert_version, "convert")
        _add("gui.context.distro_conf", self._open_distro_conf, "distro_conf")
        _add("gui.context.optimize", self._open_disk_optimize, "optimize")
        _add("gui.context.details", self._show_detail, "details")
        _add("gui.context.processes", self._show_processes, "processes")
        menu.add_separator()
        _add("gui.context.unregister", self._uninstall_distro, "unregister")
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    # ── そのほかの操作 ─────────────────────────────────────────────────────

    def _open_disk_optimize(self) -> None:
        """選択したディストリビューションのディスク最適化ダイアログを開きます。"""
        distro = self._selected_distro()
        if distro is None:
            _warn_no_selection(self)
            return
        name = distro["name"]
        vhdx = _get_distro_vhdx_path(name)
        if not vhdx:
            messagebox.showinfo(
                self._t("gui.optimize.title", name=name),
                self._t("gui.msg.vhdx_missing", name=name),
                parent=self,
            )
            return
        DiskOptimizeDialog(self, name, vhdx)

    def _open_in_explorer(self) -> None:
        """選択したディストリビューションのファイルシステムをエクスプローラーで開きます。"""
        distro = self._selected_distro()
        if distro is None:
            _warn_no_selection(self)
            return
        name = distro["name"]
        try:
            subprocess.Popen(
                ["explorer.exe", f"\\\\wsl.localhost\\{name}"],
                creationflags=CREATE_NO_WINDOW,
            )
            self._set_status(self._t("gui.msg.explorer_opened", name=name))
        except OSError as e:
            self._show_error(self._t("gui.msg.explorer_failed"), str(e))

    def _copy_ip_address(self) -> None:
        """選択したディストリビューションのIPアドレスをクリップボードにコピーします。"""
        distro = self._selected_distro()
        if distro is None:
            return
        ip = str(distro.get("ip") or "")
        if ip and ip != "-":
            self.clipboard_clear()
            self.clipboard_append(ip)
            self._set_status(self._t("gui.msg.ip_copied", ip=ip))
        else:
            self._set_status(self._t("gui.msg.ip_unavailable"))

    def _convert_version(self) -> None:
        """選択したディストリビューションの WSL バージョンを変換します(WSL1↔WSL2)。"""
        distro = self._selected_distro()
        if distro is None:
            _warn_no_selection(self)
            return
        name = distro["name"]
        current = str(distro.get("version") or "")
        target = wsl_core.conversion_target(current) or "2"

        if current in ("1", "2"):
            confirm_msg = self._t(
                "gui.confirm.convert_from", name=name, current=current, target=target
            )
        else:
            confirm_msg = self._t("gui.confirm.convert", name=name, target=target)

        if not messagebox.askyesno(self._t("gui.common.confirm"), confirm_msg, parent=self):
            return

        self._log_operation("バージョン変換", name, f"WSL{target}")
        self._set_status(self._t("gui.msg.converting", name=name, version=target))

        def _on_done(returncode: int, stderr_text: str, cancelled: bool) -> None:
            if cancelled:
                self._log_operation("バージョン変換", name, "キャンセル")
                self._set_status(self._t("gui.msg.convert_cancelled", name=name))
            elif returncode == 0:
                self._set_status(self._t("gui.msg.convert_success", name=name, version=target))
            else:
                self._show_error(self._t("gui.msg.convert_failed", name=name), stderr_text)
            self._refresh()

        # ``--set-version`` は大きなディストリビューションで数分〜数十分かかるため
        # 固定タイムアウトの _run_wsl_cmd ではなく Popen ベースの進捗ダイアログを使う。
        # 進捗を監視できる出力ファイルは無いので watch_path は None（経過時間表示）。
        TransferProgressDialog(
            self,
            self._t("gui.transfer.convert_title"),
            self._t("gui.transfer.convert_message", name=name, version=target),
            ["--set-version", name, target],
            None,
            None,
            _on_done,
            cancel_prompt=self._t("gui.transfer.convert_cancel"),
        )

    def _open_mount(self) -> None:
        """ディスクのマウントダイアログを開きます。"""
        WslMountDialog(self)

    def _open_unmount(self) -> None:
        """ディスクのアンマウントダイアログを開きます。"""
        WslUnmountDialog(self)

    def _execute_mount(self, disk: str, mount_args: list[str]) -> None:
        """ディスクのマウントコマンドを実行します。"""
        self._set_status(self._t("gui.msg.mounting", disk=disk))
        self._begin_busy()

        def _run() -> None:
            res = wsl_core.run_wsl(mount_args, timeout=60.0, creationflags=CREATE_NO_WINDOW)

            def _done() -> None:
                self._end_busy()
                if res.returncode == 0:
                    self._log_operation("マウント", disk, "成功")
                    self._set_status(self._t("gui.msg.mounted", disk=disk))
                    messagebox.showinfo(
                        self._t("gui.mount.title"),
                        self._t("gui.msg.mounted", disk=disk),
                        parent=self,
                    )
                else:
                    msg = res.stderr.strip() or self._t("gui.msg.command_failed")
                    self._log_operation("マウント", disk, f"失敗: {msg}")
                    self._show_error(
                        self._t("gui.msg.mount_failed", disk=disk),
                        msg + "\n\n" + self._t("gui.msg.admin_hint"),
                    )

            self._call_soon_safe(_done)

        threading.Thread(target=_run, daemon=True).start()

    def _execute_unmount(self, disk: str | None, unmount_args: list[str]) -> None:
        """ディスクのアンマウントコマンドを実行します。"""
        target = disk or self._t("gui.msg.all_disks")
        self._set_status(self._t("gui.msg.unmounting", disk=target))
        self._begin_busy()

        def _run() -> None:
            res = wsl_core.run_wsl(unmount_args, timeout=30.0, creationflags=CREATE_NO_WINDOW)

            def _done() -> None:
                self._end_busy()
                if res.returncode == 0:
                    self._log_operation("アンマウント", target, "成功")
                    self._set_status(self._t("gui.msg.unmounted", disk=target))
                    messagebox.showinfo(
                        self._t("gui.unmount.title"),
                        self._t("gui.msg.unmounted", disk=target),
                        parent=self,
                    )
                else:
                    msg = res.stderr.strip() or self._t("gui.msg.command_failed")
                    self._log_operation("アンマウント", target, f"失敗: {msg}")
                    self._show_error(
                        self._t("gui.msg.unmount_failed", disk=target),
                        msg + "\n\n" + self._t("gui.msg.admin_hint"),
                    )

            self._call_soon_safe(_done)

        threading.Thread(target=_run, daemon=True).start()

    def _show_wsl_version(self) -> None:
        """WSL のバージョン情報を取得してダイアログに表示します。"""
        label_keys = {
            "wsl": "gui.version.wsl",
            "kernel": "gui.version.kernel",
            "wslg": "gui.version.wslg",
            "msrdc": "gui.version.msrdc",
            "direct3d": "gui.version.direct3d",
            "dxcore": "gui.version.dxcore",
            "windows": "gui.version.windows",
        }
        self._begin_busy()

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
            except (OSError, subprocess.TimeoutExpired, ValueError):
                info = {}

            def _show() -> None:
                self._end_busy()
                lines = []
                for key, label_key in label_keys.items():
                    value = info.get(key)
                    if value is not None:
                        lines.append(f"{self._t(label_key)}: {value}")
                if not lines:
                    lines = [self._t("gui.version.unavailable")]
                capability = wsl_core.wslc_capability(str(info.get("wsl", "")))
                lines.append("")
                lines.append(
                    self._t("containers.eligible")
                    if capability["version_supported"]
                    else f"WSL Containers: {capability['reason']}"
                )
                unparsed = info.get("_unparsed_lines")
                if unparsed:
                    lines.append("")
                    lines.append(self._t("gui.version.other"))
                    lines.extend(unparsed)
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
        """``wsl --update`` をバックグラウンドで実行します (進捗ダイアログ付き)。"""
        args = ["--update"]
        if pre_release:
            args.append("--pre-release")

        self._set_status(self._t("gui.msg.updating"))

        def _on_done(returncode: int, stderr_text: str, cancelled: bool) -> None:
            target = "wsl" + ("(--pre-release)" if pre_release else "")
            if cancelled:
                self._log_operation("WSL 更新", target, "キャンセル")
                self._set_status(self._t("gui.msg.update_cancelled"))
            elif returncode == 0:
                self._log_operation("WSL 更新", target, "成功")
                self._set_status(self._t("gui.msg.update_done"))
                messagebox.showinfo(
                    self._t("gui.update.title"), self._t("gui.msg.update_done"), parent=self
                )
            else:
                msg = stderr_text or self._t("gui.msg.update_failed")
                self._log_operation("WSL 更新", target, f"失敗: {msg}")
                self._show_error(self._t("gui.msg.update_failed"), stderr_text)

        TransferProgressDialog(
            self,
            self._t("gui.update.title"),
            self._t("gui.msg.updating"),
            args,
            None,
            None,
            _on_done,
            cancel_prompt=self._t("gui.transfer.update_cancel"),
        )

    # ── ヘルプ ───────────────────────────────────────────────────────────

    def _show_shortcuts(self) -> None:
        messagebox.showinfo(
            self._t("gui.action.shortcuts"), self._t("gui.help.shortcuts"), parent=self
        )

    def _show_cli_help(self) -> None:
        """コマンドライン版 (wslmgr.exe) の場所と使い方を案内します。"""
        cli = resources.find_cli_executable()
        location = cli or self._t("gui.help.cli_not_found")
        messagebox.showinfo(
            self._t("gui.action.cli_help"),
            self._t("gui.help.cli", location=location),
            parent=self,
        )

    def _open_project_page(self) -> None:
        try:
            webbrowser.open(PROJECT_URL)
        except webbrowser.Error as e:
            self._show_error(self._t("gui.msg.browser_failed"), str(e))

    def _show_about(self) -> None:
        """アプリケーション情報を表示します。"""
        messagebox.showinfo(
            self._t("gui.about.title"),
            self._t("gui.about.body", version=wsl_core.__version__, url=PROJECT_URL),
            parent=self,
        )

    # ── ウィンドウ終了 ────────────────────────────────────────────────────

    def on_closing(self) -> None:
        # 実行中のエクスポート/インポート等があれば、確認の上でプロセスを
        # 終了させてから閉じる (#26: 放置すると wsl.exe が孤児化する)。
        live_transfers = [d for d in self._transfer_dialogs if d.winfo_exists()]
        if live_transfers:
            if not messagebox.askyesno(
                self._t("gui.common.confirm"),
                self._t("gui.confirm.quit_running", count=len(live_transfers)),
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
        self._ui_queue.close()
        self.destroy()


# ── エントリポイント ──────────────────────────────────────────────────────────


def _enable_dpi_awareness() -> None:
    """高 DPI 環境で文字がぼやけないよう、DPI 対応を宣言します (Windows のみ)。"""
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def _set_app_user_model_id() -> None:
    """タスクバーで python.exe ではなく WSL Manager のアイコンとしてまとめて表示させます。"""
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("kumakumapon.WSLManager")
    except (AttributeError, OSError):
        pass


def _activate_existing_instance() -> bool:
    """既に起動していればそのウィンドウを前面に出して True を返します (Named Mutex)。"""
    try:
        import ctypes

        mutex_name = "Global\\WSLManager_SingleInstance_Mutex"
        ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
        if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            hwnd = ctypes.windll.user32.FindWindowW(None, "WSL Manager")
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                ctypes.windll.user32.SetForegroundWindow(hwnd)
            return True
    except (AttributeError, OSError):
        pass
    return False


def main() -> None:
    if sys.platform != "win32":
        # Windows 以外では起動できない旨を伝えて終了
        root = tk.Tk()
        root.withdraw()
        language = wsl_core.resolve_language(
            wsl_core.load_settings(wsl_core.get_default_settings_path())["language"]
        )
        messagebox.showerror(
            wsl_core.translate("gui.common.error", language),
            wsl_core.translate("gui.msg.windows_only", language),
            parent=root,
        )
        root.destroy()
        sys.exit(1)

    _enable_dpi_awareness()
    _set_app_user_model_id()
    if _activate_existing_instance():
        sys.exit(0)

    app = WSLManager()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()


if __name__ == "__main__":
    main()
