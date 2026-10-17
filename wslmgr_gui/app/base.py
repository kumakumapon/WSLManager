"""``WSLManager`` の Mixin 群が共有する、型チェック用の基底クラス。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

import wsl_core

if TYPE_CHECKING:
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
