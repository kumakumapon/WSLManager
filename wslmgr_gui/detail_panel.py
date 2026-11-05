"""メイン画面右側の詳細パネル (選択中ディストリビューションの情報と操作ボタン)。

一覧で選んだディストリビューションの状態・リソース・場所をその場で見せ、よく使う
操作をボタンで並べる。操作の可否 (起動中は「起動」を無効にする等) は
:func:`wsl_core.action_availability` の結果をそのまま反映する。

このパネル自身は ``wsl.exe`` を実行しない (表示中のディストリビューションを起動して
しまわないよう、情報は一覧の取得結果とレジストリの値だけを使う)。
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Mapping
from tkinter import ttk

# (操作 ID, 翻訳キー, スタイル) のボタン配置。None は区切り (見出し) を表す。
# 1 行に 2 個ずつ並べる。``"wide"`` は 1 行を占有する。
_LAYOUT: tuple[tuple[str, ...] | str, ...] = (
    ("terminal",),
    ("start", "stop"),
    ("explorer", "processes"),
    "gui.panel.section_backup",
    ("snapshot", "export"),
    ("clone",),
    "gui.panel.section_manage",
    ("set_default", "convert"),
    ("distro_conf", "optimize"),
    ("details",),
    "gui.panel.section_danger",
    ("unregister",),
)

_BUTTON_KEYS: dict[str, str] = {
    "terminal": "gui.panel.terminal",
    "start": "gui.panel.start",
    "stop": "gui.panel.stop",
    "explorer": "gui.panel.explorer",
    "processes": "gui.panel.processes",
    "snapshot": "gui.panel.snapshot",
    "export": "gui.panel.export",
    "clone": "gui.panel.clone",
    "set_default": "gui.panel.set_default",
    "convert": "gui.panel.convert",
    "distro_conf": "gui.panel.distro_conf",
    "optimize": "gui.panel.optimize",
    "details": "gui.panel.details",
    "unregister": "gui.panel.unregister",
}

_BUTTON_STYLES: dict[str, str] = {
    "terminal": "Primary.TButton",
    "unregister": "Danger.TButton",
}


def _format_value(value: object, unit: str) -> str:
    text = str(value) if value is not None else ""
    if text in ("", "-"):
        return "—"
    return f"{text} {unit}".strip()


class DetailPanel(ttk.Frame):
    """選択中ディストリビューションの情報と操作ボタンを表示するパネル。"""

    def __init__(
        self,
        parent: tk.Misc,
        translate: Callable[..., str],
        commands: Mapping[str, Callable[[], None]],
    ) -> None:
        super().__init__(parent, padding=(12, 10))
        self._t = translate
        self._commands = commands
        self.buttons: dict[str, ttk.Button] = {}
        self._build()
        self.show(None)

    # ── 構築 ─────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)

        # 未選択時の案内
        self._placeholder = ttk.Label(
            self,
            text=self._t("gui.panel.placeholder"),
            style="Muted.TLabel",
            wraplength=240,
            justify=tk.LEFT,
        )

        self._content = ttk.Frame(self)
        self._content.columnconfigure(0, weight=1)

        self._name_var = tk.StringVar()
        ttk.Label(self._content, textvariable=self._name_var, style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )

        badges = ttk.Frame(self._content)
        badges.grid(row=1, column=0, sticky="w", pady=(4, 8))
        self._state_badge = ttk.Label(badges)
        self._state_badge.pack(side=tk.LEFT, padx=(0, 4))
        self._version_badge = ttk.Label(badges, style="BadgeVersion.TLabel")
        self._version_badge.pack(side=tk.LEFT, padx=(0, 4))
        self._default_badge = ttk.Label(
            badges, text=self._t("gui.panel.badge_default"), style="BadgeDefault.TLabel"
        )

        info = ttk.Frame(self._content)
        info.grid(row=2, column=0, sticky="ew")
        info.columnconfigure(1, weight=1)
        self._info_vars: dict[str, tk.StringVar] = {}
        for row, (key, label_key) in enumerate(
            (
                ("cpu", "gui.column.cpu"),
                ("memory", "gui.panel.memory"),
                ("disk", "gui.panel.disk"),
                ("ip", "gui.column.ip"),
            )
        ):
            ttk.Label(info, text=self._t(label_key), style="Muted.TLabel").grid(
                row=row, column=0, sticky="w", padx=(0, 10), pady=1
            )
            var = tk.StringVar(value="—")
            self._info_vars[key] = var
            ttk.Label(info, textvariable=var).grid(row=row, column=1, sticky="w", pady=1)

        self._copy_ip = ttk.Button(
            info,
            text=self._t("gui.panel.copy"),
            command=self._commands["copy_ip"],
            width=6,
        )
        self._copy_ip.grid(row=3, column=2, sticky="e")
        self.buttons["copy_ip"] = self._copy_ip

        ttk.Label(info, text=self._t("gui.panel.location"), style="Muted.TLabel").grid(
            row=4, column=0, sticky="nw", padx=(0, 10), pady=(1, 0)
        )
        self._location_var = tk.StringVar(value="—")
        # 長いパスでも折り返して全体を見せる。選択・コピーできるよう読み取り専用 Entry にする
        self._location = ttk.Entry(info, textvariable=self._location_var, state="readonly")
        self._location.grid(row=4, column=1, columnspan=2, sticky="ew", pady=(1, 0))

        actions = ttk.Frame(self._content)
        actions.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        actions.columnconfigure(0, weight=1, uniform="action")
        actions.columnconfigure(1, weight=1, uniform="action")
        row = 0
        for entry in _LAYOUT:
            if isinstance(entry, str):
                ttk.Label(actions, text=self._t(entry), style="Section.TLabel").grid(
                    row=row, column=0, columnspan=2, sticky="w", pady=(10, 2)
                )
                row += 1
                continue
            for column, action in enumerate(entry):
                button = ttk.Button(
                    actions,
                    text=self._t(_BUTTON_KEYS[action]),
                    command=self._commands[action],
                    style=_BUTTON_STYLES.get(action, "TButton"),
                )
                button.grid(
                    row=row,
                    column=column,
                    columnspan=2 if len(entry) == 1 else 1,
                    sticky="ew",
                    padx=(0 if column == 0 else 2, 0 if column == len(entry) - 1 else 2),
                    pady=2,
                )
                self.buttons[action] = button
            row += 1

    # ── 表示 ─────────────────────────────────────────────────────────────

    def show(
        self,
        distro: Mapping[str, object] | None,
        availability: Mapping[str, bool] | None = None,
    ) -> None:
        """``distro`` の内容を表示します。``None`` なら未選択の案内を表示します。"""
        if distro is None:
            self._content.grid_forget()
            self._placeholder.grid(row=0, column=0, sticky="nw")
            self.set_enabled(availability or {})
            return
        self._placeholder.grid_forget()
        self._content.grid(row=0, column=0, sticky="nsew")

        self._name_var.set(str(distro.get("name", "")))
        running = distro.get("state") == "Running"
        self._state_badge.configure(
            text=("● " if running else "○ ")
            + self._t("gui.state.running" if running else "gui.state.stopped"),
            style="BadgeRunning.TLabel" if running else "BadgeStopped.TLabel",
        )
        version = str(distro.get("version") or "")
        if version:
            self._version_badge.configure(text=f"WSL {version}")
            self._version_badge.pack(side=tk.LEFT, padx=(0, 4))
        else:
            self._version_badge.pack_forget()
        if distro.get("default"):
            self._default_badge.pack(side=tk.LEFT, padx=(0, 4))
        else:
            self._default_badge.pack_forget()

        self._info_vars["cpu"].set(_format_value(distro.get("cpu"), "%"))
        self._info_vars["memory"].set(_format_value(distro.get("memory"), "MB"))
        self._info_vars["disk"].set(_format_value(distro.get("disk"), "GB"))
        self._info_vars["ip"].set(_format_value(distro.get("ip"), ""))
        location = distro.get("location")
        self._location_var.set(str(location) if location else "—")
        self.set_enabled(availability or {})

    def set_enabled(self, availability: Mapping[str, bool]) -> None:
        """操作 ID ごとにボタンの有効/無効を切り替えます (未指定の ID は無効)。"""
        for action, button in self.buttons.items():
            button.state(["!disabled"] if availability.get(action) else ["disabled"])
