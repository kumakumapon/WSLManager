""".wslconfig 編集ダイアログ。"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, ttk
from typing import ClassVar

import wsl_core


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
