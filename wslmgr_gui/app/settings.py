"""自動更新・テーマ・言語・設定保存の Mixin。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import wsl_core
from wslmgr_gui.app.base import AppBase


class SettingsMixin(AppBase):
    """``WSLManager`` に混ぜ込む、自動更新・テーマ・言語の切替と設定の保存。"""

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
