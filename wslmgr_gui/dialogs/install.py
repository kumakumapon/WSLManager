"""ディストリビューションのオンラインインストールダイアログ。"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import wsl_core


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
