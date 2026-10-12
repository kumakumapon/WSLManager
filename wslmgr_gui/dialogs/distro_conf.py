"""/etc/wsl.conf 編集ダイアログ。"""

from __future__ import annotations

import subprocess
import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk
from typing import ClassVar

import wsl_core
from wslmgr_gui.winutil import CREATE_NO_WINDOW


class DistroConfDialog(tk.Toplevel):
    """ディストリビューションごとの ``/etc/wsl.conf`` を GUI で編集するモーダルダイアログ。

    読み込みは ``wsl -d <distro> -u root cat /etc/wsl.conf``、書き込みは
    ``wsl -d <distro> -u root sh -c 'cat > /etc/wsl.conf'`` (標準入力経由) で行い、
    いずれもバックグラウンドスレッドで実行して UI をブロックしません。
    停止中のディストロは読み書きのために WSL 側で一時的に起動されます。
    保存成功時は ``self.result = True`` を設定します。
    """

    # (セクション, キー, ラベル, ウィジェット種別, Combobox 選択肢 or None)
    _FIELDS: ClassVar[list[tuple[str, str, str, str, list[str] | None]]] = [
        ("boot", "systemd", "systemd", "combo", ["", "true", "false"]),
        ("boot", "command", "command", "entry", None),
        ("user", "default", "default", "entry", None),
        ("automount", "enabled", "enabled", "combo", ["", "true", "false"]),
        ("automount", "root", "root", "entry", None),
        ("network", "hostname", "hostname", "entry", None),
        ("network", "generateResolvConf", "generateResolvConf", "combo", ["", "true", "false"]),
        ("interop", "enabled", "enabled", "combo", ["", "true", "false"]),
        ("interop", "appendWindowsPath", "appendWindowsPath", "combo", ["", "true", "false"]),
    ]

    # (セクション, キー) -> バリデータ関数 (未登録のキーは検証なし)
    _VALIDATORS: ClassVar[dict[tuple[str, str], Callable[[str], tuple[bool, str]]]] = {
        ("boot", "systemd"): wsl_core.validate_wslconf_bool,
        ("user", "default"): wsl_core.validate_linux_username,
        ("automount", "enabled"): wsl_core.validate_wslconf_bool,
        ("automount", "root"): wsl_core.validate_mount_root,
        ("network", "hostname"): wsl_core.validate_hostname,
        ("network", "generateResolvConf"): wsl_core.validate_wslconf_bool,
        ("interop", "enabled"): wsl_core.validate_wslconf_bool,
        ("interop", "appendWindowsPath"): wsl_core.validate_wslconf_bool,
    }

    def __init__(self, parent: tk.Tk, distro_name: str) -> None:
        super().__init__(parent)
        self._app = parent
        self._distro = distro_name
        self._busy = False
        self._sections: dict[str, dict[str, str]] = {}
        self.result: bool | None = None
        self.title(
            wsl_core.translate(
                "gui.distroconf.title",
                getattr(parent, "_language", wsl_core.LANGUAGE_AUTO),
                name=distro_name,
            )
        )
        self.resizable(True, False)
        self._build_ui()
        self._set_form_enabled(False)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.grab_set()
        self._load_config()

    def _build_ui(self) -> None:
        frame = ttk.Frame(self, padding=14)
        frame.pack(fill=tk.BOTH, expand=True)

        info_frame = ttk.Frame(frame)
        info_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(
            info_frame,
            text="未設定（空欄）の項目は wsl.conf に書き込まれません。",
            foreground="#555555",
        ).pack(anchor=tk.W)
        ttk.Label(
            info_frame,
            text="変更の反映には対象ディストロの再起動 (wsl --terminate) が必要です。",
            foreground="#555555",
        ).pack(anchor=tk.W)
        ttk.Label(
            info_frame,
            text="停止中のディストロは読み書きのために一時的に起動されます。",
            foreground="#555555",
        ).pack(anchor=tk.W)
        ttk.Label(
            info_frame,
            text="コメント行（# で始まる行）は保存時に保持されません。",
            foreground="#555555",
        ).pack(anchor=tk.W)

        ttk.Label(
            frame,
            text=f"編集対象: {self._distro} の /etc/wsl.conf",
            foreground="#777777",
        ).pack(anchor=tk.W, pady=(0, 8))

        ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(0, 10))

        form_frame = ttk.Frame(frame)
        form_frame.pack(fill=tk.X)

        self._field_vars: dict[tuple[str, str], tk.StringVar] = {}
        self._widgets: list[tuple[tk.Widget, str]] = []
        row_idx = 0
        current_section: str | None = None
        for section, key, label, widget_type, combo_values in self._FIELDS:
            if section != current_section:
                current_section = section
                ttk.Label(form_frame, text=f"[{section}]", font=("", 10, "bold")).grid(
                    row=row_idx,
                    column=0,
                    columnspan=2,
                    sticky=tk.W,
                    pady=(8 if row_idx else 0, 4),
                )
                row_idx += 1
            ttk.Label(form_frame, text=label, width=22, anchor=tk.W).grid(
                row=row_idx, column=0, sticky=tk.W, padx=(0, 8), pady=3
            )
            var = tk.StringVar(value="")
            self._field_vars[(section, key)] = var
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
            self._widgets.append((widget, widget_type))
            row_idx += 1

        ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(12, 10))

        self._status_var = tk.StringVar(value="読み込み中…")
        ttk.Label(
            frame,
            textvariable=self._status_var,
            relief=tk.SUNKEN,
            anchor=tk.W,
            padding=(4, 2),
        ).pack(fill=tk.X, pady=(0, 10))

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X)
        self._save_btn = ttk.Button(btn_frame, text="保存", command=self._on_save, width=10)
        self._save_btn.pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(btn_frame, text="キャンセル", command=self._on_cancel, width=10).pack(
            side=tk.RIGHT
        )

    def _set_form_enabled(self, enabled: bool) -> None:
        """フォームの各ウィジェットの有効/無効を切り替えます。"""
        for widget, widget_type in self._widgets:
            try:
                if enabled:
                    widget.configure(state="readonly" if widget_type == "combo" else "normal")
                else:
                    widget.configure(state=tk.DISABLED)
            except tk.TclError:
                pass
        try:
            self._save_btn.configure(state=tk.NORMAL if enabled else tk.DISABLED)
        except tk.TclError:
            pass

    def _load_config(self) -> None:
        """/etc/wsl.conf をバックグラウンドスレッドで読み込みます。"""
        distro = self._distro

        def _run() -> tuple[bool, str]:
            try:
                result = subprocess.run(
                    ["wsl", "-d", distro, "-u", "root", "cat", "/etc/wsl.conf"],
                    capture_output=True,
                    creationflags=CREATE_NO_WINDOW,
                    timeout=20.0,
                )
            except subprocess.TimeoutExpired:
                return False, "タイムアウトしました。"
            except OSError as e:
                return False, str(e)
            if result.returncode != 0:
                # ファイルが存在しない場合なども含め、非0終了は空扱いにする
                return True, ""
            return True, wsl_core.decode_wsl_output(result.stdout)

        def _run_and_apply() -> None:
            ok, text_or_err = _run()
            self.after(0, lambda: self._on_loaded(ok, text_or_err))

        threading.Thread(target=_run_and_apply, daemon=True).start()

    def _on_loaded(self, ok: bool, text_or_err: str) -> None:
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        if not ok:
            messagebox.showerror(
                "読み込みエラー",
                f"「{self._distro}」の wsl.conf 読み込みに失敗しました:\n{text_or_err}",
                parent=self,
            )
            self.destroy()
            return
        try:
            self._sections = wsl_core.parse_wslconfig(text_or_err)
        except wsl_core.WslConfigParseError as e:
            messagebox.showerror(
                "パースエラー",
                f"「{self._distro}」の /etc/wsl.conf をパースできませんでした:\n{e}\n\n"
                "既存の設定を保護するため、ファイルを手動で修正してから再度開いてください。",
                parent=self,
            )
            self.destroy()
            return
        for (section, key), var in self._field_vars.items():
            var.set(self._sections.get(section, {}).get(key, ""))
        self._set_form_enabled(True)
        self._status_var.set("読み込み完了。")

    def _on_save(self) -> None:
        """フォームの内容を検証して /etc/wsl.conf に書き込みます。"""
        if self._busy:
            return
        for (section, key), var in self._field_vars.items():
            validator = self._VALIDATORS.get((section, key))
            if validator is None:
                continue
            val = var.get().strip()
            valid, reason = validator(val)
            if not valid:
                messagebox.showwarning("入力エラー", reason, parent=self)
                return

        # 既存セクション・キーを保持しつつ編集対象のキーだけ上書き/削除する
        new_sections: dict[str, dict[str, str]] = {s: dict(kv) for s, kv in self._sections.items()}
        for (section, key), var in self._field_vars.items():
            value = var.get().strip()
            sec = new_sections.setdefault(section, {})
            if value:
                sec[key] = value
            else:
                sec.pop(key, None)

        text = wsl_core.dump_wslconfig(new_sections)

        self._busy = True
        self._set_form_enabled(False)
        self._status_var.set("保存中…")
        distro = self._distro

        def _run() -> tuple[bool, str]:
            try:
                result = subprocess.run(
                    ["wsl", "-d", distro, "-u", "root", "sh", "-c", "cat > /etc/wsl.conf"],
                    input=text.encode("utf-8"),
                    capture_output=True,
                    creationflags=CREATE_NO_WINDOW,
                    timeout=20.0,
                )
            except subprocess.TimeoutExpired:
                return False, "タイムアウトしました。"
            except OSError as e:
                return False, str(e)
            if result.returncode != 0:
                err = wsl_core.decode_wsl_output(result.stderr).strip()
                return False, err or f"エラー (終了コード {result.returncode})"
            return True, ""

        def _run_and_apply() -> None:
            ok, err = _run()
            self.after(0, lambda: self._on_saved(ok, err, new_sections))

        threading.Thread(target=_run_and_apply, daemon=True).start()

    def _on_saved(self, ok: bool, err: str, new_sections: dict[str, dict[str, str]]) -> None:
        self._busy = False
        try:
            exists = self.winfo_exists()
        except tk.TclError:
            exists = False

        if not ok:
            self._log_operation_safe(f"保存失敗: {err}")
            if exists:
                self._set_form_enabled(True)
                self._status_var.set(f"保存に失敗しました: {err}")
                messagebox.showerror(
                    "保存エラー",
                    f"wsl.conf の書き込みに失敗しました:\n{err}",
                    parent=self,
                )
            return

        self._sections = new_sections
        self.result = True
        self._log_operation_safe("保存")

        if not exists:
            return

        restart = messagebox.askyesno(
            "保存しました",
            (
                f"「{self._distro}」の wsl.conf を保存しました。\n\n"
                "変更を反映するには対象ディストロの再起動 (wsl --terminate) が必要です。\n"
                "今すぐ再起動しますか？"
            ),
            parent=self,
        )
        if not restart:
            self.destroy()
            return

        self._status_var.set("再起動中…")
        distro = self._distro

        def _run_terminate() -> tuple[int, str]:
            try:
                result = subprocess.run(
                    ["wsl", "--terminate", distro],
                    capture_output=True,
                    creationflags=CREATE_NO_WINDOW,
                    timeout=20.0,
                )
            except subprocess.TimeoutExpired:
                return -1, "タイムアウトしました。"
            except OSError as e:
                return -1, str(e)
            return result.returncode, wsl_core.decode_wsl_output(result.stderr).strip()

        def _run_and_finish() -> None:
            rc, msg = _run_terminate()
            self.after(0, lambda: self._on_terminated(rc, msg))

        threading.Thread(target=_run_and_finish, daemon=True).start()

    def _on_terminated(self, rc: int, msg: str) -> None:
        self._log_operation_safe("再起動" if rc == 0 else f"再起動失敗: {msg or '不明なエラー'}")
        try:
            exists = self.winfo_exists()
        except tk.TclError:
            exists = False
        if rc != 0 and exists:
            messagebox.showwarning(
                "再起動エラー",
                f"「{self._distro}」の再起動に失敗しました:\n{msg or '不明なエラー'}",
                parent=self,
            )
        if exists:
            self.destroy()

    def _log_operation_safe(self, result: str) -> None:
        """親アプリの操作ログに記録します（親に _log_operation がない場合は無視）。"""
        log_fn = getattr(self._app, "_log_operation", None)
        if callable(log_fn):
            log_fn("ディストロ設定", self._distro, result)

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()
