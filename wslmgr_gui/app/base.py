"""``WSLManager`` の Mixin 群が共有する、型チェック用の基底クラス。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING, Any

import wsl_core

if TYPE_CHECKING:
    from wslmgr_gui.widgets import TreeviewSorter

    # 型チェック時だけ ``tk.Tk`` の API (after / winfo_* など) を Mixin から使えるようにする。
    # 実行時は ``object`` なので、``class WSLManager(Mixin, tk.Tk)`` の MRO に Tk が二重に入らない。
    _Root = tk.Tk
else:
    _Root = object


class AppBase(_Root):
    """Mixin が参照する ``WSLManager`` 側のメンバーの型宣言 (実装は持たない)。

    Tk のメソッドはここで宣言しない (``tk.Tk`` と定義が衝突するため)。属性は注釈のみ、
    メソッドは ``if TYPE_CHECKING:`` 内で宣言する。実装は ``WSLManager`` が持つ。
    """

    # ``WSLManager.__init__`` / UI 構築で作られる属性
    _resource_history: wsl_core.ResourceHistory
    _resource_history_visible: bool
    _history_layouts: dict[str, wsl_core.ChartLayout]
    _history_toggle: ttk.Button
    _statusbar: ttk.Label
    _auto_refresh_var: tk.BooleanVar
    _sorter: TreeviewSorter
    _refresh_job: str | None
    _current_theme: str
    _settings: dict[str, Any]
    _settings_path: str
    _log_dir: str
    _log_file: str
    _operation_log: list[str]
    _log_writer: wsl_core.AsyncLogWriter

    if TYPE_CHECKING:
        # 実装は ``WSLManager`` (本体) にある。Mixin から呼ぶものだけを宣言する。
        def _refresh(self) -> None: ...

        def _set_status(self, msg: str) -> None: ...

        def _t(self, key: str, **values: object) -> str: ...
