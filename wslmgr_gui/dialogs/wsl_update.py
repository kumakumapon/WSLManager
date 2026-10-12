"""WSL 更新の確認ダイアログ。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import wsl_core


class WslUpdateConfirmDialog(tk.Toplevel):
    """``wsl --update`` 実行前の確認ダイアログ。

    ``--pre-release`` オプションのチェックボックスを備えます。実行中の
    ディストリビューションがある場合は、更新によりセッションが終了する
    可能性がある旨の警告文を表示します。

    ``wait_window()`` で待機し、実行が確定した場合は ``self.result`` に
    ``{"pre_release": bool}`` を設定します。キャンセル時は ``None`` のままです。
    """

    def __init__(self, parent: tk.Tk, running_distros: list[str]) -> None:
        super().__init__(parent)
        self.title(
            wsl_core.translate(
                "gui.update.title", getattr(parent, "_language", wsl_core.LANGUAGE_AUTO)
            )
        )
        self.resizable(False, False)
        self.result: dict | None = None
        self._running_distros = running_distros
        self._build_ui()
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def _build_ui(self) -> None:
        frame = ttk.Frame(self, padding=14)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame,
            text="wsl --update を実行して WSL 本体（カーネル）を更新します。",
            wraplength=380,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(0, 8))

        if self._running_distros:
            names = "、".join(self._running_distros)
            ttk.Label(
                frame,
                text=(
                    f"実行中のディストリビューション ({names}) があります。\n"
                    "更新によりこれらのセッションが終了する可能性があります。"
                ),
                foreground="#b03030",
                wraplength=380,
                justify=tk.LEFT,
            ).pack(anchor=tk.W, pady=(0, 10))

        self._pre_release_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame,
            text="プレリリース版を使用する (--pre-release)",
            variable=self._pre_release_var,
        ).pack(anchor=tk.W, pady=(0, 10))

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="更新", command=self._on_ok, width=10).pack(
            side=tk.RIGHT, padx=(4, 0)
        )
        ttk.Button(btn_frame, text="キャンセル", command=self._on_cancel, width=10).pack(
            side=tk.RIGHT
        )

    def _on_ok(self) -> None:
        self.result = {"pre_release": self._pre_release_var.get()}
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()
