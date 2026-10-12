"""
WSL Manager - WSL2 ディストリビューション管理ツール

WSL2 の個別ディストリビューションの起動・停止・管理を行う GUI アプリケーションです。
Windows 10/11 + WSL2 環境での使用を前提としています。
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import ClassVar

import wsl_core
from wslmgr_gui.dialogs.containers import ContainerManagerDialog
from wslmgr_gui.dialogs.disk_optimize import DiskOptimizeDialog
from wslmgr_gui.dialogs.distro_conf import DistroConfDialog
from wslmgr_gui.dialogs.distro_detail import DistroDetailDialog
from wslmgr_gui.dialogs.install import InstallDialog
from wslmgr_gui.dialogs.log_viewer import LogViewerDialog
from wslmgr_gui.dialogs.mount import WslMountDialog, WslUnmountDialog
from wslmgr_gui.dialogs.process import ProcessWindow
from wslmgr_gui.dialogs.wsl_config import WslConfigDialog
from wslmgr_gui.dialogs.wsl_update import WslUpdateConfirmDialog
from wslmgr_gui.dialogs.wsl_version import WslVersionDialog
from wslmgr_gui.widgets import TreeviewSorter
from wslmgr_gui.winutil import (
    CREATE_NEW_CONSOLE,
    CREATE_NO_WINDOW,
    _get_distro_vhdx_path,
    _get_distro_vhdx_sizes,
)

logger = logging.getLogger(__name__)


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
        on_done: callable,
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


class SnapshotManagerDialog(tk.Toplevel):
    """スナップショット管理ダイアログ。

    保存先ディレクトリ内のスナップショット (tar + JSON メタデータ) 一覧を表示し、
    復元・削除・保存先フォルダを開く操作を提供します。
    """

    def __init__(self, parent: WSLManager) -> None:
        super().__init__(parent)
        self._parent = parent
        self._snapshots: list[dict] = []
        self.title(
            wsl_core.translate(
                "gui.snapshot.title", getattr(parent, "_language", wsl_core.LANGUAGE_AUTO)
            )
        )
        self.geometry("720x420")
        self.minsize(600, 320)
        self.resizable(True, True)
        self._build_ui()
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._reload()

    def _build_ui(self) -> None:
        main = ttk.Frame(self, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        top_frame = ttk.Frame(main)
        top_frame.pack(fill=tk.X, pady=(0, 6))

        self._dir_var = tk.StringVar(value="保存先: -")
        ttk.Label(top_frame, textvariable=self._dir_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(top_frame, text="保存先変更…", command=self._change_dir, width=12).pack(
            side=tk.RIGHT
        )

        tree_frame = ttk.Frame(main)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("name", "created_at", "size", "comment")
        self._tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")
        for cid, text, w in [
            ("name", "ディストリビューション", 160),
            ("created_at", "作成日時", 140),
            ("size", "サイズ", 90),
            ("comment", "コメント", 220),
        ]:
            self._tree.heading(cid, text=text)
            self._tree.column(cid, width=w, minwidth=60, anchor=tk.W)
        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        bottom = ttk.Frame(main)
        bottom.pack(fill=tk.X, pady=(8, 0))
        self._total_var = tk.StringVar(value="合計: 0 B (0 件)")
        ttk.Label(bottom, textvariable=self._total_var).pack(side=tk.LEFT)

        ttk.Button(bottom, text="閉じる", command=self.destroy, width=10).pack(
            side=tk.RIGHT, padx=(4, 0)
        )
        ttk.Button(bottom, text="更新", command=self._reload, width=10).pack(
            side=tk.RIGHT, padx=(4, 0)
        )
        ttk.Button(bottom, text="フォルダを開く", command=self._open_folder, width=13).pack(
            side=tk.RIGHT, padx=(4, 0)
        )
        ttk.Button(bottom, text="保存先変更...", command=self._change_snapshot_dir, width=13).pack(
            side=tk.RIGHT, padx=(4, 0)
        )
        ttk.Button(bottom, text="削除", command=self._delete_snapshot, width=10).pack(
            side=tk.RIGHT, padx=(4, 0)
        )
        ttk.Button(bottom, text="復元...", command=self._restore_snapshot, width=10).pack(
            side=tk.RIGHT, padx=(4, 0)
        )

    def _change_dir(self) -> None:
        """スナップショット保存先ディレクトリを変更します。"""
        current = self._parent._snapshot_dir()
        new_dir = filedialog.askdirectory(
            parent=self,
            title="スナップショット保存先フォルダの選択",
            initialdir=current,
        )
        if not new_dir:
            return
        self._parent._settings["snapshot_dir"] = os.path.abspath(new_dir)
        self._parent._save_settings()
        self._reload()

    def _reload(self) -> None:
        """スナップショット一覧を保存先ディレクトリから再読込してツリーに反映します。"""
        snap_dir = self._parent._snapshot_dir()
        self._dir_var.set(f"保存先: {snap_dir}")
        self._snapshots = wsl_core.load_snapshots(snap_dir)

        for item in self._tree.get_children():
            self._tree.delete(item)

        for idx, snap in enumerate(self._snapshots):
            created = str(snap.get("created_at", "")).replace("T", " ")
            if snap.get("tar_exists", True):
                size_text = wsl_core.format_bytes(snap.get("size_bytes", 0))
            else:
                size_text = "(tar なし)"
            self._tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(
                    snap.get("distro_name", ""),
                    created,
                    size_text,
                    snap.get("comment", ""),
                ),
            )

        total = wsl_core.total_snapshots_size(self._snapshots)
        self._total_var.set(f"合計: {wsl_core.format_bytes(total)} ({len(self._snapshots)} 件)")

    def _selected_snapshot(self) -> dict | None:
        sel = self._tree.selection()
        if not sel:
            return None
        idx = int(sel[0])
        if 0 <= idx < len(self._snapshots):
            return self._snapshots[idx]
        return None

    def _restore_snapshot(self) -> None:
        """選択したスナップショットを新しいディストリビューションとして復元します。"""
        snap = self._selected_snapshot()
        if snap is None:
            messagebox.showwarning("警告", "スナップショットを選択してください。", parent=self)
            return
        if not snap.get("tar_exists", True):
            messagebox.showwarning(
                "警告", "tar ファイルが見つかりません。復元できません。", parent=self
            )
            return

        distro_name = snap.get("distro_name", "")
        tar_path = snap.get("tar_path", "")

        existing = [d["name"] for d in self._parent._all_distros]
        new_name = simpledialog.askstring(
            "復元",
            "復元先のディストリビューション名を入力してください。",
            initialvalue=wsl_core.default_clone_name(distro_name, existing),
            parent=self,
        )
        if new_name is None:
            return
        new_name = new_name.strip()
        valid, reason = wsl_core.validate_distro_name(new_name)
        if not valid:
            messagebox.showwarning("警告", reason, parent=self)
            return
        existing_casefold = {n.casefold() for n in existing}
        if new_name.casefold() in existing_casefold:
            messagebox.showwarning(
                "警告", "同名のディストリビューションが既に存在します。", parent=self
            )
            return

        install_path = filedialog.askdirectory(title="インストール先フォルダを選択", parent=self)
        if not install_path:
            return

        version = snap.get("wsl_version") or "2"

        if not messagebox.askyesno(
            "確認",
            (
                "次の内容で復元します。\n\n"
                f"名前: {new_name}\n"
                f"スナップショット: {os.path.basename(tar_path)}\n"
                f"保存先: {install_path}\n"
                f"バージョン: WSL{version}"
            ),
            parent=self,
        ):
            return

        # 入力 tar のサイズを分母に、インストール先 ext4.vhdx の成長を監視する
        total_bytes: int | None = None
        watch_path: str | None = None
        if version == "2":
            try:
                total_bytes = os.path.getsize(tar_path)
            except OSError:
                total_bytes = None
            watch_path = os.path.join(install_path, "ext4.vhdx")

        parent = self._parent
        parent._log_operation("スナップショット復元", new_name, tar_path)
        parent._set_status(f"「{new_name}」へ復元中…")

        def _on_done(returncode: int, stderr_text: str, cancelled: bool) -> None:
            if cancelled:
                parent._log_operation("スナップショット復元", new_name, "キャンセル")
                parent._set_status(f"「{new_name}」への復元をキャンセルしました。")
                if messagebox.askyesno(
                    "確認",
                    (
                        "復元を中断したため、不完全な登録が残っている\n"
                        f"可能性があります。「{new_name}」の登録を解除しますか？"
                    ),
                    parent=parent,
                ):
                    parent._run_wsl_cmd(
                        ["--unregister", new_name],
                        f"「{new_name}」の登録を解除しました。",
                        f"「{new_name}」の登録解除に失敗しました。",
                    )
                    return
            elif returncode == 0:
                parent._set_status(f"「{new_name}」に復元しました。")
            else:
                parent._set_status(stderr_text or f"「{new_name}」への復元に失敗しました。")
            parent._refresh()

        # 親をメインウィンドウにする。管理ダイアログを親にすると、復元中に
        # 管理ダイアログを閉じた場合に進捗ダイアログごと破棄されてしまう。
        TransferProgressDialog(
            parent,
            "スナップショット復元",
            f"「{new_name}」へ復元中…",
            ["--import", new_name, install_path, tar_path, "--version", version],
            watch_path,
            total_bytes,
            _on_done,
        )

    def _delete_snapshot(self) -> None:
        """選択したスナップショットの tar / JSON ファイルを削除します。"""
        snap = self._selected_snapshot()
        if snap is None:
            messagebox.showwarning("警告", "スナップショットを選択してください。", parent=self)
            return

        distro_name = snap.get("distro_name", "")
        created = str(snap.get("created_at", "")).replace("T", " ")
        tar_file = snap.get("tar_file", "")

        if not messagebox.askyesno(
            "削除確認",
            (
                "次のスナップショットを削除します。この操作は取り消せません。\n\n"
                f"ディストリビューション: {distro_name}\n"
                f"作成日時: {created}\n"
                f"ファイル: {tar_file}"
            ),
            parent=self,
        ):
            return

        errors: list[str] = []
        tar_path = snap.get("tar_path", "")
        json_path = snap.get("json_path", "")
        if snap.get("tar_exists", True) and tar_path:
            try:
                os.remove(tar_path)
            except OSError as e:
                errors.append(str(e))
        if json_path:
            try:
                os.remove(json_path)
            except OSError as e:
                errors.append(str(e))

        if errors:
            messagebox.showerror("エラー", "削除に失敗しました:\n" + "\n".join(errors), parent=self)

        self._parent._log_operation("スナップショット削除", distro_name, tar_file)
        self._reload()

    def _open_folder(self) -> None:
        """スナップショット保存先フォルダをエクスプローラーで開きます。"""
        snap_dir = self._parent._snapshot_dir()
        try:
            os.makedirs(snap_dir, exist_ok=True)
        except OSError as e:
            messagebox.showerror("エラー", str(e), parent=self)
            return

        if not hasattr(os, "startfile"):
            messagebox.showinfo("情報", "この機能は Windows でのみ利用できます。", parent=self)
            return
        try:
            os.startfile(snap_dir)  # type: ignore[attr-defined]
        except OSError as e:
            messagebox.showerror("エラー", str(e), parent=self)

    def _change_snapshot_dir(self) -> None:
        """#17: スナップショットの保存先ディレクトリを変更します。"""
        current_dir = self._parent._snapshot_dir()
        new_dir = filedialog.askdirectory(
            title="スナップショット保存先フォルダを選択",
            initialdir=current_dir if os.path.isdir(current_dir) else None,
            parent=self,
        )
        if not new_dir:
            return
        self._parent._settings["snapshot_dir"] = new_dir
        self._parent._save_settings()
        self._reload()


