"""スナップショット管理ダイアログ。"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import TYPE_CHECKING

import wsl_core
from wslmgr_gui.dialogs.transfer import TransferProgressDialog

if TYPE_CHECKING:
    from wslmgr import WSLManager


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
