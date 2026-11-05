"""エクスポート・インポート・複製の入力フォーム。

以前は「VHD 形式にしますか? (いいえで tar)」のような はい/いいえ の質問と、
ファイル選択ダイアログを何段も続けていた。ここでは必要な項目を 1 画面に並べ、
既定値を埋め、入力の誤りをその場で示す。

フォームは入力を集めるだけで、``wsl.exe`` は実行しない。実行前の確認 (上書き確認・
内容確認) は呼び出し側 (:mod:`wslmgr`) が従来どおり行う。
"""

from __future__ import annotations

import os
import tkinter as tk
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from tkinter import filedialog, ttk

import wsl_core


@dataclass(frozen=True)
class ExportRequest:
    path: str
    vhd: bool


@dataclass(frozen=True)
class ImportRequest:
    name: str
    image_path: str
    install_dir: str
    version: str


@dataclass(frozen=True)
class CloneRequest:
    name: str
    install_dir: str


def _image_stem(path: str) -> str:
    """``C:/x/Ubuntu-20260101.tar.gz`` → ``Ubuntu-20260101`` (インポート名の候補)。"""
    base = os.path.basename(path)
    lowered = base.lower()
    for ext in (*wsl_core.TAR_EXTENSIONS, *wsl_core.VHD_EXTENSIONS):
        if lowered.endswith(ext):
            return base[: -len(ext)]
    return os.path.splitext(base)[0]


class FormDialog(tk.Toplevel):
    """入力フォームの共通部分 (モーダル表示、エラー表示、OK/キャンセル、キー操作)。"""

    def __init__(self, parent: tk.Misc, title: str, ok_text: str) -> None:
        super().__init__(parent)
        self._language = getattr(parent, "_language", wsl_core.LANGUAGE_AUTO)
        self.title(title)
        self.resizable(True, False)
        self.result: object | None = None

        self.body = ttk.Frame(self, padding=(16, 14, 16, 8))
        self.body.pack(fill=tk.BOTH, expand=True)
        self.body.columnconfigure(1, weight=1)

        self._error_var = tk.StringVar()
        self._error = ttk.Label(
            self, textvariable=self._error_var, style="Error.TLabel", wraplength=460
        )

        buttons = ttk.Frame(self, padding=(16, 4, 16, 14))
        buttons.pack(fill=tk.X, side=tk.BOTTOM)
        self._buttons = buttons
        self._ok = ttk.Button(
            buttons, text=ok_text, style="Primary.TButton", command=self._on_ok, width=14
        )
        self._ok.pack(side=tk.RIGHT)
        ttk.Button(
            buttons, text=self._t("gui.common.cancel"), command=self._on_cancel, width=12
        ).pack(side=tk.RIGHT, padx=(0, 6))

        self.bind("<Return>", lambda _e: self._on_ok())
        self.bind("<Escape>", lambda _e: self._on_cancel())
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.transient(parent)  # type: ignore[call-overload]

    def _t(self, key: str, **values: object) -> str:
        return wsl_core.translate(key, self._language, **values)

    # ── 部品 ──────────────────────────────────────────────────────────────

    def _label(self, row: int, key: str) -> None:
        ttk.Label(self.body, text=self._t(key)).grid(
            row=row, column=0, sticky="w", padx=(0, 10), pady=4
        )

    def _entry_row(self, row: int, key: str, var: tk.StringVar, width: int = 44) -> ttk.Entry:
        self._label(row, key)
        entry = ttk.Entry(self.body, textvariable=var, width=width)
        entry.grid(row=row, column=1, sticky="ew", pady=4)
        return entry

    def _path_row(
        self, row: int, key: str, var: tk.StringVar, browse: Callable[[], None]
    ) -> ttk.Entry:
        entry = self._entry_row(row, key, var)
        ttk.Button(self.body, text=self._t("gui.form.browse"), command=browse, width=8).grid(
            row=row, column=2, sticky="e", padx=(6, 0), pady=4
        )
        return entry

    def _hint(self, row: int, text: str) -> None:
        ttk.Label(self.body, text=text, style="Muted.TLabel", wraplength=440, justify=tk.LEFT).grid(
            row=row, column=1, columnspan=2, sticky="w", pady=(0, 4)
        )

    # ── 検証と結果 ────────────────────────────────────────────────────────

    def _show_errors(self, errors: Sequence[wsl_core.FormError]) -> bool:
        """エラーがあれば表示して False を返します。"""
        if not errors:
            self._error_var.set("")
            self._error.pack_forget()
            return True
        self._error_var.set("\n".join(self._t(key, **values) for key, values in errors))
        # ボタンのすぐ上に表示する (下端から buttons → error の順に積む)
        self._error.pack(fill=tk.X, padx=16, side=tk.BOTTOM, after=self._buttons)
        return False

    def _collect(self) -> object | None:
        """入力を検証し、妥当なら結果を返します (サブクラスで実装)。"""
        raise NotImplementedError

    def _on_ok(self) -> None:
        result = self._collect()
        if result is None:
            return
        self.result = result
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()

    def run(self) -> object | None:
        """モーダルで表示し、閉じられるまで待って結果を返します。"""
        self.update_idletasks()
        _center_over(self, self.master)
        try:
            self.grab_set()
        except tk.TclError:
            pass  # 他のウィンドウが grab 中など。モーダルでなくても入力はできる
        self.wait_window(self)
        return self.result


