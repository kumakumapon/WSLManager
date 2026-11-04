"""同梱ファイル (アイコンなど) の場所と、配布物の中のほかの実行ファイルの検索。

ソースから実行したとき (``python wslmgr.py``) と、PyInstaller で 1 ファイルの exe に
したとき (同梱ファイルは起動時に ``sys._MEIPASS`` へ展開される) の両方で同じパスを
返せるようにする。
"""

from __future__ import annotations

import os
import sys

# リポジトリのルート (この ``wslmgr_gui`` パッケージの 1 つ上)
_SOURCE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CLI_EXECUTABLE = "wslmgr.exe"


def is_frozen() -> bool:
    """PyInstaller でビルドした exe として動いていれば True。"""
    return bool(getattr(sys, "frozen", False))


def resource_root() -> str:
    """同梱ファイルの基点フォルダー。"""
    bundle = getattr(sys, "_MEIPASS", None)
    return bundle if isinstance(bundle, str) and bundle else _SOURCE_ROOT


def resource_path(*parts: str) -> str:
    """同梱ファイル (例: ``resource_path("assets", "wslmanager.ico")``) の絶対パス。"""
    return os.path.join(resource_root(), *parts)


def app_directory() -> str:
    """利用者から見たアプリのフォルダー (exe の置き場所、ソース実行ならリポジトリ)。"""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return _SOURCE_ROOT


def find_cli_executable() -> str | None:
    """GUI と同じフォルダーにあるコマンドライン版 (``wslmgr.exe``) のパスを返します。

    インストーラ版とポータブル版の ZIP は、``WSLManager.exe`` と ``wslmgr.exe`` を
    同じフォルダーに置く。見つからなければ ``None``。
    """
    candidate = os.path.join(app_directory(), "dist", CLI_EXECUTABLE)
    for path in (os.path.join(app_directory(), CLI_EXECUTABLE), candidate):
        if os.path.isfile(path):
            return path
    return None
