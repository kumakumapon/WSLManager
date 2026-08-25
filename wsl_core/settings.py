"""
wsl_core.settings - アプリ設定および設定ファイルの永続化・アトミック書き込みモジュール
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from typing import Any

from .i18n import normalize_language
from .parsing import dump_wslconfig
from .types import CURRENT_SCHEMA_VERSION

DEFAULT_SETTINGS: dict[str, Any] = {
    "schema_version": CURRENT_SCHEMA_VERSION,
    "theme": None,           # ttk テーマ名 (None はシステムデフォルト)
    "auto_refresh": False,   # 自動更新の ON/OFF
    "window_geometry": None, # ウィンドウジオメトリ "WxH+X+Y" (None は未保存)
    "sort_column": None,     # メイン一覧のソート列 ID (None は未ソート)
    "sort_desc": False,      # ソートが降順かどうか
    "snapshot_dir": None,    # スナップショット保存先 (None はデフォルト)
    "language": "auto",     # 表示言語 (auto, ja, en)
}

_GEOMETRY_RE = re.compile(r"^\d+x\d+([+-]-?\d+[+-]-?\d+)?$")
PARTIAL_WRITE_SUFFIX = ".wslmgr-partial"


def get_default_settings_path() -> str:
    """アプリ設定を保存するデフォルトファイルパスを返します。

    Windows (``sys.platform == "win32"``) では環境変数 ``APPDATA`` 配下の
    ``WSLManager/settings.json`` を、それ以外では ``~/.wslmgr/settings.json``
    を返します。ディレクトリ・ファイルの作成などの I/O は一切行いません。
    """
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        return os.path.join(appdata, "WSLManager", "settings.json")
    return os.path.expanduser("~/.wslmgr/settings.json")


def is_valid_geometry(value: Any) -> bool:
    """tkinter のウィンドウジオメトリ文字列として妥当かどうかを判定します。

    ``"WxH"`` または ``"WxH+X+Y"`` (X, Y は ``+``/``-`` 付きの整数オフセット)
    の形式のみを妥当とします。W, H は 1 以上の整数である必要があります。
    ``value`` が ``str`` でない場合は常に False を返します。
    """
    if not isinstance(value, str):
        return False
    m = _GEOMETRY_RE.match(value)
    if not m:
        return False
    width_str, height_str = value.split("x", 1)
    # height_str には "+X+Y" などが続く可能性があるため、先頭の数字部分のみを取り出す
    height_digits = re.match(r"^\d+", height_str)
    if not height_digits:
        return False
    width = int(width_str)
    height = int(height_digits.group())
    return width > 0 and height > 0


def normalize_settings(data: Any) -> dict[str, Any]:
    """任意のオブジェクトから完全な設定 dict を生成して返します。

    ``DEFAULT_SETTINGS`` の全キーを持つ新しい dict を返します。
    ``data`` が dict でない場合は ``DEFAULT_SETTINGS`` のコピーを返します。
    各キーの値は型・形式を検証し、不正な場合はデフォルト値にフォールバック
    します。``data`` に存在しない未知のキーは無視されます。
    引数・``DEFAULT_SETTINGS`` を破壊的に変更することはありません。
    """
    result = dict(DEFAULT_SETTINGS)
    if not isinstance(data, dict):
        return result

    schema_ver = data.get("schema_version")
    if isinstance(schema_ver, int) and not isinstance(schema_ver, bool) and schema_ver > 0:
        result["schema_version"] = schema_ver

    theme = data.get("theme")
    if isinstance(theme, str) and theme:
        result["theme"] = theme

    auto_refresh = data.get("auto_refresh")
    if isinstance(auto_refresh, bool):
        result["auto_refresh"] = auto_refresh

    window_geometry = data.get("window_geometry")
    if is_valid_geometry(window_geometry):
        result["window_geometry"] = window_geometry

    sort_column = data.get("sort_column")
    if isinstance(sort_column, str) and sort_column:
        result["sort_column"] = sort_column

    sort_desc = data.get("sort_desc")
    if isinstance(sort_desc, bool):
        result["sort_desc"] = sort_desc

    snapshot_dir = data.get("snapshot_dir")
    if isinstance(snapshot_dir, str) and snapshot_dir:
        result["snapshot_dir"] = snapshot_dir

    result["language"] = normalize_language(data.get("language"))

    return result


def load_settings(path: str) -> dict[str, Any]:
    """設定ファイルを読み込んで正規化した設定 dict を返します。

    起動を妨げないよう、ファイルが存在しない・権限がない・JSON として
    不正・dict でない、などいかなる失敗時にも例外を送出せず
    ``DEFAULT_SETTINGS`` のコピーを返します。
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return dict(DEFAULT_SETTINGS)
    return normalize_settings(data)


def atomic_write_text(path: str, content: str, encoding: str = "utf-8") -> bool:
    """テキストを一時ファイル経由でアトミックに書き込みます。

    同じディレクトリ内に一時ファイルを作成して書き込み、``os.replace()``
    で ``path`` に置き換えます。書き込み中にプロセスが落ちても、
    ``path`` の内容が 0 バイトや切り詰め状態になることはありません。

    保存先ディレクトリが存在しない場合は作成します。
    成功時は True、``OSError`` 発生時は False を返します（例外は送出しません）。
    """
    dir_ = os.path.dirname(path) or "."
    try:
        os.makedirs(dir_, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=dir_, prefix=".wslmgr-", suffix=".tmp")
    except OSError:
        return False
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        os.replace(tmp_path, path)
    except OSError:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return False
    return True


def partial_write_path(final_path: str) -> str:
    """アトミック書き込み用の一時パス (``<path>.wslmgr-partial``) を返します。"""
    return final_path + PARTIAL_WRITE_SUFFIX


def finalize_partial_write(partial_path: str, final_path: str) -> bool:
    """成功した部分書き込みを最終パスに ``os.replace`` で移動します。

    ``partial_path`` が存在する場合、``final_path`` に置き換えます。
    成功時 True、``OSError`` 発生時は False を返します。
    ``partial_path`` が存在しない場合も False を返します。
    """
    if not os.path.exists(partial_path):
        return False
    try:
        os.replace(partial_path, final_path)
    except OSError:
        return False
    return True


def discard_partial_write(partial_path: str) -> None:
    """部分書き込みの一時ファイルを削除します。存在しない場合は何もしません。"""
    try:
        os.remove(partial_path)
    except OSError:
        pass


def save_settings(path: str, settings: dict) -> bool:
    """設定 dict を正規化した上で JSON ファイルとしてアトミックに保存します。

    書き込みは :func:`atomic_write_text` 経由で行い、途中クラッシュで
    設定ファイルが 0 バイトや切り詰めになることを防ぎます。
    成功した場合は True を、``OSError`` が発生した場合は False を返します。
    """
    normalized = normalize_settings(settings)
    payload = json.dumps(normalized, ensure_ascii=False, indent=2) + "\n"
    return atomic_write_text(path, payload)


def save_wslconfig(path: str, sections: dict[str, dict[str, str]]) -> bool:
    """``.wslconfig`` の内容を :func:`atomic_write_text` 経由でアトミックに保存します。

    呼び出し側で素の ``open(path, "w")`` を使うと、書き込み中のクラッシュで
    ``.wslconfig`` が 0 バイトや途中までの状態のまま残ってしまう。この
    合成 API を経由することでその失敗経路を構造的に防ぐ。
    成功時は True、``OSError`` 発生時は False を返します（例外は送出しません）。
    """
    return atomic_write_text(path, dump_wslconfig(sections))
