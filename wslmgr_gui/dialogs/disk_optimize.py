"""仮想ディスク (VHDX) 最適化ダイアログ。"""

from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import wsl_core
from wslmgr_gui.winutil import CREATE_NO_WINDOW


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