class WSLManager(tk.Tk):
    """WSL2 ディストリビューション管理メインウィンドウ。"""

    # 状態の日本語表示マッピング
    STATE_JP: ClassVar[dict[str, str]] = {"Running": "実行中", "Stopped": "停止中"}

    # リソース使用量(CPU/メモリ)取得のタイムアウト秒数。
    # VM 初期化直後や、ログインシェルの起動が重い/プロセス数が多い
    # ディストリビューションでは 2 秒では応答が返らないことがあるため、
    # 余裕を持たせた値にしている。
    RESOURCE_QUERY_TIMEOUT = 8.0

    # IP アドレス取得のタイムアウト秒数。理由は RESOURCE_QUERY_TIMEOUT と同様
    # (VM 初期化直後 / ログインシェルが重い / プロセス数が多い場合に備える)。
    IP_QUERY_TIMEOUT = 8.0

    def __init__(self) -> None:
        super().__init__()
        self.title("WSL Manager")
        self.geometry("780x500")
        self.resizable(True, True)
        self.minsize(640, 400)

        self._refresh_job: str | None = None
        self._refresh_in_progress = False
        self._refresh_pending = False
        self._process_windows: dict[str, ProcessWindow] = {}
        self._transfer_dialogs: list[TransferProgressDialog] = []
        self._all_distros: list[dict] = []
        self._resource_history = wsl_core.ResourceHistory()
        self._resource_history_visible = False
        self._history_layouts: dict[str, wsl_core.ChartLayout] = {}
        self._operation_log: list[str] = []
        self._log_dir = wsl_core.get_default_log_dir()
        self._log_file = os.path.join(self._log_dir, "operations.jsonl")
        # ログ書き込みは Tk のイベントループを塞がないよう専用スレッドに委譲する
        self._log_writer = wsl_core.AsyncLogWriter(self._log_dir)
        # #35: ログ書き込みキューの溢れ/書き込み失敗を一度だけステータスバーに通知するためのフラグ
        self._log_writer_warning_shown = False
        self._load_persisted_log()
        self._settings_path = wsl_core.get_default_settings_path()
        self._settings = wsl_core.load_settings(self._settings_path)
        self._language = wsl_core.resolve_language(self._settings["language"])
        if self._settings["window_geometry"]:
            try:
                self.geometry(self._settings["window_geometry"])
            except tk.TclError:
                pass
        self._filter_var = tk.StringVar()
        self._setup_theme()
        self._build_ui()
        self._filter_var.trace_add("write", lambda *_: self._render_distros())
        if self._settings["auto_refresh"]:
            self._schedule_auto_refresh()
        else:
            self._refresh()

    # ── UI 構築 ──────────────────────────────────────────────────────────────

    def _t(self, key: str, **values: object) -> str:
        """Translate text used by the main application shell."""
        return wsl_core.translate(key, self._language, **values)

    def _setup_theme(self) -> None:
        """利用可能な ttk テーマを検出し、デフォルトテーマを設定します。"""
        style = ttk.Style(self)
        self._available_themes = sorted(style.theme_names())
        self._current_theme = style.theme_use()
        saved_theme = self._settings["theme"]
        if saved_theme and saved_theme in self._available_themes:
            try:
                style.theme_use(saved_theme)
                self._current_theme = saved_theme
            except tk.TclError:
                pass

    def _build_ui(self) -> None:
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        self._build_menubar()
        self._build_toolbar(main_frame)
        self._build_treeview(main_frame)
        self._build_resource_history_panel(main_frame)
        self._build_statusbar(main_frame)

    def _build_menubar(self) -> None:
        """メニューバーを構築してウィンドウに設定します。"""
        menubar = tk.Menu(self)

        # ── ファイル ──
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(
            label=self._t("gui.action.import"),
            command=self._import_distro_image,
            accelerator="Ctrl+I",
        )
        file_menu.add_command(
            label=self._t("gui.action.export"),
            command=self._export_distro_image,
            accelerator="Ctrl+E",
        )
        file_menu.add_separator()
        file_menu.add_command(
            label=self._t("gui.action.exit"),
            command=self.on_closing,
            accelerator="Alt+F4",
        )
        menubar.add_cascade(label=self._t("gui.menu.file"), menu=file_menu)

        # ── ディストリビューション ──
        distro_menu = tk.Menu(menubar, tearoff=0)
        distro_menu.add_command(
            label=self._t("gui.action.start_terminal"),
            command=self._open_terminal,
            accelerator="Return",
        )
        distro_menu.add_command(
            label=self._t("gui.action.stop"),
            command=self._stop_distro,
            accelerator="Delete",
        )
        distro_menu.add_command(
            label=self._t("gui.action.shutdown"),
            command=self._shutdown_all,
            accelerator="Ctrl+Shift+Q",
        )
        distro_menu.add_separator()
        distro_menu.add_command(
            label=self._t("gui.action.set_default"),
            command=self._set_default,
        )
        distro_menu.add_command(
            label=self._t("gui.action.convert"),
            command=self._convert_version,
        )
        distro_menu.add_separator()
        distro_menu.add_command(
            label=self._t("gui.action.install"),
            command=self._install_distro,
        )
        distro_menu.add_command(
            label=self._t("gui.action.unregister"),
            command=self._uninstall_distro,
        )
        menubar.add_cascade(label=self._t("gui.menu.distribution"), menu=distro_menu)

        # ── ツール ──
        tools_menu = tk.Menu(menubar, tearoff=0)
        tools_menu.add_command(
            label=self._t("gui.action.details"),
            command=self._show_detail,
            accelerator="Ctrl+D",
        )
        tools_menu.add_command(
            label=self._t("gui.action.processes"),
            command=self._show_processes,
            accelerator="Ctrl+P",
        )
        tools_menu.add_command(
            label=self._t("gui.action.explorer"),
            command=self._open_in_explorer,
        )
        tools_menu.add_command(
            label=self._t("gui.action.optimize"),
            command=self._open_disk_optimize,
        )
        tools_menu.add_command(
            label=self._t("gui.action.snapshots"),
            command=self._open_snapshot_manager,
        )
        tools_menu.add_command(
            label="WSL Containers...",
            command=self._open_container_manager,
        )
        tools_menu.add_separator()
        tools_menu.add_command(
            label=self._t("gui.action.mount"),
            command=self._open_mount,
        )
        tools_menu.add_command(
            label=self._t("gui.action.unmount"),
            command=self._open_unmount,
        )
        tools_menu.add_separator()
        tools_menu.add_command(
            label=self._t("gui.action.wsl_config"),
            command=self._open_wslconfig,
            accelerator="Ctrl+,",
        )
        tools_menu.add_command(
            label=self._t("gui.action.log"),
            command=self._show_log_viewer,
            accelerator="Ctrl+L",
        )
        tools_menu.add_separator()
        self._theme_var = tk.StringVar(value=self._current_theme)
        theme_menu = tk.Menu(tools_menu, tearoff=0)
        for theme_name in self._available_themes:
            theme_menu.add_radiobutton(
                label=theme_name,
                variable=self._theme_var,
                value=theme_name,
                command=lambda t=theme_name: self._change_theme(t),
            )
        tools_menu.add_cascade(label=self._t("gui.action.theme"), menu=theme_menu)
        language_menu = tk.Menu(tools_menu, tearoff=0)
        self._language_var = tk.StringVar(value=self._settings["language"])
        for language in (wsl_core.LANGUAGE_AUTO, *wsl_core.SUPPORTED_LANGUAGES):
            language_menu.add_radiobutton(
                label=self._t(f"language.{language}"),
                variable=self._language_var,
                value=language,
                command=lambda value=language: self._change_language(value),
            )
        tools_menu.add_cascade(label=self._t("gui.menu.language"), menu=language_menu)
        menubar.add_cascade(label=self._t("gui.menu.tools"), menu=tools_menu)

        # ── ヘルプ ──
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(
            label=self._t("gui.action.wsl_version"),
            command=self._show_wsl_version,
        )
        help_menu.add_command(
            label=self._t("gui.action.update_wsl"),
            command=self._update_wsl,
        )
        help_menu.add_command(
            label=self._t("gui.action.about"),
            command=self._show_about,
        )
        menubar.add_cascade(label=self._t("gui.menu.help"), menu=help_menu)

        self.config(menu=menubar)

        # ── キーボードショートカット ──
        self.bind_all("<Control-r>", lambda e: self._refresh())
        self.bind_all("<Control-i>", lambda e: self._import_distro_image())
        self.bind_all("<Control-e>", lambda e: self._export_distro_image())
        self.bind_all("<Control-d>", lambda e: self._show_detail())
        self.bind_all("<Control-p>", lambda e: self._show_processes())
        self.bind_all("<Control-comma>", lambda e: self._open_wslconfig())
        self.bind_all("<Control-l>", lambda e: self._show_log_viewer())
        self.bind_all(
            "<Delete>",
            lambda e: (
                self._stop_distro() if not isinstance(e.widget, (tk.Entry, ttk.Entry)) else None
            ),
        )
        self.bind_all("<Control-Shift-Q>", lambda e: self._shutdown_all())
        self.bind_all("<F5>", lambda e: self._refresh())

    def _build_toolbar(self, parent: ttk.Frame) -> None:
        """主要操作と補助操作を2段に分け、狭い画面でも表示を保ちます。"""
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill=tk.X, pady=(0, 8))

        primary_row = ttk.Frame(toolbar)
        primary_row.pack(fill=tk.X)

        primary_actions = [
            (self._t("gui.toolbar.start"), self._start_distro, 8),
            (self._t("gui.toolbar.stop"), self._stop_distro, 8),
            (self._t("gui.toolbar.shutdown"), self._shutdown_all, 11),
            (self._t("gui.toolbar.terminal"), self._open_terminal, 11),
            (self._t("gui.toolbar.processes"), self._show_processes, 11),
        ]
        for index, (label, cmd, width) in enumerate(primary_actions):
            if index == 3:
                ttk.Separator(primary_row, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=6, fill=tk.Y)
            ttk.Button(primary_row, text=label, command=cmd, width=width).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            primary_row,
            text=self._t("gui.toolbar.refresh"),
            command=self._refresh,
            width=10,
        ).pack(side=tk.RIGHT, padx=2)

        secondary_row = ttk.Frame(toolbar)
        secondary_row.pack(fill=tk.X, pady=(4, 0))

        secondary_actions = [
            (self._t("gui.toolbar.install"), self._install_distro, 12),
            (self._t("gui.toolbar.import"), self._import_distro_image, 10),
            (self._t("gui.toolbar.export"), self._export_distro_image, 10),
            (self._t("gui.toolbar.wsl_config"), self._open_wslconfig, 13),
        ]
        for label, cmd, width in secondary_actions:
            ttk.Button(secondary_row, text=label, command=cmd, width=width).pack(
                side=tk.LEFT, padx=2
            )

        self._auto_refresh_var = tk.BooleanVar(value=self._settings["auto_refresh"])
        ttk.Checkbutton(
            secondary_row,
            text=self._t("gui.auto_refresh"),
            variable=self._auto_refresh_var,
            command=self._toggle_auto_refresh,
        ).pack(side=tk.LEFT, padx=(8, 4))

        ttk.Label(secondary_row, text="🔍").pack(side=tk.LEFT, padx=(4, 2))
        ttk.Entry(secondary_row, textvariable=self._filter_var, width=12).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            secondary_row,
            text="✕",
            width=2,
            command=lambda: self._filter_var.set(""),
        ).pack(side=tk.LEFT, padx=2)
        self._history_toggle = ttk.Button(
            secondary_row,
            text=self._t("gui.history.show"),
            command=self._toggle_resource_history,
        )
        self._history_toggle.pack(side=tk.RIGHT, padx=2)

    def _build_treeview(self, parent: ttk.Frame) -> None:
        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("default", "name", "state", "version", "cpu", "memory", "disk", "ip")
        self._tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")

        self._tree.heading("default", text="")
        self._tree.heading("name", text=self._t("gui.column.name"))
        self._tree.heading("state", text=self._t("gui.column.state"))
        self._tree.heading("version", text=self._t("gui.column.version"))
        self._tree.heading("cpu", text="CPU(%)")
        self._tree.heading("memory", text=self._t("gui.column.memory"))
        self._tree.heading("disk", text=self._t("gui.column.disk"))
        self._tree.heading("ip", text=self._t("gui.column.ip"))

        self._tree.column("default", width=26, minwidth=26, anchor=tk.CENTER)
        self._tree.column("name", width=180, minwidth=120)
        self._tree.column("state", width=80, minwidth=70, anchor=tk.CENTER)
        self._tree.column("version", width=70, minwidth=65, anchor=tk.CENTER)
        self._tree.column("cpu", width=70, minwidth=60, anchor=tk.CENTER)
        self._tree.column("memory", width=85, minwidth=75, anchor=tk.CENTER)
        self._tree.column("disk", width=85, minwidth=75, anchor=tk.CENTER)
        self._tree.column("ip", width=120, minwidth=95)

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self._tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        # ダブルクリックでターミナルを開く
        self._tree.bind("<Double-1>", lambda _e: self._open_terminal())

        # Enter キーでもダブルクリックと同じ動作にする（メニューの
        # accelerator="Return" 表示に合わせる）。フィルタ入力欄で
        # Enter を打っても誤発火しないよう、bind_all ではなく
        # Treeview ウィジェットに直接バインドする。
        self._tree.bind("<Return>", self._on_tree_return)

        # 右クリックコンテキストメニュー
        self._tree.bind("<Button-3>", self._show_context_menu)

        # 状態による行の色分け
        self._tree.tag_configure("running", foreground="#1a7a1a")
        self._tree.tag_configure("stopped", foreground="#888888")

        # 列クリックソート
        self._sorter = TreeviewSorter(self._tree, numeric_columns={"cpu", "memory", "disk"})
        self._sorter.set_state(self._settings["sort_column"], self._settings["sort_desc"])

    def _build_statusbar(self, parent: ttk.Frame) -> None:
        self._status_var = tk.StringVar(value=self._t("gui.status.ready"))
        self._statusbar = ttk.Label(
            parent,
            textvariable=self._status_var,
            relief=tk.SUNKEN,
            anchor=tk.W,
            padding=(4, 2),
        )
        self._statusbar.pack(fill=tk.X, pady=(8, 0))

    def _build_resource_history_panel(self, parent: ttk.Frame) -> None:
        """CPU とメモリの最近30分の推移を表示する、折りたたみ可能なパネル。"""
        self._history_frame = ttk.Labelframe(parent, text="リソース履歴（直近30分）")
        self._cpu_history_canvas = tk.Canvas(
            self._history_frame, height=130, highlightthickness=0, background="white"
        )
        self._memory_history_canvas = tk.Canvas(
            self._history_frame, height=130, highlightthickness=0, background="white"
        )
        ttk.Label(self._history_frame, text="CPU 使用率").pack(anchor=tk.W, padx=6, pady=(4, 0))
        self._cpu_history_canvas.pack(fill=tk.X, padx=6)
        ttk.Label(self._history_frame, text="メモリ使用量").pack(anchor=tk.W, padx=6, pady=(2, 0))
        self._memory_history_canvas.pack(fill=tk.X, padx=6, pady=(0, 4))
        for canvas, metric in (
            (self._cpu_history_canvas, "cpu"),
            (self._memory_history_canvas, "memory"),
        ):
            canvas.bind("<Configure>", lambda _event: self._draw_resource_history())
            canvas.bind(
                "<Motion>",
                lambda event, c=canvas, m=metric: self._on_history_canvas_motion(c, m, event),
            )
            canvas.bind("<Leave>", lambda _event, c=canvas: self._clear_history_tooltip(c))

    def _toggle_resource_history(self) -> None:
        self._resource_history_visible = not self._resource_history_visible
        if self._resource_history_visible:
            self._history_frame.pack(fill=tk.X, pady=(6, 0), before=self._statusbar)
            self._history_toggle.configure(text="📈 履歴を隠す")
            self._draw_resource_history()
        else:
            self._clear_history_tooltip(self._cpu_history_canvas)
            self._clear_history_tooltip(self._memory_history_canvas)
            self._history_frame.pack_forget()
            self._history_toggle.configure(text="📈 履歴を表示")

    def _draw_resource_history(self) -> None:
        if not self._resource_history_visible:
            return
        self._draw_history_canvas(self._cpu_history_canvas, "cpu")
        self._draw_history_canvas(self._memory_history_canvas, "memory")

    def _draw_history_canvas(self, canvas: tk.Canvas, metric: str) -> None:
        """Canvas に1メトリックの系列・軸・凡例を安全に描画します。"""
        canvas.delete("all")
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width <= 2 or height <= 2:
            self._history_layouts.pop(str(canvas), None)
            return
        layout = wsl_core.prepare_chart_layout(self._resource_history, metric, width, height)
        self._history_layouts[str(canvas)] = layout
        for tick in layout.y_ticks:
            canvas.create_line(layout.plot_x0, tick.pos, layout.plot_x1, tick.pos, fill="#e6e6e6")
            canvas.create_text(
                layout.plot_x0 - 4, tick.pos, text=tick.label, anchor=tk.E, fill="#555"
            )
        for tick in layout.x_ticks:
            canvas.create_line(tick.pos, layout.plot_y0, tick.pos, layout.plot_y1, fill="#f0f0f0")
            canvas.create_text(
                tick.pos,
                layout.plot_y1 + 12,
                text=tick.label,
                anchor=tk.N,
                fill="#555",
            )
        canvas.create_rectangle(
            layout.plot_x0, layout.plot_y0, layout.plot_x1, layout.plot_y1, outline="#bdbdbd"
        )
        for series in layout.series:
            for segment in series.segments:
                if len(segment) > 1:
                    coordinates = [coordinate for point in segment for coordinate in point]
                    canvas.create_line(*coordinates, fill=series.color, width=2)
                elif segment:
                    x, y = segment[0]
                    canvas.create_oval(x - 2, y - 2, x + 2, y + 2, fill=series.color, outline="")
        if layout.empty:
            canvas.create_text(
                (layout.plot_x0 + layout.plot_x1) / 2,
                (layout.plot_y0 + layout.plot_y1) / 2,
                text="有効な履歴データはありません",
                fill="#666",
            )
        legend_x = layout.plot_x0 + 6
        for series in layout.series:
            canvas.create_line(
                legend_x,
                layout.plot_y0 + 8,
                legend_x + 12,
                layout.plot_y0 + 8,
                fill=series.color,
                width=2,
            )
            canvas.create_text(
                legend_x + 16,
                layout.plot_y0 + 8,
                text=series.name,
                anchor=tk.W,
                fill="#333",
            )
            legend_x += 22 + len(series.name) * 7

    def _on_history_canvas_motion(self, canvas: tk.Canvas, metric: str, event: tk.Event) -> None:
        """Show the nearest resource-history observation while the cursor is over a graph."""
        layout = self._history_layouts.get(str(canvas))
        if not self._resource_history_visible or layout is None:
            return
        nearest = wsl_core.find_nearest_chart_point(layout, event.x, event.y)
        if nearest is None:
            self._clear_history_tooltip(canvas)
            return
        series, point = nearest
        self._draw_history_tooltip(canvas, metric, series, point, event.x, event.y)

    @staticmethod
    def _resource_value_label(metric: str, value: float) -> str:
        """Format an exact sampled value for a resource-history tooltip."""
        return f"{value:.1f}%" if metric == "cpu" else f"{value:.1f} MB"

    def _draw_history_tooltip(
        self,
        canvas: tk.Canvas,
        metric: str,
        series: wsl_core.ChartSeries,
        point: wsl_core.ChartPoint,
        cursor_x: float,
        cursor_y: float,
    ) -> None:
        self._clear_history_tooltip(canvas)
        timestamp = datetime.fromtimestamp(point.timestamp).strftime("%Y-%m-%d %H:%M:%S")
        value = self._resource_value_label(metric, point.value)
        label = f"{series.name}\n{timestamp}\n{value}"
        text_item = canvas.create_text(
            cursor_x + 12,
            cursor_y - 12,
            text=label,
            anchor=tk.SW,
            justify=tk.LEFT,
            fill="#111",
            tags="history-tooltip",
        )
        bbox = canvas.bbox(text_item)
        if bbox is None:
            return
        width, height = canvas.winfo_width(), canvas.winfo_height()
        dx = max(4 - bbox[0], min(0, width - 4 - bbox[2]))
        dy = max(4 - bbox[1], min(0, height - 4 - bbox[3]))
        if dx or dy:
            canvas.move(text_item, dx, dy)
        bbox = canvas.bbox(text_item)
        if bbox is not None:
            rectangle = canvas.create_rectangle(
                bbox[0] - 4,
                bbox[1] - 3,
                bbox[2] + 4,
                bbox[3] + 3,
                fill="#ffffe0",
                outline="#777",
                tags="history-tooltip",
            )
            canvas.tag_lower(rectangle, text_item)
        canvas.create_oval(
            point.x - 4,
            point.y - 4,
            point.x + 4,
            point.y + 4,
            outline=series.color,
            width=2,
            tags="history-tooltip",
        )

    @staticmethod
    def _clear_history_tooltip(canvas: tk.Canvas) -> None:
        canvas.delete("history-tooltip")

    # ── ディストリビューション情報取得 ─────────────────────────────────────

    def _get_distro_resource_usage(self, name: str) -> tuple[str, str]:
        """指定ディストリビューションのCPU使用率(%)とメモリ使用量(MB)を返します。"""
        try:
            result = subprocess.run(
                [
                    "wsl",
                    "-d",
                    name,
                    "--",
                    "sh",
                    "-lc",
                    (
                        "ps -eo pcpu=,rss= | "
                        "awk '{cpu+=$1; mem+=$2} END {printf \"%.1f %.1f\", cpu, mem/1024}'"
                    ),
                ],
                capture_output=True,
                creationflags=CREATE_NO_WINDOW,
                timeout=self.RESOURCE_QUERY_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired):
            return "-", "-"

        if result.returncode != 0:
            return "-", "-"

        output = wsl_core.decode_wsl_output(result.stdout).strip()
        return wsl_core.parse_resource_usage(output)

    def _get_distro_ip(self, name: str) -> str:
        """指定ディストリビューションの IP アドレスを返します。"""
        try:
            result = subprocess.run(
                ["wsl", "-d", name, "--", "hostname", "-I"],
                capture_output=True,
                creationflags=CREATE_NO_WINDOW,
                timeout=self.IP_QUERY_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired):
            return "-"
        if result.returncode != 0:
            return "-"
        output = wsl_core.decode_wsl_output(result.stdout).strip()
        ips = wsl_core.parse_ip_addresses(output)
        return ips[0] if ips else "-"

    def _get_distros(self) -> tuple[list[dict], str | None]:
        """``wsl --list --verbose`` を解析し、必要に応じてリソース情報も取得します。

        Returns:
            (distros, error_message) のタプル。
            成功時は distros にリストが入り error_message は None。
            失敗時は distros は空リストで error_message にメッセージが入ります。
        """
        try:
            result = subprocess.run(
                ["wsl", "--list", "--verbose"],
                capture_output=True,
                creationflags=CREATE_NO_WINDOW,
                timeout=15.0,
            )
        except subprocess.TimeoutExpired:
            return [], "WSL の応答がタイムアウトしました。"
        except FileNotFoundError:
            return [], "wsl.exe が見つかりません。WSL2 がインストールされているか確認してください。"
        except OSError as e:
            return [], f"WSL の実行に失敗しました: {e}"

        if result.returncode != 0:
            stderr = wsl_core.decode_wsl_output(result.stderr).strip()
            return [], stderr or "ディストリビューション一覧の取得に失敗しました。"

        output = wsl_core.decode_wsl_output(result.stdout)
        distros: list[dict] = wsl_core.parse_distro_list(output)

        # レジストリから仮想ディスク (ext4.vhdx) のサイズを取得する
        disk_sizes = _get_distro_vhdx_sizes()
        for d in distros:
            size = disk_sizes.get(d["name"])
            if size is not None:
                d["disk"] = f"{size:.1f}"

        # Running のディストロのリソース使用量を並列取得する
        running_distros = [d for d in distros if d["state"] == "Running"]
        if running_distros:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                future_to_distro = {
                    executor.submit(self._get_distro_resource_usage, d["name"]): d
                    for d in running_distros
                }
                for future in concurrent.futures.as_completed(future_to_distro):
                    distro = future_to_distro[future]
                    try:
                        cpu, memory = future.result()
                    except Exception:
                        # 1 ディストロの取得失敗で一覧更新全体を止めない。原因はデバッグログに残す。
                        logger.debug(
                            "リソース使用量の取得に失敗: %s", distro["name"], exc_info=True
                        )
                        cpu, memory = "-", "-"
                    distro["cpu"] = cpu
                    distro["memory"] = memory

                ip_future_to_distro = {
                    executor.submit(self._get_distro_ip, d["name"]): d for d in running_distros
                }
                for future in concurrent.futures.as_completed(ip_future_to_distro):
                    distro = ip_future_to_distro[future]
                    try:
                        distro["ip"] = future.result()
                    except Exception:
                        logger.debug("IP アドレスの取得に失敗: %s", distro["name"], exc_info=True)
                        distro["ip"] = "-"

        return distros, None

    # ── ツリービュー更新 ──────────────────────────────────────────────────

    def _refresh(self) -> None:
        if self._refresh_in_progress:
            self._refresh_pending = True
            return

        selected = self._selected_name()
        self._refresh_in_progress = True
        self._set_status("更新中…")

        def _run() -> None:
            distros, err = self._get_distros()
            self._call_soon_safe(lambda: self._apply_refresh_result(distros, err, selected))

        threading.Thread(target=_run, daemon=True).start()

    def _apply_refresh_result(
        self, distros: list[dict], err: str | None, selected: str | None
    ) -> None:
        if err:
            self._set_status(err)
            self._refresh_in_progress = False
            if self._refresh_pending:
                self._refresh_pending = False
                self._refresh()
            return

        self._all_distros = distros
        self._resource_history.record_refresh(distros)
        self._render_distros(selected)
        self._draw_resource_history()

        count = len(distros)
        running = sum(1 for d in distros if d["state"] == "Running")

        # フィルタが適用されている場合はフィルタ後の件数を追記
        filter_text = self._filter_var.get().strip().casefold()
        if filter_text:
            filtered_count = sum(1 for d in distros if filter_text in d["name"].casefold())
            self._set_status(
                f"ディストリビューション数: {count}  "
                f"(実行中: {running} / 停止中: {count - running})"
                f"  （フィルタ表示: {filtered_count} 件）"
            )
        else:
            self._set_status(
                f"ディストリビューション数: {count}  "
                f"(実行中: {running} / 停止中: {count - running})"
            )

        self._refresh_in_progress = False
        if self._refresh_pending:
            self._refresh_pending = False
            self._refresh()
        self._check_log_writer_health()

    def _render_distros(self, selected: str | None = None) -> None:
        """フィルタを適用してツリービューを再描画します。

        ``self._all_distros`` のみを参照し、subprocess 等の重い処理は行いません。
        フィルタ入力のたびに呼ばれるため、軽量に保つこと。
        """
        # 引数が省略された場合は現在の選択名を維持する
        if selected is None:
            selected = self._selected_name()

        # 全行削除
        for item in self._tree.get_children():
            self._tree.delete(item)

        filter_text = self._filter_var.get().strip().casefold()

        select_iid: str | None = None
        for d in self._all_distros:
            if filter_text and filter_text not in d["name"].casefold():
                continue
            default_mark = "★" if d["default"] else ""
            state_jp = (
                self.STATE_JP.get(d["state"], d["state"]) if self._language == "ja" else d["state"]
            )
            version_str = f"WSL{d['version']}" if d["version"] else ""
            tag = "running" if d["state"] == "Running" else "stopped"
            iid = self._tree.insert(
                "",
                tk.END,
                values=(
                    default_mark,
                    d["name"],
                    state_jp,
                    version_str,
                    d["cpu"],
                    d["memory"],
                    d["disk"],
                    d.get("ip", "-"),
                ),
                tags=(tag,),
            )
            if d["name"] == selected:
                select_iid = iid

        # ソート状態を再適用
        self._sorter.apply()

        # 直前の選択を復元、なければ先頭を選択
        if select_iid:
            self._tree.selection_set(select_iid)
            self._tree.see(select_iid)
        elif self._tree.get_children():
            self._tree.selection_set(self._tree.get_children()[0])

    def _selected_name(self) -> str | None:
        sel = self._tree.selection()
        if not sel:
            return None
        values = self._tree.item(sel[0])["values"]
        return str(values[1]) if values else None

    def _set_status(self, msg: str) -> None:
        self._status_var.set(msg)

    def _check_log_writer_health(self) -> None:
        """#35: ログ書き込みのキュー溢れ/失敗を検知し、初回のみステータスバーに警告表示します。

        定期更新 (自動更新タイマー / 手動更新) のタイミングで呼び出す想定です。
        メインスレッドから ``self._log_writer`` のプロパティを読むだけなので、
        既存の GUI 更新パターン (メインスレッドから触る) を踏襲しています。
        """
        if self._log_writer_warning_shown:
            return
        dropped = self._log_writer.dropped_count
        write_errors = self._log_writer.write_error_count
        if dropped > 0 or write_errors > 0:
            self._log_writer_warning_shown = True
            self._set_status(
                "警告: 操作ログの書き込みに問題が発生しています"
                f"（キュー溢れによる破棄: {dropped} 件 / 書き込み失敗: {write_errors} 件）"
            )

    def _call_soon_safe(self, fn: callable) -> None:
        """バックグラウンドスレッドから UI 更新を安全にスケジュールします。

        長時間コマンドの実行中にウィンドウが閉じられると ``self`` は destroy
        済みになり、素の ``after(0, ...)`` は ``tk.TclError`` を送出します。
        スレッド内での例外は誰も捕まえないため、スケジュール時と実行時の
        両方をここでガードします。ウィンドウが既に無い場合は黙って捨てます。
        """

        def _guarded() -> None:
            try:
                if self.winfo_exists():
                    fn()
            except tk.TclError:
                pass

        try:
            self.after(0, _guarded)
        except (tk.TclError, RuntimeError):
            # destroy 済み、または mainloop 終了後にスケジュールしようとした場合
            pass

    def _set_status_safe(self, msg: str) -> None:
        """バックグラウンドスレッドからステータスバーを更新します。"""
        self._call_soon_safe(lambda: self._set_status(msg))

    # ── 操作ログ ─────────────────────────────────────────────────────────

    def _load_persisted_log(self) -> None:
        """ログファイルから過去の操作ログを読み込みます。"""
        try:
            if os.path.exists(self._log_file):
                with open(self._log_file, encoding="utf-8") as f:
                    entries = wsl_core.deserialize_log_entries(f.read())
                for entry in entries[-1000:]:
                    self._operation_log.append(wsl_core.format_log_entry_from_dict(entry))
        except OSError:
            pass

    def _persist_log_entry(self, operation: str, target: str, result: str) -> None:
        """操作ログ1件をファイルに追記します（実際の書き込みは別スレッド）。

        呼び出しはキューへの投入のみで完了するため、イベントループを
        ブロックしません。書き込み失敗は :class:`wsl_core.AsyncLogWriter`
        側で無視されます。
        """
        self._log_writer.submit(operation, target, result, source="gui")

    def _log_operation(self, operation: str, target: str, result: str) -> None:
        """操作ログにエントリを追加し、ファイルにも永続化します。

        Args:
            operation: 操作名（例: "停止"）。
            target: 操作対象（例: ディストリビューション名）。
            result: 結果（例: "実行"）。
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] {operation} | {target} | {result}"
        self._operation_log.append(entry)
        # 最大 1000 件を超えたら古いエントリを削除
        if len(self._operation_log) > 1000:
            self._operation_log = self._operation_log[-1000:]
        self._persist_log_entry(operation, target, result)

    def _show_log_viewer(self) -> None:
        """操作ログビューアーダイアログを開きます。"""
        dialog: LogViewerDialog | None = None

        def _clear() -> None:
            # キューに残った書き込みを先に片付けないと、削除直後に
            # 書き戻されて「消したログが復活する」ように見えてしまう
            self._log_writer.flush()
            _deleted, failed = wsl_core.delete_log_files(self._log_dir)
            self._operation_log.clear()
            if failed:
                messagebox.showwarning(
                    "警告",
                    "一部のログファイルを削除できませんでした。\n"
                    "他のプロセスが使用中の可能性があります:\n" + "\n".join(failed),
                    parent=dialog if dialog is not None else self,
                )

        dialog = LogViewerDialog(self, self._operation_log, _clear)

    # ── WSL コマンド実行 ──────────────────────────────────────────────────

    def _run_wsl_cmd(
        self,
        args: list[str],
        success_msg: str,
        error_msg: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        """WSL コマンドをバックグラウンドスレッドで実行し、完了後にリストを更新します。"""

        def _run() -> None:
            try:
                result = subprocess.run(
                    ["wsl", *args],
                    capture_output=True,
                    creationflags=CREATE_NO_WINDOW,
                    timeout=timeout,
                )
                if result.returncode == 0:
                    self._set_status_safe(success_msg)
                else:
                    stderr = wsl_core.decode_wsl_output(result.stderr).strip()
                    msg = error_msg or stderr or f"エラー (終了コード {result.returncode})"
                    self._set_status_safe(msg)
            except subprocess.TimeoutExpired:
                self._set_status_safe("WSL の応答がタイムアウトしました。")
            except OSError as e:
                self._set_status_safe(str(e))
            finally:
                self._call_soon_safe(self._refresh)

        threading.Thread(target=_run, daemon=True).start()

    # ── ボタンアクション ──────────────────────────────────────────────────

    def _start_distro(self) -> None:
        """選択したディストリビューションのターミナルを開きます（起動を兼ねます）。"""
        self._open_terminal()

    def _stop_distro(self) -> None:
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                self._t("gui.common.warning"), self._t("gui.msg.select_distro"), parent=self
            )
            return
        if not messagebox.askyesno(
            self._t("gui.common.confirm"), self._t("gui.confirm.stop", name=name), parent=self
        ):
            return
        self._log_operation("停止", name, "実行")
        status_msg = f"「{name}」を停止中…" if self._language == "ja" else f"Stopping '{name}'..."
        self._set_status(status_msg)
        ok_msg = f"「{name}」を停止しました。" if self._language == "ja" else f"Stopped '{name}'."
        err_msg = (
            f"「{name}」の停止に失敗しました。"
            if self._language == "ja"
            else f"Failed to stop '{name}'."
        )
        self._run_wsl_cmd(["--terminate", name], ok_msg, err_msg)

    def _shutdown_all(self) -> None:
        if not messagebox.askyesno(
            self._t("gui.common.confirm"), self._t("gui.confirm.shutdown"), parent=self
        ):
            return
        self._log_operation("全停止", "全ディストリビューション", "実行")
        status_msg = (
            "WSL を全停止中…" if self._language == "ja" else "Shutting down all distributions..."
        )
        self._set_status(status_msg)
        ok_msg = (
            "WSL を全停止しました。" if self._language == "ja" else "Shut down all distributions."
        )
        err_msg = (
            "WSL の全停止に失敗しました。"
            if self._language == "ja"
            else "Failed to shut down all distributions."
        )
        self._run_wsl_cmd(["--shutdown"], ok_msg, err_msg)

    def _set_default(self) -> None:
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                self._t("gui.common.warning"), self._t("gui.msg.select_distro"), parent=self
            )
            return
        self._log_operation("デフォルト設定", name, "実行")
        status_msg = (
            f"「{name}」をデフォルトに設定中…"
            if self._language == "ja"
            else f"Setting '{name}' as default..."
        )
        self._set_status(status_msg)
        self._run_wsl_cmd(
            ["--set-default", name],
            self._t("gui.msg.set_default_success", name=name),
            self._t("gui.msg.set_default_failed", error=""),
        )

    def _open_terminal(self) -> None:
        """選択したディストリビューションのターミナルウィンドウを開きます。

        Windows Terminal (wt.exe) が利用可能な場合はそちらを優先し、
        ない場合は cmd.exe にフォールバックします。
        """
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                self._t("gui.common.warning"), self._t("gui.msg.select_distro"), parent=self
            )
            return
        # wsl --list の出力から得た名前はこのアプリの作成時バリデーションを
        # 経由していない可能性がある (他ツールでの登録等)。cmd.exe/wt.exe の
        # コマンドラインインタプリタに渡す前に必ず再検証する。
        valid, reason = wsl_core.validate_distro_name(name)
        if not valid:
            messagebox.showerror(
                self._t("gui.common.error"),
                f"「{name}」はターミナル起動時に使用できない名前です: {reason}",
                parent=self,
            )
            return
        try:
            # Windows Terminal を優先
            subprocess.Popen(
                ["wt.exe", "wsl", "-d", name],
                creationflags=CREATE_NO_WINDOW,
            )
            self._log_operation("ターミナル起動", name, "Windows Terminal")
            self._set_status(f"「{name}」のターミナルを開きました (Windows Terminal)。")
            return
        except FileNotFoundError:
            pass
        except OSError:
            pass

        # cmd.exe にフォールバック
        try:
            subprocess.Popen(
                ["cmd.exe", "/k", "wsl", "-d", name],
                creationflags=CREATE_NEW_CONSOLE,
            )
            self._log_operation("ターミナル起動", name, "コマンド プロンプト")
            self._set_status(f"「{name}」のターミナルを開きました (コマンド プロンプト)。")
        except OSError as e:
            self._set_status(f"ターミナルを開けませんでした: {e}")

    def _on_tree_return(self, _event: object = None) -> None:
        """Treeview 上で Return キーが押されたときの処理。

        ダブルクリックと同じくターミナルを開くが、選択行が無い状態で
        Enter を押しても警告ダイアログは出さず、何もしない
        （空撃ちを無害な no-op にする）。
        """
        if not self._selected_name():
            return
        self._open_terminal()

    def _show_detail(self) -> None:
        """選択したディストリビューションの詳細情報ダイアログを開きます。"""
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                "警告", "ディストリビューションを選択してください。", parent=self
            )
            return
        DistroDetailDialog(self, name)

    def _show_processes(self) -> None:
        """選択したディストリビューションのプロセス一覧ウィンドウを開きます。"""
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                self._t("gui.common.warning"), self._t("gui.msg.select_distro"), parent=self
            )
            return

        sel = self._tree.selection()
        if sel:
            state_val = self._tree.item(sel[0])["values"][2]
            if state_val not in ("実行中", "Running"):
                messagebox.showwarning(
                    self._t("gui.common.warning"),
                    f"「{name}」は停止中です。起動してからプロセスを確認してください。"
                    if self._language == "ja"
                    else f"'{name}' is stopped. Please start it before checking processes.",
                    parent=self,
                )
                return

        self._process_windows = {k: v for k, v in self._process_windows.items() if v.winfo_exists()}

        existing = self._process_windows.get(name)
        if existing and existing.winfo_exists():
            existing.lift()
            existing.focus_set()
            return

        win = ProcessWindow(self, name)
        self._process_windows[name] = win

    def _clone_distro(self) -> None:
        """選択したディストリビューションを複製します（エクスポート→インポートを自動実行）。"""
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                "警告", "ディストリビューションを選択してください。", parent=self
            )
            return

        existing = [d["name"] for d in self._all_distros]
        version = next((str(d["version"]) for d in self._all_distros if d["name"] == name), "")

        new_name = simpledialog.askstring(
            "複製",
            "新しいディストリビューション名を入力してください。",
            initialvalue=wsl_core.default_clone_name(name, existing),
            parent=self,
        )
        if new_name is None:
            return
        new_name = new_name.strip()
        valid, reason = wsl_core.validate_clone_name(new_name, existing)
        if not valid:
            messagebox.showwarning("警告", reason, parent=self)
            return

        install_path = filedialog.askdirectory(title="複製先フォルダを選択")
        if not install_path:
            return

        if not messagebox.askyesno(
            "確認",
            (
                "次の内容で複製します。\n\n"
                f"複製元: {name}\n"
                f"複製先の名前: {new_name}\n"
                f"複製先フォルダ: {install_path}\n\n"
                "複製中は一時 tar ファイルが複製先フォルダに作成され、"
                "完了後に削除されます。"
            ),
            parent=self,
        ):
            return

        self._log_operation("複製", name, f"→ {new_name}")
        self._set_status(f"「{name}」を複製中… (1/2 エクスポート)")
        self._run_clone_cmd(name, new_name, install_path, version)

    def _run_clone_cmd(self, name: str, new_name: str, install_path: str, version: str) -> None:
        """複製処理（エクスポート→インポート）をバックグラウンドスレッドで実行します。"""

        def _run() -> None:
            try:
                fd, tmp_tar = tempfile.mkstemp(
                    prefix=f"{new_name}-clone-", suffix=".tar", dir=install_path
                )
                os.close(fd)
            except OSError as e:
                self._set_status_safe(str(e))
                return

            try:
                try:
                    export_result = subprocess.run(
                        ["wsl", "--export", name, tmp_tar],
                        capture_output=True,
                        creationflags=CREATE_NO_WINDOW,
                        timeout=3600,
                    )
                except subprocess.TimeoutExpired:
                    self._set_status_safe("複製処理がタイムアウトしました。")
                    return
                except OSError as e:
                    self._set_status_safe(str(e))
                    return

                if export_result.returncode != 0:
                    stderr = wsl_core.decode_wsl_output(export_result.stderr).strip()
                    msg = stderr or f"「{name}」のエクスポートに失敗しました。"
                    self._set_status_safe(msg)
                    return

                self._set_status_safe(f"「{name}」を複製中… (2/2 インポート)")

                import_args = ["wsl", "--import", new_name, install_path, tmp_tar]
                if version in ("1", "2"):
                    import_args += ["--version", version]

                try:
                    import_result = subprocess.run(
                        import_args,
                        capture_output=True,
                        creationflags=CREATE_NO_WINDOW,
                        timeout=3600,
                    )
                except subprocess.TimeoutExpired:
                    self._set_status_safe("複製処理がタイムアウトしました。")
                    return
                except OSError as e:
                    self._set_status_safe(str(e))
                    return

                if import_result.returncode != 0:
                    stderr = wsl_core.decode_wsl_output(import_result.stderr).strip()
                    msg = stderr or f"「{new_name}」のインポートに失敗しました。"
                    self._set_status_safe(msg)
                    return

                self._set_status_safe(f"「{name}」を「{new_name}」として複製しました。")
            finally:
                try:
                    os.remove(tmp_tar)
                except OSError:
                    pass
                self._call_soon_safe(self._refresh)

        threading.Thread(target=_run, daemon=True).start()

    def _export_distro_image(self) -> None:
        """選択したディストリビューションをエクスポートします（tar または VHD 形式）。"""
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                "警告", "ディストリビューションを選択してください。", parent=self
            )
            return

        use_vhd = messagebox.askyesno(
            "エクスポート形式",
            "VHD 形式でエクスポートしますか？\n「いいえ」を選ぶと tar 形式でエクスポートします。",
            parent=self,
        )

        if use_vhd:
            export_path = filedialog.asksaveasfilename(
                title="エクスポート先を選択",
                defaultextension=".vhdx",
                initialfile=f"{name}.vhdx",
                filetypes=[("VHDX image", "*.vhdx"), ("All files", "*.*")],
            )
        else:
            export_path = filedialog.asksaveasfilename(
                title="エクスポート先を選択",
                defaultextension=".tar",
                initialfile=f"{name}.tar",
                filetypes=[("Tar archive", "*.tar"), ("All files", "*.*")],
            )
        if not export_path:
            return

        if os.path.exists(export_path) and not messagebox.askyesno(
            "確認", f"既存ファイルを上書きしますか？\n{export_path}", parent=self
        ):
            return

        partial_path = wsl_core.partial_write_path(export_path)
        # 前回失敗して残った部分ファイルがあれば掃除する（wsl --export は既存ファイルを拒否する）
        wsl_core.discard_partial_write(partial_path)

        cmd_args = ["--export", name, partial_path]
        if use_vhd:
            cmd_args.append("--vhd")

        # 元 VHDX のサイズを進捗率の分母 (上限の目安) として使う
        total_bytes: int | None = None
        vhdx_path = _get_distro_vhdx_path(name)
        if vhdx_path:
            try:
                total_bytes = os.path.getsize(vhdx_path)
            except OSError:
                total_bytes = None

        self._log_operation("エクスポート", name, export_path)
        self._set_status(f"「{name}」をエクスポート中…")

        def _on_done(returncode: int, stderr_text: str, cancelled: bool) -> None:
            if cancelled:
                wsl_core.discard_partial_write(partial_path)
                self._log_operation("エクスポート", name, "キャンセル")
                self._set_status(f"「{name}」のエクスポートをキャンセルしました。")
            elif returncode == 0:
                if wsl_core.finalize_partial_write(partial_path, export_path):
                    self._set_status(f"「{name}」をエクスポートしました。")
                else:
                    wsl_core.discard_partial_write(partial_path)
                    self._set_status(
                        f"「{name}」のエクスポートに失敗しました（一時ファイルの移動に失敗）。"
                    )
            else:
                wsl_core.discard_partial_write(partial_path)
                self._set_status(stderr_text or f"「{name}」のエクスポートに失敗しました。")
            self._refresh()

        TransferProgressDialog(
            self,
            "エクスポート",
            f"「{name}」をエクスポート中…",
            cmd_args,
            partial_path,
            total_bytes,
            _on_done,
        )

    # ── スナップショット ─────────────────────────────────────────────────

    def _snapshot_dir(self) -> str:
        """スナップショットの保存先ディレクトリを返します（設定優先、未設定時はデフォルト）。"""
        return self._settings.get("snapshot_dir") or wsl_core.get_default_snapshot_dir()

    def _create_snapshot(self) -> None:
        """選択したディストリビューションのスナップショット (tar + メタデータ) を作成します。"""
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                "警告", "ディストリビューションを選択してください。", parent=self
            )
            return

        comment = simpledialog.askstring(
            "スナップショット作成",
            f"「{name}」のスナップショットを作成します。\nコメント (任意):",
            parent=self,
        )
        if comment is None:
            return

        snap_dir = self._snapshot_dir()
        try:
            os.makedirs(snap_dir, exist_ok=True)
        except OSError as e:
            messagebox.showerror("エラー", str(e), parent=self)
            return

        timestamp = time.strftime(wsl_core.SNAPSHOT_TIMESTAMP_FORMAT)
        created_at = datetime.now().isoformat(timespec="seconds")
        basename = wsl_core.build_snapshot_basename(name, timestamp)
        tar_path = os.path.join(snap_dir, basename + ".tar")
        json_path = os.path.join(snap_dir, basename + ".json")

        wsl_version = next((str(d["version"]) for d in self._all_distros if d["name"] == name), "2")

        # 元 VHDX のサイズを進捗率の分母 (上限の目安) として使う
        total_bytes: int | None = None
        vhdx_path = _get_distro_vhdx_path(name)
        if vhdx_path:
            try:
                total_bytes = os.path.getsize(vhdx_path)
            except OSError:
                total_bytes = None

        partial_tar = wsl_core.partial_write_path(tar_path)
        # 前回失敗して残った部分ファイルがあれば掃除する（wsl --export は既存ファイルを拒否する）
        wsl_core.discard_partial_write(partial_tar)

        self._log_operation("スナップショット作成", name, tar_path)
        self._set_status(f"「{name}」のスナップショットを作成中…")

        def _on_done(returncode: int, stderr_text: str, cancelled: bool) -> None:
            if cancelled:
                wsl_core.discard_partial_write(partial_tar)
                self._log_operation("スナップショット作成", name, "キャンセル")
                self._set_status(f"「{name}」のスナップショット作成をキャンセルしました。")
            elif returncode == 0:
                if not wsl_core.finalize_partial_write(partial_tar, tar_path):
                    wsl_core.discard_partial_write(partial_tar)
                    self._set_status(
                        f"「{name}」のスナップショット作成に失敗しました"
                        "（一時ファイルの移動に失敗）。"
                    )
                else:
                    try:
                        size = os.path.getsize(tar_path)
                    except OSError:
                        size = 0
                    metadata = wsl_core.build_snapshot_metadata(
                        name, wsl_version, comment, size, created_at, basename + ".tar"
                    )
                    if not wsl_core.write_snapshot_metadata(json_path, metadata):
                        self._set_status(
                            f"「{name}」のスナップショットを作成しましたが、"
                            "メタデータの保存に失敗しました。"
                        )
                    else:
                        self._set_status(f"「{name}」のスナップショットを作成しました。")
            else:
                wsl_core.discard_partial_write(partial_tar)
                self._set_status(stderr_text or f"「{name}」のスナップショット作成に失敗しました。")
            self._refresh()

        TransferProgressDialog(
            self,
            "スナップショット作成",
            f"「{name}」のスナップショットを作成中…",
            ["--export", name, partial_tar],
            partial_tar,
            total_bytes,
            _on_done,
        )

    def _open_snapshot_manager(self) -> None:
        """スナップショット管理ダイアログを開きます。"""
        SnapshotManagerDialog(self)

    def _open_container_manager(self) -> None:
        """Open the read-only WSL Containers management dialog."""
        ContainerManagerDialog(self)

    def _get_online_distros(self) -> tuple[list[str], str | None]:
        """``wsl --list --online`` からインストール可能なディストロ名を取得します。"""
        try:
            result = subprocess.run(
                ["wsl", "--list", "--online"],
                capture_output=True,
                creationflags=CREATE_NO_WINDOW,
                timeout=60.0,
            )
        except subprocess.TimeoutExpired:
            return [], "オンライン一覧の取得がタイムアウトしました。"
        except FileNotFoundError:
            return [], "wsl.exe が見つかりません。WSL2 がインストールされているか確認してください。"
        except OSError as e:
            return [], f"WSL の実行に失敗しました: {e}"

        if result.returncode != 0:
            stderr = wsl_core.decode_wsl_output(result.stderr).strip()
            return [], stderr or "インストール可能な一覧取得に失敗しました。"

        names = wsl_core.parse_online_distros(wsl_core.decode_wsl_output(result.stdout))
        return names, None

    def _install_distro(self) -> None:
        """公式配布ディストリビューションを個別インストールします。

        バックグラウンドで ``wsl --list --online`` を取得しつつ UI フリーズを防ぎます。
        取得完了後に :class:`InstallDialog` を表示します。
        """
        self._set_status("インストール可能な一覧を取得中…")

        def _fetch() -> None:
            candidates, err = self._get_online_distros()
            self._call_soon_safe(lambda: self._open_install_dialog(candidates, err))

        threading.Thread(target=_fetch, daemon=True).start()

    def _open_install_dialog(self, candidates: list[str], err: str | None) -> None:
        """``_install_distro`` のバックグラウンド取得完了後にダイアログを開きます。"""
        if err:
            self._set_status(err)

        dialog = InstallDialog(self, candidates)
        self.wait_window(dialog)

        name = dialog.result
        if name is None:
            self._set_status("インストールをキャンセルしました。")
            return

        if not messagebox.askyesno("確認", f"「{name}」をインストールしますか？", parent=self):
            return

        self._set_status(f"「{name}」をインストール中…")
        self._run_wsl_cmd(
            ["--install", "-d", name, "--no-launch"],
            f"「{name}」をインストールしました。初回起動時に初期セットアップ（ユーザー作成）が実行されます。",
            f"「{name}」のインストールに失敗しました。",
        )

    def _uninstall_distro(self) -> None:
        """選択したディストリビューションを個別アンインストールします。"""
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                self._t("gui.common.warning"), self._t("gui.msg.select_distro"), parent=self
            )
            return

        if not messagebox.askyesno(
            self._t("gui.common.confirm"),
            self._t("gui.confirm.unregister", name=name),
            parent=self,
        ):
            return

        confirm_name = simpledialog.askstring(
            self._t("gui.common.confirm"),
            (
                "誤操作防止のため、削除するディストリビューション名を\n"
                f"正確に入力してください: {name}"
                if self._language == "ja"
                else f"To prevent mistakes, please re-enter the exact distribution name:\n{name}"
            ),
            parent=self,
        )
        if confirm_name is None:
            return

        if confirm_name.strip() != name:
            messagebox.showwarning(
                self._t("gui.common.warning"),
                "入力された名前が一致しないため、アンインストールを中止しました。"
                if self._language == "ja"
                else "Uninstallation cancelled because the entered name did not match.",
                parent=self,
            )
            return

        self._log_operation("アンインストール", name, "実行")
        status_msg = (
            f"「{name}」をアンインストール中…"
            if self._language == "ja"
            else f"Unregistering '{name}'..."
        )
        self._set_status(status_msg)
        self._run_wsl_cmd(
            ["--unregister", name],
            self._t("gui.msg.unregister_success", name=name),
            self._t("gui.msg.unregister_failed", error=""),
        )

    def _import_distro_image(self) -> None:
        """tar/vhdx 形式のディストリビューションイメージをインポートします。"""
        distro_name = simpledialog.askstring(
            "インポート", "新しいディストリビューション名を入力してください。", parent=self
        )
        if distro_name is None:
            return
        distro_name = distro_name.strip()
        valid, reason = wsl_core.validate_distro_name(distro_name)
        if not valid:
            messagebox.showwarning("警告", reason, parent=self)
            return

        image_path = filedialog.askopenfilename(
            title="インポートするイメージを選択",
            filetypes=[
                ("WSL image files", "*.tar *.tar.gz *.tgz *.vhd *.vhdx"),
                ("All files", "*.*"),
            ],
        )
        if not image_path:
            return

        install_path = filedialog.askdirectory(title="インストール先フォルダを選択")
        if not install_path:
            return

        is_wsl2 = messagebox.askyesno(
            "WSL バージョン",
            "WSL2 としてインポートしますか？\n「いいえ」を選ぶと WSL1 としてインポートします。",
            parent=self,
        )
        version = "2" if is_wsl2 else "1"

        if not messagebox.askyesno(
            "確認",
            (
                "次の内容でインポートします。\n\n"
                f"名前: {distro_name}\n"
                f"イメージ: {image_path}\n"
                f"保存先: {install_path}\n"
                f"バージョン: WSL{version}"
            ),
            parent=self,
        ):
            return

        # 入力イメージのサイズを分母に、インストール先 ext4.vhdx の成長を監視する
        # (WSL1 は vhdx を使わないため経過時間のみの表示になる)
        total_bytes: int | None = None
        watch_path: str | None = None
        if version == "2":
            try:
                total_bytes = os.path.getsize(image_path)
            except OSError:
                total_bytes = None
            watch_path = os.path.join(install_path, "ext4.vhdx")

        self._log_operation("インポート", distro_name, image_path)
        self._set_status(f"「{distro_name}」をインポート中…")

        def _on_done(returncode: int, stderr_text: str, cancelled: bool) -> None:
            if cancelled:
                self._log_operation("インポート", distro_name, "キャンセル")
                self._set_status(f"「{distro_name}」のインポートをキャンセルしました。")
                if messagebox.askyesno(
                    "確認",
                    (
                        "インポートを中断したため、不完全な登録が残っている\n"
                        f"可能性があります。「{distro_name}」の登録を解除しますか？"
                    ),
                    parent=self,
                ):
                    self._run_wsl_cmd(
                        ["--unregister", distro_name],
                        f"「{distro_name}」の登録を解除しました。",
                        f"「{distro_name}」の登録解除に失敗しました。",
                    )
                    return
            elif returncode == 0:
                self._set_status(f"「{distro_name}」をインポートしました。")
            else:
                self._set_status(stderr_text or f"「{distro_name}」のインポートに失敗しました。")
            self._refresh()

        TransferProgressDialog(
            self,
            "インポート",
            f"「{distro_name}」をインポート中…",
            [
                "--import",
                distro_name,
                install_path,
                image_path,
                "--version",
                version,
            ],
            watch_path,
            total_bytes,
            _on_done,
        )

    def _open_wslconfig(self) -> None:
        """.wslconfig エディタダイアログを開きます。"""
        dialog = WslConfigDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            self._set_status(".wslconfig を保存しました。反映には全停止が必要です。")

    def _open_distro_conf(self) -> None:
        """選択したディストリビューションの wsl.conf エディタダイアログを開きます。"""
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                "警告", "ディストリビューションを選択してください。", parent=self
            )
            return
        dialog = DistroConfDialog(self, name)
        self.wait_window(dialog)
        if dialog.result:
            self._set_status(f"「{name}」の wsl.conf を保存しました。")
            self._refresh()

    def _show_context_menu(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        """右クリックでディストリビューション操作のコンテキストメニューを表示します。"""
        row = self._tree.identify_row(event.y)
        if not row:
            return
        self._tree.selection_set(row)
        self._tree.focus(row)

        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label=self._t("gui.context.terminal"), command=self._open_terminal)
        menu.add_command(label=self._t("gui.context.details"), command=self._show_detail)
        menu.add_command(label=self._t("gui.context.processes"), command=self._show_processes)
        menu.add_command(label=self._t("gui.context.explorer"), command=self._open_in_explorer)
        menu.add_command(label=self._t("gui.context.copy_ip"), command=self._copy_ip_address)
        menu.add_separator()
        menu.add_command(label=self._t("gui.context.stop"), command=self._stop_distro)
        menu.add_command(label=self._t("gui.context.set_default"), command=self._set_default)
        menu.add_command(label=self._t("gui.context.convert"), command=self._convert_version)
        menu.add_command(label=self._t("gui.context.optimize"), command=self._open_disk_optimize)
        menu.add_command(label=self._t("gui.context.distro_conf"), command=self._open_distro_conf)
        menu.add_separator()
        menu.add_command(label=self._t("gui.context.clone"), command=self._clone_distro)
        menu.add_command(label=self._t("gui.context.snapshot"), command=self._create_snapshot)
        menu.add_command(label=self._t("gui.context.export"), command=self._export_distro_image)
        menu.add_command(label=self._t("gui.context.unregister"), command=self._uninstall_distro)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _open_disk_optimize(self) -> None:
        """選択したディストリビューションのディスク最適化ダイアログを開きます。"""
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                "警告", "ディストリビューションを選択してください。", parent=self
            )
            return
        vhdx = _get_distro_vhdx_path(name)
        if not vhdx:
            messagebox.showinfo(
                "ディスク最適化",
                (
                    f"「{name}」の仮想ディスク (ext4.vhdx) が見つかりません。\n"
                    "WSL1 か、ディスク情報を取得できない構成の可能性があります。"
                ),
                parent=self,
            )
            return
        DiskOptimizeDialog(self, name, vhdx)

    def _open_in_explorer(self) -> None:
        """選択したディストリビューションのファイルシステムをエクスプローラーで開きます。"""
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                "警告", "ディストリビューションを選択してください。", parent=self
            )
            return
        try:
            subprocess.Popen(
                ["explorer.exe", f"\\\\wsl.localhost\\{name}"],
                creationflags=CREATE_NO_WINDOW,
            )
            self._set_status(f"「{name}」をエクスプローラーで開きました。")
        except OSError as e:
            self._set_status(f"エクスプローラーを開けませんでした: {e}")

    def _copy_ip_address(self) -> None:
        """選択したディストリビューションのIPアドレスをクリップボードにコピーします。"""
        sel = self._tree.selection()
        if not sel:
            return
        values = self._tree.item(sel[0])["values"]
        if not values or len(values) < 8:
            return
        ip = str(values[7])  # index 7 = ip column
        if ip and ip != "-":
            self.clipboard_clear()
            self.clipboard_append(ip)
            self._set_status(f"IPアドレスをコピーしました: {ip}")
        else:
            self._set_status("IPアドレスが取得できていません。")

    def _convert_version(self) -> None:
        """選択したディストリビューションの WSL バージョンを変換します(WSL1↔WSL2)。"""
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                self._t("gui.common.warning"), self._t("gui.msg.select_distro"), parent=self
            )
            return

        sel = self._tree.selection()
        current_version_str = ""
        if sel:
            values = self._tree.item(sel[0])["values"]
            if values and len(values) > 3:
                current_version_str = str(values[3])  # index 3: "WSL1" or "WSL2"

        if current_version_str == "WSL1":
            current = "1"
            target = "2"
        elif current_version_str == "WSL2":
            current = "2"
            target = "1"
        else:
            current = "?"
            target = "2"

        if current == "?":
            confirm_msg = self._t("gui.confirm.convert", name=name, target=target)
        else:
            if self._language == "ja":
                confirm_msg = (
                    f"「{name}」を WSL{current} から WSL{target} に変換しますか？\n"
                    "（変換には数分かかる場合があります）"
                )
            else:
                confirm_msg = (
                    f"Convert '{name}' from WSL{current} to WSL{target}?\n"
                    "(This conversion may take several minutes)"
                )

        if not messagebox.askyesno(self._t("gui.common.confirm"), confirm_msg, parent=self):
            return

        self._log_operation("バージョン変換", name, f"WSL{target}")
        status_msg = (
            f"「{name}」を WSL{target} に変換中…"
            if self._language == "ja"
            else f"Converting '{name}' to WSL{target}..."
        )
        self._set_status(status_msg)

        def _on_done(returncode: int, stderr_text: str, cancelled: bool) -> None:
            if cancelled:
                self._log_operation("バージョン変換", name, "キャンセル")
                self._set_status(
                    f"「{name}」の WSL バージョン変換を中断しました。"
                    if self._language == "ja"
                    else f"Cancelled WSL version conversion for '{name}'."
                )
            elif returncode == 0:
                self._set_status(self._t("gui.msg.convert_success", name=name, version=target))
            else:
                self._set_status(stderr_text or self._t("gui.msg.convert_failed", error=""))
            self._refresh()

        # ``--set-version`` は大きなディストリビューションで数分〜数十分かかるため
        # 固定タイムアウトの _run_wsl_cmd ではなく Popen ベースの進捗ダイアログを使う。
        # 進捗を監視できる出力ファイルは無いので watch_path は None（経過時間表示）。
        TransferProgressDialog(
            self,
            "WSL バージョン変換",
            f"「{name}」を WSL{target} に変換しています…",
            ["--set-version", name, target],
            None,
            None,
            _on_done,
            cancel_prompt=(
                "変換をキャンセルしますか？\n"
                "変換の中断はディストリビューションが不完全な状態で"
                "残る可能性があります。"
            ),
        )

    def _open_mount(self) -> None:
        """ディスクのマウントダイアログを開きます。"""
        WslMountDialog(self)

    def _open_unmount(self) -> None:
        """ディスクのアンマウントダイアログを開きます。"""
        WslUnmountDialog(self)

    def _execute_mount(self, disk: str, mount_args: list[str]) -> None:
        """ディスクのマウントコマンドを実行します。"""
        self._set_status(f"「{disk}」をマウント中…")

        def _run() -> None:
            res = wsl_core.run_wsl(mount_args, timeout=60.0, creationflags=CREATE_NO_WINDOW)

            def _done() -> None:
                if res.returncode == 0:
                    self._log_operation("マウント", disk, "成功")
                    self._set_status(f"「{disk}」をマウントしました。")
                    messagebox.showinfo(
                        "マウント完了", f"「{disk}」を正常にマウントしました。", parent=self
                    )
                else:
                    msg = res.stderr.strip() or "マウントに失敗しました。"
                    self._log_operation("マウント", disk, f"失敗: {msg}")
                    self._set_status(f"マウント失敗: {msg}")
                    messagebox.showerror(
                        "マウントエラー",
                        f"「{disk}」のマウントに失敗しました:\n{msg}\n\n"
                        "管理者権限が必要な場合があります。",
                        parent=self,
                    )

            self._call_soon_safe(_done)

        threading.Thread(target=_run, daemon=True).start()

    def _execute_unmount(self, disk: str | None, unmount_args: list[str]) -> None:
        """ディスクのアンマウントコマンドを実行します。"""
        target = disk or "すべてのマウントディスク"
        self._set_status(f"「{target}」をアンマウント中…")

        def _run() -> None:
            res = wsl_core.run_wsl(unmount_args, timeout=30.0, creationflags=CREATE_NO_WINDOW)

            def _done() -> None:
                if res.returncode == 0:
                    self._log_operation("アンマウント", target, "成功")
                    self._set_status(f"「{target}」をアンマウントしました。")
                    messagebox.showinfo(
                        "アンマウント完了",
                        f"「{target}」を正常にアンマウントしました。",
                        parent=self,
                    )
                else:
                    msg = res.stderr.strip() or "アンマウントに失敗しました。"
                    self._log_operation("アンマウント", target, f"失敗: {msg}")
                    self._set_status(f"アンマウント失敗: {msg}")
                    messagebox.showerror(
                        "アンマウントエラー",
                        f"「{target}」のアンマウントに失敗しました:\n{msg}\n\n"
                        "管理者権限が必要な場合があります。",
                        parent=self,
                    )

            self._call_soon_safe(_done)

        threading.Thread(target=_run, daemon=True).start()

    def _show_wsl_version(self) -> None:
        """WSL のバージョン情報を取得してダイアログに表示します。"""
        label_map = {
            "wsl": "WSL バージョン",
            "kernel": "カーネル バージョン",
            "wslg": "WSLg バージョン",
            "msrdc": "MSRDC バージョン",
            "direct3d": "Direct3D バージョン",
            "dxcore": "DXCore バージョン",
            "windows": "Windows バージョン",
        }

        def _run() -> None:
            try:
                result = subprocess.run(
                    ["wsl", "--version"],
                    capture_output=True,
                    creationflags=CREATE_NO_WINDOW,
                    timeout=10.0,
                )
                output = wsl_core.decode_wsl_output(result.stdout)
                info = wsl_core.parse_wsl_version(output)
            except (OSError, subprocess.TimeoutExpired, ValueError):
                info = {}

            def _show() -> None:
                lines = []
                for key, label in label_map.items():
                    value = info.get(key)
                    if value is not None:
                        lines.append(f"{label}: {value}")
                capability = wsl_core.wslc_capability(str(info.get("wsl", "")))
                lines.append("")
                lines.append(
                    self._t("containers.eligible")
                    if capability["version_supported"]
                    else f"WSL Containers: {capability['reason']}"
                )
                unparsed = info.get("_unparsed_lines")
                if unparsed:
                    lines.append("")
                    lines.append("【その他の情報】")
                    lines.extend(unparsed)
                if not lines:
                    lines = ["WSL のバージョン情報を取得できませんでした。"]
                WslVersionDialog(self, lines, self._update_wsl)

            self._call_soon_safe(_show)

        threading.Thread(target=_run, daemon=True).start()

    def _update_wsl(self) -> None:
        """WSL 本体（wsl.exe / カーネル）の更新確認・実行フローを開始します。"""
        running_distros = [d["name"] for d in self._all_distros if d["state"] == "Running"]

        dialog = WslUpdateConfirmDialog(self, running_distros)
        self.wait_window(dialog)
        if dialog.result is None:
            return

        pre_release = bool(dialog.result.get("pre_release", False))
        self._run_wsl_update_cmd(pre_release)

    def _run_wsl_update_cmd(self, pre_release: bool) -> None:
        """``wsl --update`` をバックグラウンドスレッドで実行します。"""
        args = ["--update"]
        if pre_release:
            args.append("--pre-release")

        self._set_status("WSL を更新中…（数分かかる場合があります）")

        def _on_done(returncode: int, stderr_text: str, cancelled: bool) -> None:
            target = "wsl" + ("(--pre-release)" if pre_release else "")
            if cancelled:
                self._log_operation("WSL 更新", target, "キャンセル")
                self._set_status("WSL の更新をキャンセルしました。")
            elif returncode == 0:
                self._log_operation("WSL 更新", target, "成功")
                self._set_status("WSL の更新が完了しました。")
                messagebox.showinfo("WSL 更新", "WSL の更新が完了しました。", parent=self)
            else:
                msg = stderr_text or "WSL の更新に失敗しました。"
                self._log_operation("WSL 更新", target, f"失敗: {msg}")
                self._set_status(f"WSL 更新失敗: {msg}")
                messagebox.showerror("WSL 更新エラー", msg, parent=self)

        TransferProgressDialog(
            self,
            "WSL 更新",
            "WSL を更新しています…（数分かかる場合があります）",
            args,
            None,
            None,
            _on_done,
            cancel_prompt="WSL の更新をキャンセルしますか？",
        )

    def _show_about(self) -> None:
        """アプリケーション情報を表示します。"""
        messagebox.showinfo(
            "WSL Manager について",
            f"WSL Manager v{wsl_core.__version__}\n\n"
            "WSL2 ディストリビューション管理ツール\n"
            "Windows 10/11 + WSL2 環境用\n\n"
            "GitHub: https://github.com/kumakumapon/WSLManager",
            parent=self,
        )

    # ── 自動更新 ─────────────────────────────────────────────────────────

    def _toggle_auto_refresh(self) -> None:
        if self._auto_refresh_var.get():
            self._schedule_auto_refresh()
        else:
            if self._refresh_job:
                self.after_cancel(self._refresh_job)
                self._refresh_job = None
        self._save_settings()

    def _schedule_auto_refresh(self) -> None:
        self._refresh()
        self._refresh_job = self.after(5000, self._schedule_auto_refresh)

    # ── テーマ切り替え ────────────────────────────────────────────────────

    def _change_theme(self, theme_name: str) -> None:
        """ttk テーマを切り替えます。"""
        try:
            style = ttk.Style(self)
            style.theme_use(theme_name)
            self._current_theme = theme_name
            self._set_status(f"テーマを「{theme_name}」に変更しました。")
            self._save_settings()
        except tk.TclError:
            self._set_status(f"テーマ「{theme_name}」の適用に失敗しました。")

    def _change_language(self, language: str) -> None:
        """Persist a language preference for the next application launch."""
        self._settings["language"] = wsl_core.normalize_language(language)
        self._save_settings()
        self._set_status(self._t("gui.language_changed"))

    # ── 設定の保存 ───────────────────────────────────────────────────────

    def _save_settings(self) -> None:
        """現在の UI 状態を設定ファイルに保存します。失敗しても例外は投げません。"""
        sort_col, sort_desc = self._sorter.get_state()
        settings = {
            "theme": self._current_theme,
            "auto_refresh": self._auto_refresh_var.get(),
            "window_geometry": self.geometry(),
            "sort_column": sort_col,
            "sort_desc": sort_desc,
            "snapshot_dir": self._settings.get("snapshot_dir"),
            "language": self._settings.get("language", wsl_core.LANGUAGE_AUTO),
        }
        wsl_core.save_settings(self._settings_path, settings)

    # ── ウィンドウ終了 ────────────────────────────────────────────────────

    def on_closing(self) -> None:
        # 実行中のエクスポート/インポート等があれば、確認の上でプロセスを
        # 終了させてから閉じる (#26: 放置すると wsl.exe が孤児化する)。
        live_transfers = [d for d in self._transfer_dialogs if d.winfo_exists()]
        if live_transfers:
            if not messagebox.askyesno(
                "確認",
                f"実行中の処理が {len(live_transfers)} 件あります。中断して終了しますか？\n"
                "中断すると、処理中だったファイルが不完全な状態で残る場合があります。",
                parent=self,
            ):
                return
            for dialog in live_transfers:
                # 1件の force_cancel が予期せぬ例外を送出しても、他のダイアログの
                # 終了処理とアプリの終了処理自体は続行する。
                try:
                    dialog.force_cancel()
                except OSError:
                    pass
        if self._refresh_job:
            self.after_cancel(self._refresh_job)
        self._save_settings()
        # キューに残った操作ログを書き終えてからライタスレッドを終了させる
        self._log_writer.stop()
        self.destroy()


# ── エントリポイント ──────────────────────────────────────────────────────────


def main() -> None:
    if sys.platform != "win32":
        # Windows 以外では起動できない旨を伝えて終了
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "エラー",
            "WSL Manager は Windows 環境でのみ動作します。\nWindows 10/11 上で実行してください。",
            parent=root,
        )
        root.destroy()
        sys.exit(1)

    # 高DPI 対応
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass

    # 多重起動防止 (Named Mutex)
    try:
        import ctypes

        mutex_name = "Global\\WSLManager_SingleInstance_Mutex"
        ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
        if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            hwnd = ctypes.windll.user32.FindWindowW(None, "WSL Manager")
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                ctypes.windll.user32.SetForegroundWindow(hwnd)
            sys.exit(0)
    except (AttributeError, OSError):
        pass

    app = WSLManager()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()


if __name__ == "__main__":
    main()
