"""WSL コマンドの長時間転送・進捗ダイアログ。"""

from __future__ import annotations

import os
import subprocess
import threading
import time
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

import wsl_core
from wslmgr_gui.winutil import CREATE_NO_WINDOW


class TransferProgressDialog(tk.Toplevel):
    """エクスポート/インポートの進捗表示とキャンセルを提供するダイアログ。

    ``wsl`` コマンドを :class:`subprocess.Popen` で起動し、``watch_path`` の
    ファイルサイズを 1 秒間隔でポーリングして進捗を間接的に可視化します。
    ``wsl --export`` / ``--import`` 自体は進捗を出力しないため、出力ファイルの
    成長を ``total_bytes`` (上限の目安) と比較して進捗率を推定します。

    - ``total_bytes`` が分かる場合は確定 (determinate) プログレスバーで % 表示
    - 不明な場合は不確定 (indeterminate) バー + 書き込み済みサイズのみ表示
    - ``watch_path`` が None の場合はサイズ監視を行わず経過時間のみ表示

    キャンセルボタンで起動したプロセスを ``terminate()`` します。
    完了時は ``on_done(returncode, stderr_text, cancelled)`` を呼び出します。
    キャンセル要求とほぼ同時にプロセスが正常終了した場合は、処理が完了して
    いるため ``cancelled=False`` として通知します。
    """

    POLL_INTERVAL_MS = 1000

    def __init__(
        self,
        parent: tk.Tk,
        title: str,
        message: str,
        wsl_args: list[str],
        watch_path: str | None,
        total_bytes: int | None,
        on_done: Callable[[int, str, bool], None],
        cancel_prompt: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self._watch_path = watch_path
        self._total_bytes = total_bytes
        self._on_done = on_done
        self._cancel_prompt = cancel_prompt or "処理をキャンセルしますか？"
        self._cancelled = False
        self._finished = False
        self._start_time = time.monotonic()
        self._build_ui(message)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._request_cancel)

        try:
            self._proc = subprocess.Popen(
                ["wsl", *wsl_args],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=CREATE_NO_WINDOW,
            )
        except (OSError, FileNotFoundError) as e:
            self._finished = True
            err_text = str(e)
            self.after_idle(lambda: self._close_with(-1, err_text, False))
            return

        threading.Thread(target=self._wait_proc, daemon=True).start()
        self.after(self.POLL_INTERVAL_MS, self._tick)
        # アプリ終了時 (WSLManager.on_closing) に強制キャンセルできるよう
        # 親ウィンドウへ自己登録する。Popen 起動に失敗したパス (上の except)
        # では after_idle で即座に自己完結するため登録不要。
        self._owner = parent
        if hasattr(parent, "_transfer_dialogs"):
            parent._transfer_dialogs.append(self)

    def _build_ui(self, message: str) -> None:
        main = ttk.Frame(self, padding=16)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text=message).pack(anchor=tk.W)

        determinate = self._total_bytes is not None and self._total_bytes > 0
        self._progress = ttk.Progressbar(
            main,
            length=380,
            mode="determinate" if determinate else "indeterminate",
        )
        self._progress.pack(fill=tk.X, pady=(10, 6))
        if not determinate:
            self._progress.start(80)

        self._status_var = tk.StringVar(value="開始しています…")
        ttk.Label(main, textvariable=self._status_var).pack(anchor=tk.W)

        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(12, 0))
        self._cancel_btn = ttk.Button(
            btn_frame, text="キャンセル", command=self._request_cancel, width=12
        )
        self._cancel_btn.pack(side=tk.RIGHT)

    # ── プロセス監視 ──────────────────────────────────────────────────

    def _wait_proc(self) -> None:
        """バックグラウンドスレッドでプロセス終了を待ちます。"""
        _stdout, stderr = self._proc.communicate()
        stderr_text = wsl_core.decode_wsl_output(stderr).strip() if stderr else ""
        returncode = self._proc.returncode
        self.after(0, lambda: self._handle_exit(returncode, stderr_text))

    def _handle_exit(self, returncode: int, stderr_text: str) -> None:
        """プロセス終了を UI スレッドで処理します。"""
        if self._finished:
            return
        self._finished = True
        # キャンセル要求とほぼ同時に正常終了した場合は完了扱いにする
        cancelled = self._cancelled and returncode != 0
        self._close_with(returncode, stderr_text, cancelled)

    def _close_with(self, returncode: int, stderr_text: str, cancelled: bool) -> None:
        owner = getattr(self, "_owner", None)
        if owner is not None:
            try:
                owner._transfer_dialogs.remove(self)
            except ValueError:
                pass
        try:
            self.destroy()
        finally:
            self._on_done(returncode, stderr_text, cancelled)

    # ── 進捗ポーリング ──────────────────────────────────────────────────

    def _tick(self) -> None:
        """1 秒ごとにファイルサイズと経過時間で表示を更新します。"""
        if self._finished:
            return
        elapsed = time.monotonic() - self._start_time

        if self._cancelled:
            self._status_var.set("キャンセルしています…")
        elif self._watch_path is None:
            self._status_var.set(f"経過 {wsl_core.format_duration(elapsed)}")
        else:
            try:
                current = os.path.getsize(self._watch_path)
            except OSError:
                current = 0
            self._status_var.set(
                wsl_core.format_transfer_status(current, self._total_bytes, elapsed)
            )
            percent = wsl_core.estimate_transfer_progress(current, self._total_bytes)
            if percent is not None:
                # 完了前に 100% に見えないよう 99% で頭打ちにする
                self._progress.configure(value=min(percent, 99.0))

        self.after(self.POLL_INTERVAL_MS, self._tick)

    # ── キャンセル ──────────────────────────────────────────────────

    def _request_cancel(self) -> None:
        """キャンセルボタン / 閉じるボタン押下時の処理。"""
        if self._finished or self._cancelled:
            return
        if not messagebox.askyesno("確認", self._cancel_prompt, parent=self):
            return
        if self._finished:  # 確認ダイアログ表示中に完了した場合
            return
        self._cancelled = True
        self._cancel_btn.configure(state=tk.DISABLED)
        self._status_var.set("キャンセルしています…")
        try:
            self._proc.terminate()
        except OSError:
            pass

    def force_cancel(self, timeout: float = 5.0) -> None:
        """アプリ終了時 (WSLManager.on_closing) に呼ばれます。

        確認ダイアログや完了コールバック (``_on_done``、ログ記録や
        「不完全な登録を解除しますか」の確認を含む) は一切呼び出さず、
        プロセスの終了だけを同期的に保証します。``self._finished`` を
        先に立てるため、後から ``_wait_proc`` 経由で ``_handle_exit`` が
        呼ばれても no-op になります (二重処理の防止)。
        """
        if self._finished:
            return
        self._finished = True
        proc = getattr(self, "_proc", None)
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=2.0)
            except (subprocess.TimeoutExpired, OSError):
                # kill() の時点で対象プロセスが既に自然終了している場合など、
                # OSError (Windows では PermissionError 等) が起き得る。
                # on_closing 側の後続処理 (他ダイアログの force_cancel・
                # 終了処理) を止めないよう、ここでも握りつぶす。
                pass
