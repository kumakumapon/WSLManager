"""メイン画面と各ダイアログで共有する ttk スタイル・フォント・色。

色はすべてここに集め、ウィジェット側では名前付きスタイル (``"Danger.TButton"`` など) と
:data:`COLORS` だけを参照する。
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

COLORS: dict[str, str] = {
    "running": "#1a7f37",
    "stopped": "#6e7781",
    "danger": "#cf222e",
    "muted": "#57606a",
    "accent": "#0969da",
    "stripe": "#f3f5f8",
    "badge_running_bg": "#dafbe1",
    "badge_stopped_bg": "#eaeef2",
    "badge_default_bg": "#fff1c2",
    "badge_default_fg": "#7d4e00",
    "badge_version_bg": "#ddf4ff",
    "error_bg": "#ffebe9",
    "info_bg": "#ddf4ff",
}

# 既定フォントの最小サイズ (pt)。Windows の既定 (Segoe UI 9pt) は日本語だと読みにくい。
MIN_FONT_POINTS = 10

_NAMED_FONTS = ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkTooltipFont")


def _enlarge_named_fonts(root: tk.Misc) -> None:
    for name in _NAMED_FONTS:
        try:
            font = tkfont.nametofont(name, root=root)
        except tk.TclError:
            continue
        size = int(font.cget("size"))
        # 負の値はピクセル指定。DPI に追従しないため、ポイント指定 (正の値) だけを調整する。
        if 0 < size < MIN_FONT_POINTS:
            font.configure(size=MIN_FONT_POINTS)


def derived_font(root: tk.Misc, *, delta: int = 0, bold: bool = False) -> tkfont.Font:
    """``TkDefaultFont`` を基準に、サイズ差・太字を指定したフォントを作ります。"""
    base = tkfont.nametofont("TkDefaultFont", root=root)
    size = int(base.cget("size"))
    # ポイント指定なら加算、ピクセル指定 (負) なら絶対値を大きくする
    new_size = size + delta if size > 0 else size - delta
    return tkfont.Font(
        root=root,
        family=base.cget("family"),
        size=new_size,
        weight="bold" if bold else "normal",
    )


def apply_styles(root: tk.Misc) -> dict[str, tkfont.Font]:
    """スタイルを登録し、ウィジェット側で使うフォントを返します。

    テーマを切り替えた後にも呼び直すこと (テーマ変更で一部の設定が失われるため)。
    """
    _enlarge_named_fonts(root)
    fonts = {
        "title": derived_font(root, delta=4, bold=True),
        "heading": derived_font(root, bold=True),
        "empty": derived_font(root, delta=2),
    }
    style = ttk.Style(root)
    linespace = tkfont.nametofont("TkDefaultFont", root=root).metrics("linespace")

    # Tk 8.6 の Treeview は行の高さが DPI・フォントに追従しないため、明示的に広げる
    style.configure("Treeview", rowheight=int(linespace * 1.7))
    style.configure("Treeview.Heading", font=fonts["heading"], padding=(4, 3))

    style.configure("Toolbar.TButton", padding=(8, 3))
    style.configure("Primary.TButton", font=fonts["heading"])
    style.configure("Danger.TButton", foreground=COLORS["danger"])
    style.map("Danger.TButton", foreground=[("disabled", "#d0a0a0")])

    style.configure("Title.TLabel", font=fonts["title"])
    style.configure("Heading.TLabel", font=fonts["heading"])
    style.configure("Section.TLabel", font=fonts["heading"], foreground=COLORS["muted"])
    style.configure("Muted.TLabel", foreground=COLORS["muted"])
    style.configure("Empty.TLabel", font=fonts["empty"], foreground=COLORS["muted"])
    style.configure("Error.TLabel", foreground=COLORS["danger"])

    badge_padding = (6, 1)
    style.configure(
        "BadgeRunning.TLabel",
        background=COLORS["badge_running_bg"],
        foreground=COLORS["running"],
        padding=badge_padding,
    )
    style.configure(
        "BadgeStopped.TLabel",
        background=COLORS["badge_stopped_bg"],
        foreground=COLORS["muted"],
        padding=badge_padding,
    )
    style.configure(
        "BadgeDefault.TLabel",
        background=COLORS["badge_default_bg"],
        foreground=COLORS["badge_default_fg"],
        padding=badge_padding,
    )
    style.configure(
        "BadgeVersion.TLabel",
        background=COLORS["badge_version_bg"],
        foreground=COLORS["accent"],
        padding=badge_padding,
    )
    return fonts


def configure_tree_tags(tree: ttk.Treeview) -> None:
    """一覧の行タグ (状態の色・縞模様) を設定します。"""
    tree.tag_configure("running", foreground=COLORS["running"])
    tree.tag_configure("stopped", foreground=COLORS["stopped"])
    tree.tag_configure("stripe", background=COLORS["stripe"])