def _center_over(window: tk.Toplevel, parent: tk.Misc | None) -> None:
    if parent is None:
        return
    try:
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h = window.winfo_reqwidth(), window.winfo_reqheight()
    except tk.TclError:
        return
    x = max(px + (pw - w) // 2, 0)
    y = max(py + (ph - h) // 3, 0)
    window.geometry(f"+{x}+{y}")


# ── エクスポート ─────────────────────────────────────────────────────────────


class ExportDialog(FormDialog):
    """エクスポート先と形式 (tar / VHDX) を 1 画面で指定するフォーム。"""

    def __init__(
        self, parent: tk.Misc, name: str, version: str, initial_dir: str | None = None
    ) -> None:
        super().__init__(
            parent,
            wsl_core.translate("gui.export.title", getattr(parent, "_language", "auto"), name=name),
            wsl_core.translate("gui.export.ok", getattr(parent, "_language", "auto")),
        )
        self._name = name
        # 前回のフォルダーが消えていれば (外付けドライブを外した等) ホームから始める
        directory = (
            initial_dir if initial_dir and os.path.isdir(initial_dir) else os.path.expanduser("~")
        )
        self._vhd_var = tk.BooleanVar(value=False)
        self._path_var = tk.StringVar(
            value=os.path.join(directory, wsl_core.suggest_export_filename(name, vhd=False))
        )

        self._label(0, "gui.form.distro")
        ttk.Label(self.body, text=name, style="Heading.TLabel").grid(
            row=0, column=1, sticky="w", pady=4
        )

        self._label(1, "gui.export.format")
        formats = ttk.Frame(self.body)
        formats.grid(row=1, column=1, columnspan=2, sticky="w", pady=4)
        ttk.Radiobutton(
            formats,
            text=self._t("gui.export.format_tar"),
            variable=self._vhd_var,
            value=False,
            command=self._on_format,
        ).pack(anchor=tk.W)
        vhd = ttk.Radiobutton(
            formats,
            text=self._t("gui.export.format_vhd"),
            variable=self._vhd_var,
            value=True,
            command=self._on_format,
        )
        vhd.pack(anchor=tk.W)
        if version == "1":  # WSL1 には仮想ディスクが無い
            vhd.state(["disabled"])

        entry = self._path_row(2, "gui.export.destination", self._path_var, self._browse)
        self._hint(3, self._t("gui.export.hint"))
        entry.focus_set()
        entry.icursor(tk.END)

    def _on_format(self) -> None:
        self._path_var.set(
            wsl_core.replace_export_extension(self._path_var.get(), self._vhd_var.get())
        )

    def _browse(self) -> None:
        vhd = self._vhd_var.get()
        current = self._path_var.get()
        path = filedialog.asksaveasfilename(
            parent=self,
            title=self._t("gui.export.browse_title"),
            initialdir=os.path.dirname(current) or None,
            initialfile=os.path.basename(current) or None,
            defaultextension=".vhdx" if vhd else ".tar",
            filetypes=[("VHDX", "*.vhdx")] if vhd else [("Tar", "*.tar")],
        )
        if path:
            self._path_var.set(os.path.normpath(path))

    def _collect(self) -> ExportRequest | None:
        path = self._path_var.get().strip()
        if not self._show_errors(wsl_core.validate_export_form(path)):
            return None
        return ExportRequest(path=path, vhd=self._vhd_var.get())

    @classmethod
    def ask(
        cls, parent: tk.Misc, name: str, version: str, initial_dir: str | None = None
    ) -> ExportRequest | None:
        result = cls(parent, name, version, initial_dir).run()
        return result if isinstance(result, ExportRequest) else None


# ── インポート ───────────────────────────────────────────────────────────────


class ImportDialog(FormDialog):
    """イメージ・名前・インストール先・WSL バージョンを 1 画面で指定するフォーム。

    名前はイメージのファイル名から、インストール先は名前から自動で埋める
    (利用者が自分で書き換えた項目は、それ以降は自動で上書きしない)。
    """

    def __init__(self, parent: tk.Misc, existing: Sequence[str]) -> None:
        language = getattr(parent, "_language", "auto")
        super().__init__(
            parent,
            wsl_core.translate("gui.import.title", language),
            wsl_core.translate("gui.import.ok", language),
        )
        self._existing = list(existing)
        self._image_var = tk.StringVar()
        self._name_var = tk.StringVar()
        self._dir_var = tk.StringVar(value=wsl_core.default_install_base())
        self._version_var = tk.StringVar(value="2")
        self._name_edited = False
        self._dir_edited = False
        self._updating = False

        self._path_row(0, "gui.import.image", self._image_var, self._browse_image)
        name_entry = self._entry_row(1, "gui.common.name", self._name_var)
        self._path_row(2, "gui.form.install_dir", self._dir_var, self._browse_dir)
        self._hint(3, self._t("gui.form.install_dir_hint"))

        self._label(4, "gui.import.version")
        versions = ttk.Frame(self.body)
        versions.grid(row=4, column=1, columnspan=2, sticky="w", pady=4)
        ttk.Radiobutton(
            versions, text=self._t("gui.import.wsl2"), variable=self._version_var, value="2"
        ).pack(side=tk.LEFT, padx=(0, 12))
        self._wsl1 = ttk.Radiobutton(versions, text="WSL 1", variable=self._version_var, value="1")
        self._wsl1.pack(side=tk.LEFT)
        self._vhd_hint = ttk.Label(
            self.body, text=self._t("gui.import.vhd_hint"), style="Muted.TLabel"
        )

        self._image_var.trace_add("write", lambda *_: self._on_image_changed())
        self._name_var.trace_add("write", lambda *_: self._on_name_changed())
        self._dir_var.trace_add("write", lambda *_: self._on_dir_changed())
        name_entry.focus_set()

    def _set(self, var: tk.StringVar, value: str) -> None:
        self._updating = True
        try:
            var.set(value)
        finally:
            self._updating = False

    def _on_image_changed(self) -> None:
        image = self._image_var.get().strip()
        if not self._name_edited and image:
            # 名前のトレースが走ってインストール先も追従する (自動入力なので「編集済み」にはしない)
            self._set(self._name_var, _image_stem(image))
        if wsl_core.is_vhd_image(image):
            self._version_var.set("2")
            self._wsl1.state(["disabled"])
            self._vhd_hint.grid(row=5, column=1, columnspan=2, sticky="w")
        else:
            self._wsl1.state(["!disabled"])
            self._vhd_hint.grid_forget()

    def _on_name_changed(self) -> None:
        if not self._updating:
            self._name_edited = True
        if not self._dir_edited:
            self._set(self._dir_var, wsl_core.suggest_install_dir(self._name_var.get()))

    def _on_dir_changed(self) -> None:
        if not self._updating:
            self._dir_edited = True

    def _browse_image(self) -> None:
        extensions = (*wsl_core.TAR_EXTENSIONS, *wsl_core.VHD_EXTENSIONS)
        patterns = " ".join(f"*{ext}" for ext in extensions)
        path = filedialog.askopenfilename(
            parent=self,
            title=self._t("gui.import.browse_image"),
            filetypes=[(self._t("gui.import.image_types"), patterns), ("*", "*.*")],
        )
        if path:
            self._image_var.set(os.path.normpath(path))

    def _browse_dir(self) -> None:
        path = filedialog.askdirectory(
            parent=self, title=self._t("gui.form.browse_dir"), mustexist=False
        )
        if path:
            self._dir_var.set(os.path.normpath(path))

    def _collect(self) -> ImportRequest | None:
        name = self._name_var.get().strip()
        image = self._image_var.get().strip()
        install_dir = self._dir_var.get().strip()
        errors = wsl_core.validate_import_form(
            name, image, install_dir, self._existing, self._language
        )
        if not self._show_errors(errors):
            return None
        version = "2" if wsl_core.is_vhd_image(image) else self._version_var.get()
        return ImportRequest(name=name, image_path=image, install_dir=install_dir, version=version)

    @classmethod
    def ask(cls, parent: tk.Misc, existing: Sequence[str]) -> ImportRequest | None:
        result = cls(parent, existing).run()
        return result if isinstance(result, ImportRequest) else None


# ── 複製 ─────────────────────────────────────────────────────────────────────


class CloneDialog(FormDialog):
    """複製先の名前とインストール先を 1 画面で指定するフォーム。"""

    def __init__(self, parent: tk.Misc, source: str, existing: Sequence[str]) -> None:
        language = getattr(parent, "_language", "auto")
        super().__init__(
            parent,
            wsl_core.translate("gui.clone.title", language, name=source),
            wsl_core.translate("gui.clone.ok", language),
        )
        self._existing = list(existing)
        initial = wsl_core.default_clone_name(source, self._existing)
        self._name_var = tk.StringVar(value=initial)
        self._dir_var = tk.StringVar(value=wsl_core.suggest_install_dir(initial))
        self._dir_edited = False
        self._updating = False

        self._label(0, "gui.clone.source")
        ttk.Label(self.body, text=source, style="Heading.TLabel").grid(
            row=0, column=1, sticky="w", pady=4
        )
        name_entry = self._entry_row(1, "gui.clone.new_name", self._name_var)
        self._path_row(2, "gui.form.install_dir", self._dir_var, self._browse_dir)
        self._hint(3, self._t("gui.clone.hint"))

        self._name_var.trace_add("write", lambda *_: self._on_name_changed())
        self._dir_var.trace_add("write", lambda *_: self._on_dir_changed())
        name_entry.focus_set()
        name_entry.select_range(0, tk.END)

    def _on_name_changed(self) -> None:
        if not self._dir_edited:
            self._updating = True
            try:
                self._dir_var.set(wsl_core.suggest_install_dir(self._name_var.get()))
            finally:
                self._updating = False

    def _on_dir_changed(self) -> None:
        if not self._updating:
            self._dir_edited = True

    def _browse_dir(self) -> None:
        path = filedialog.askdirectory(
            parent=self, title=self._t("gui.form.browse_dir"), mustexist=False
        )
        if path:
            self._dir_var.set(os.path.normpath(path))

    def _collect(self) -> CloneRequest | None:
        name = self._name_var.get().strip()
        install_dir = self._dir_var.get().strip()
        errors = wsl_core.validate_clone_form(name, install_dir, self._existing, self._language)
        if not self._show_errors(errors):
            return None
        return CloneRequest(name=name, install_dir=install_dir)

    @classmethod
    def ask(cls, parent: tk.Misc, source: str, existing: Sequence[str]) -> CloneRequest | None:
        result = cls(parent, source, existing).run()
        return result if isinstance(result, CloneRequest) else None
