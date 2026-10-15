"""操作ログビューアーダイアログ。"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

import wsl_core


class LogViewerDialog(tk.Toplevel):
    """操作ログを表示するダイアログ。

    ``log_entries`` に渡されたログエントリを読み取り専用の Text ウィジェットで表示します。
    クリアボタンを押すと ``clear_callback`` を呼び出してログを消去します。
    """

    def __init__(
        self,
        parent: tk.Tk,
        log_entries: list[str],
        clear_callback: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self._log_entries = log_entries
        self._clear_callback = clear_callback
        self.title(
            wsl_core.translate(
                "gui.log.title", getattr(parent, "_language", wsl_core.LANGUAGE_AUTO)
            )
        )
        self.geometry("600x400")
        self.resizable(True, True)
        self._build_ui()
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _build_ui(self) -> None:
        main = ttk.Frame(self, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        text_frame = ttk.Frame(main)
        text_frame.pack(fill=tk.BOTH, expand=True)

        vsb = ttk.Scrollbar(text_frame, orient=tk.VERTICAL)
        self._text = tk.Text(
            text_frame,
            state=tk.DISABLED,
            wrap=tk.NONE,
            yscrollcommand=vsb.set,
        )
        vsb.configure(command=self._text.yview)
        self._text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._refresh_text()

        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btn_frame, text="閉じる", command=self.destroy, width=10).pack(
            side=tk.RIGHT, padx=(4, 0)
        )
        ttk.Button(btn_frame, text="クリア", command=self._on_clear, width=10).pack(side=tk.RIGHT)

    def _refresh_text(self) -> None:
        """ログエントリをテキストウィジェットに反映します。"""
        self._text.configure(state=tk.NORMAL)
        self._text.delete("1.0", tk.END)
        for entry in self._log_entries:
            self._text.insert(tk.END, entry + "\n")
        self._text.configure(state=tk.DISABLED)
        # 最終行までスクロール
        self._text.see(tk.END)

    def _on_clear(self) -> None:
        """クリアボタン押下時にコールバックを呼び出してログを消去します。"""
        self._clear_callback()
        self._refresh_text()
