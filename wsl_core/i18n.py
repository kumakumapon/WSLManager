"""Small, dependency-free translation helpers for WSL Manager.

The application deliberately keeps translations in source rather than adding a
runtime dependency or a catalog compilation step.  ``auto`` follows the
system locale; explicit ``ja`` and ``en`` preferences are persisted by the
settings module.
"""

from __future__ import annotations

import locale
import os
from collections.abc import Mapping

LANGUAGE_AUTO = "auto"
SUPPORTED_LANGUAGES = ("ja", "en")

_MESSAGES: Mapping[str, Mapping[str, str]] = {
    "language.system": {"ja": "システム設定", "en": "System default"},
    "language.ja": {"ja": "日本語", "en": "Japanese"},
    "language.en": {"ja": "English", "en": "English"},
    "gui.menu.file": {"ja": "ファイル", "en": "File"},
    "gui.menu.distribution": {"ja": "ディストリビューション", "en": "Distribution"},
    "gui.menu.tools": {"ja": "ツール", "en": "Tools"},
    "gui.menu.help": {"ja": "ヘルプ", "en": "Help"},
    "gui.menu.language": {"ja": "言語", "en": "Language"},
    "gui.action.import": {"ja": "インポート...", "en": "Import..."},
    "gui.action.export": {"ja": "エクスポート...", "en": "Export..."},
    "gui.action.exit": {"ja": "終了", "en": "Exit"},
    "gui.action.start_terminal": {"ja": "起動 / ターミナル", "en": "Start / Terminal"},
    "gui.action.stop": {"ja": "停止", "en": "Stop"},
    "gui.action.shutdown": {"ja": "全停止", "en": "Shut down all"},
    "gui.action.set_default": {"ja": "デフォルトに設定", "en": "Set as default"},
    "gui.action.convert": {"ja": "WSL1/WSL2 変換", "en": "Convert WSL1/WSL2"},
    "gui.action.install": {"ja": "インストール...", "en": "Install..."},
    "gui.action.unregister": {"ja": "アンインストール...", "en": "Unregister..."},
    "gui.action.details": {"ja": "詳細情報...", "en": "Details..."},
    "gui.action.processes": {"ja": "プロセス一覧", "en": "Processes"},
    "gui.action.explorer": {"ja": "エクスプローラーで開く", "en": "Open in Explorer"},
    "gui.action.optimize": {"ja": "ディスク最適化...", "en": "Optimize disk..."},
    "gui.action.snapshots": {"ja": "スナップショット管理...", "en": "Manage snapshots..."},
    "gui.action.mount": {"ja": "ディスクのマウント...", "en": "Mount disk..."},
    "gui.action.unmount": {"ja": "ディスクのアンマウント...", "en": "Unmount disk..."},
    "gui.action.wsl_config": {"ja": "WSL 設定 (.wslconfig)", "en": "WSL settings (.wslconfig)"},
    "gui.action.log": {"ja": "操作ログ...", "en": "Operation log..."},
    "gui.action.theme": {"ja": "テーマ", "en": "Theme"},
    "gui.action.wsl_version": {"ja": "WSL バージョン情報...", "en": "WSL version..."},
    "gui.action.update_wsl": {"ja": "WSL を更新", "en": "Update WSL"},
    "gui.action.about": {"ja": "このアプリについて...", "en": "About..."},
    "gui.toolbar.start": {"ja": "▶  起動", "en": "▶  Start"},
    "gui.toolbar.stop": {"ja": "■  停止", "en": "■  Stop"},
    "gui.toolbar.shutdown": {"ja": "⬛  全停止", "en": "⬛  Shut down"},
    "gui.toolbar.terminal": {"ja": "🖥  ターミナル", "en": "🖥  Terminal"},
    "gui.toolbar.processes": {"ja": "📋  プロセス", "en": "📋  Processes"},
    "gui.toolbar.refresh": {"ja": "🔄  更新", "en": "🔄  Refresh"},
    "gui.toolbar.install": {"ja": "📦  インストール", "en": "📦  Install"},
    "gui.toolbar.import": {"ja": "📥  インポート", "en": "📥  Import"},
    "gui.toolbar.export": {"ja": "📤  エクスポート", "en": "📤  Export"},
    "gui.toolbar.wsl_config": {"ja": "⚙  WSL設定", "en": "⚙  WSL settings"},
    "gui.auto_refresh": {"ja": "自動更新", "en": "Auto refresh"},
    "gui.history.show": {"ja": "📈 履歴を表示", "en": "📈 Show history"},
    "gui.status.ready": {"ja": "準備完了", "en": "Ready"},
    "gui.column.name": {"ja": "ディストリビューション名", "en": "Distribution"},
    "gui.column.state": {"ja": "状態", "en": "State"},
    "gui.column.version": {"ja": "バージョン", "en": "Version"},
    "gui.column.memory": {"ja": "メモリ(MB)", "en": "Memory (MB)"},
    "gui.column.disk": {"ja": "ディスク(GB)", "en": "Disk (GB)"},
    "gui.column.ip": {"ja": "IPアドレス", "en": "IP address"},
    "gui.language_changed": {
        "ja": "言語設定を保存しました。変更は次回の起動時に反映されます。",
        "en": "Language preference saved. It will be applied next time the app starts.",
    },
    "cli.description": {
        "ja": "WSL Manager - コマンドラインインターフェース",
        "en": "WSL Manager command-line interface",
    },
    "cli.language": {
        "ja": "表示言語 (auto, ja, en。既定: 保存済み設定またはシステム設定)",
        "en": "Display language (auto, ja, en; default: saved preference or system default)",
    },
    "cli.quiet": {
        "ja": "成功時のメッセージ出力を抑制します",
        "en": "Suppress success messages",
    },
    "cli.list": {
        "ja": "WSL ディストリビューションの一覧を表示します",
        "en": "List WSL distributions",
    },
    "cli.format": {
        "ja": "出力フォーマット (既定: table)",
        "en": "Output format (default: table)",
    },
    "cli.with_ip": {
        "ja": "実行中ディストリビューションの IP アドレスも取得します",
        "en": "Include IP addresses for running distributions",
    },
    "cli.with_disk": {
        "ja": "実行中ディストリビューションのディスク使用量も取得します",
        "en": "Include disk usage for running distributions",
    },
    "cli.all_info": {
        "ja": "IP アドレスおよびディスク使用量を含めて表示します",
        "en": "Include IP addresses and disk usage",
    },
    "cli.list_error": {
        "ja": "ディストリビューション一覧の取得に失敗しました。",
        "en": "Failed to get the distribution list.",
    },
    "cli.error": {"ja": "エラー", "en": "Error"},
    "cli.header.name": {"ja": "名前", "en": "Name"},
    "cli.header.state": {"ja": "状態", "en": "State"},
    "cli.header.version": {"ja": "バージョン", "en": "Version"},
    "cli.header.default": {"ja": "既定", "en": "Default"},
}


def normalize_language(value: object) -> str:
    """Return a supported stored language value, falling back to ``auto``."""
    if isinstance(value, str) and value in (LANGUAGE_AUTO, *SUPPORTED_LANGUAGES):
        return value
    return LANGUAGE_AUTO


def detect_system_language(locale_name: str | None = None) -> str:
    """Detect Japanese systems; use English as the safe fallback for all others."""
    if locale_name is None:
        try:
            locale_name = locale.getlocale()[0]
        except (ValueError, locale.Error):
            locale_name = None
        locale_name = locale_name or os.environ.get("LANG") or os.environ.get("LC_ALL")
    return "ja" if locale_name and locale_name.lower().startswith("ja") else "en"


def resolve_language(preference: object, locale_name: str | None = None) -> str:
    """Resolve an explicit preference or the current system language."""
    preference = normalize_language(preference)
    return detect_system_language(locale_name) if preference == LANGUAGE_AUTO else preference


def translate(key: str, language: object = LANGUAGE_AUTO, **values: object) -> str:
    """Translate ``key`` and interpolate named values; return the key if unknown."""
    message = _MESSAGES.get(key, {}).get(resolve_language(language), key)
    return message.format(**values)
