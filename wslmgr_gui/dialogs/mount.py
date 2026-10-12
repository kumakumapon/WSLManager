"""ディスクのマウント・アンマウントダイアログ。"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

import wsl_core

if TYPE_CHECKING:
    from wslmgr import WSLManager


class WslMountDialog(tk.Toplevel):
    """物理ディスクまたは VHD を WSL2 にマウントするダイアログ。"""

    def __init__(self, parent: WSLManager) -> None:
        super().__init__(parent)
        self._parent = parent
        self.title(
            wsl_core.translate(
                "gui.mount.title", getattr(parent, "_language", wsl_core.LANGUAGE_AUTO)
            )
        )
        self.resizable(False, False)
        self._build_ui()
        self.transient(parent)
        self.grab_set()

    def _build_ui(self) -> None:
        frame = ttk.Frame(self, padding=14)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame,
            text=(
                "物理ディスクまたは VHD/VHDX ファイルを WSL2 にマウントします。\n"
                "※ 管理者権限が必要な場合があります。"
            ),
            foreground="#555555",
        ).grid(row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 10))

        # ディスクパス
        ttk.Label(frame, text="ディスク / VHD パス:").grid(row=1, column=0, sticky=tk.W, pady=3)
        self._disk_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self._disk_var, width=32).grid(
            row=1, column=1, sticky=tk.W, pady=3
        )
        ttk.Button(frame, text="参照...", command=self._browse_vhd, width=8).grid(
            row=1, column=2, padx=(4, 0), pady=3
        )

        # VHD フラグ
        self._vhd_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame,
            text="VHD / VHDX ファイルとしてマウント (--vhd)",
            variable=self._vhd_var,
        ).grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=3)

        # Bare フラグ
        self._bare_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame,
            text="ファイルシステムをマウントせずアタッチのみ (--bare)",
            variable=self._bare_var,
        ).grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=3)

        # ファイルシステム
        ttk.Label(frame, text="ファイルシステム (--type):").grid(
            row=4, column=0, sticky=tk.W, pady=3
        )
        self._type_var = tk.StringVar(value="")
        ttk.Entry(frame, textvariable=self._type_var, width=20).grid(
            row=4, column=1, sticky=tk.W, pady=3
        )

        # パーティション
        ttk.Label(frame, text="パーティション番号 (--partition):").grid(
            row=5, column=0, sticky=tk.W, pady=3
        )
        self._partition_var = tk.StringVar(value="")
        ttk.Entry(frame, textvariable=self._partition_var, width=10).grid(
            row=5, column=1, sticky=tk.W, pady=3
        )

        # マウント名
        ttk.Label(frame, text="マウント名 (--name):").grid(row=6, column=0, sticky=tk.W, pady=3)
        self._name_var = tk.StringVar(value="")
        ttk.Entry(frame, textvariable=self._name_var, width=20).grid(
            row=6, column=1, sticky=tk.W, pady=3
        )

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=7, column=0, columnspan=3, sticky=tk.E, pady=(12, 0))
        ttk.Button(btn_frame, text="マウント", command=self._on_mount, width=10).pack(
            side=tk.RIGHT, padx=(4, 0)
        )
        ttk.Button(btn_frame, text="キャンセル", command=self.destroy, width=10).pack(side=tk.RIGHT)

    def _browse_vhd(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="VHD/VHDX ファイルの選択",
            filetypes=[("VHD Files", "*.vhdx;*.vhd"), ("All Files", "*.*")],
        )
        if path:
            self._disk_var.set(path)
            self._vhd_var.set(True)

    def _on_mount(self) -> None:
        disk = self._disk_var.get().strip()
        if not disk:
            messagebox.showwarning(
                "入力エラー", "ディスクまたは VHD のパスを入力してください。", parent=self
            )
            return

        part_str = self._partition_var.get().strip()
        part_num = int(part_str) if part_str.isdigit() else None

        mount_args = wsl_core.build_wsl_mount_args(
            disk=disk,
            bare=self._bare_var.get(),
            fs_type=self._type_var.get().strip() or None,
            partition=part_num,
            vhd=self._vhd_var.get(),
            name=self._name_var.get().strip() or None,
        )

        self.destroy()
        self._parent._execute_mount(disk, mount_args)


class WslUnmountDialog(tk.Toplevel):
    """WSL2 にマウントされているディスクをアンマウントするダイアログ。"""

    def __init__(self, parent: WSLManager) -> None:
        super().__init__(parent)
        self._parent = parent
        self.title(
            wsl_core.translate(
                "gui.unmount.title", getattr(parent, "_language", wsl_core.LANGUAGE_AUTO)
            )
        )
        self.resizable(False, False)
        self._build_ui()
        self.transient(parent)
        self.grab_set()

    def _build_ui(self) -> None:
        frame = ttk.Frame(self, padding=14)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame,
            text=(
                "アンマウントするディスクパスを入力してください。\n"
                "空欄のまま実行すると、マウントされているすべてのディスクをアンマウントします。"
            ),
            foreground="#555555",
        ).pack(anchor=tk.W, pady=(0, 10))

        row = ttk.Frame(frame)
        row.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(row, text="ディスクパス (任意):", width=18, anchor=tk.W).pack(side=tk.LEFT)
        self._disk_var = tk.StringVar()
        ttk.Entry(row, textvariable=self._disk_var, width=30).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="アンマウント", command=self._on_unmount, width=12).pack(
            side=tk.RIGHT, padx=(4, 0)
        )
        ttk.Button(btn_frame, text="キャンセル", command=self.destroy, width=10).pack(side=tk.RIGHT)

    def _on_unmount(self) -> None:
        disk = self._disk_var.get().strip() or None
        unmount_args = wsl_core.build_wsl_unmount_args(disk=disk)
        self.destroy()
        self._parent._execute_unmount(disk, unmount_args)
