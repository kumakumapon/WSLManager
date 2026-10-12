"""WSL バージョン情報ダイアログ。"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

import wsl_core


class WslVersionDialog(tk.Toplevel):
    """WSL バージョン情報を表示するダイアログ。

    ``lines`` に渡された各行をラベルとして表示し、「更新を確認」ボタン押下時に
    ダイアログを閉じたうえで ``on_check_update`` コールバックを呼び出します。
    """

    def __init__(
        self,
        parent: tk.Tk,
        lines: list[str],
        on_check_update: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self._on_check_update = on_check_update
        self.title(
            wsl_core.translate(
                "gui.version.title", getattr(parent, "_language", wsl_core.LANGUAGE_AUTO)
            )
        )
        self.resizable(False, False)
        self._build_ui(lines)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _build_ui(self, lines: list[str]) -> None:
        frame = ttk.Frame(self, padding=14)
        frame.pack(fill=tk.BOTH, expand=True)

        for line in lines:
            ttk.Label(frame, text=line, justify=tk.LEFT).pack(anchor=tk.W)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(btn_frame, text="閉じる", command=self.destroy, width=10).pack(side=tk.RIGHT)
        ttk.Button(
            btn_frame, text="更新を確認", command=self._on_check_update_click, width=12
        ).pack(side=tk.RIGHT, padx=(0, 4))

    def _on_check_update_click(self) -> None:
        self.destroy()
        self._on_check_update()
