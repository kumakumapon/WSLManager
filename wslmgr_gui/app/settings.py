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
        self._refresh_job = self.after(self._auto_refresh_ms, self._schedule_auto_refresh)

    def _set_auto_refresh_interval(self, seconds: int) -> None:
        """自動更新の間隔を変更します (自動更新中なら新しい間隔で予約し直します)。"""
        if seconds not in wsl_core.AUTO_REFRESH_INTERVALS:
            return
        self._settings["auto_refresh_interval"] = seconds
        self._auto_refresh_ms = seconds * 1000
        if self._refresh_job:
            self.after_cancel(self._refresh_job)
            self._refresh_job = self.after(self._auto_refresh_ms, self._schedule_auto_refresh)
        self._save_settings()
        self._set_status(self._t("gui.status.interval_changed", seconds=seconds))

    # ── テーマ切り替え ────────────────────────────────────────────────────

    def _change_theme(self, theme_name: str) -> None:
        """ttk テーマを切り替えます。"""
        try:
            style = ttk.Style(self)
            style.theme_use(theme_name)
        except tk.TclError:
            self._set_status(self._t("gui.status.theme_failed", theme=theme_name))
            return
        self._current_theme = theme_name
        # テーマを変えると名前付きスタイルの設定が失われるため登録し直す
        self._reapply_styles()
        self._set_status(self._t("gui.status.theme_changed", theme=theme_name))
        self._save_settings()

    def _change_language(self, language: str) -> None:
        """表示言語を保存し、その場で画面を作り直して反映します。"""
        self._settings["language"] = wsl_core.normalize_language(language)
        self._save_settings()
        self._language = wsl_core.resolve_language(self._settings["language"])
        self._rebuild_ui()
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
            "auto_refresh_interval": self._settings.get(
                "auto_refresh_interval", wsl_core.DEFAULT_SETTINGS["auto_refresh_interval"]
            ),
            "detail_panel": self._settings.get(
                "detail_panel", wsl_core.DEFAULT_SETTINGS["detail_panel"]
            ),
            "last_export_dir": self._settings.get("last_export_dir"),
        }
        wsl_core.save_settings(self._settings_path, settings)
