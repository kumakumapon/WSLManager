"""
wsl_core.snapshot - ディストリビューションのスナップショット管理・メタデータ操作モジュール
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from typing import Any

from .settings import atomic_write_text
from .types import CURRENT_SCHEMA_VERSION

SNAPSHOT_TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S"
_SNAPSHOT_FORBIDDEN_CHARS = set('\\/:*?"<>|')


def get_default_snapshot_dir() -> str:
    """スナップショットを保存するデフォルトディレクトリのパスを返します。

    Windows (``sys.platform == "win32"``) では環境変数 ``USERPROFILE`` 配下の
    ``WSLSnapshots`` を、それ以外では ``~/WSLSnapshots`` を返します。
    ディレクトリの作成などの I/O は一切行いません。
    """
    if sys.platform == "win32":
        return os.path.join(os.environ.get("USERPROFILE", ""), "WSLSnapshots")
    return os.path.expanduser("~/WSLSnapshots")


def sanitize_snapshot_name(name: str) -> str:
    """スナップショット名をファイル名として安全な文字列に変換します。

    Windows/POSIX のファイル名で使用できない文字 (``\\ / : * ? " < > |``)、
    制御文字、空白文字を全て ``_`` に置き換えます。前後の ``_`` は除去し、
    結果が空文字列になった場合は ``"distro"`` を返します。
    """
    chars = []
    for ch in name:
        if ch in _SNAPSHOT_FORBIDDEN_CHARS or ord(ch) < 0x20 or ch.isspace():
            chars.append("_")
        else:
            chars.append(ch)
    result = "".join(chars).strip("_")
    return result or "distro"


def build_snapshot_basename(distro_name: str, timestamp: str) -> str:
    """スナップショットファイルのベース名 (拡張子なし) を生成します。

    ``sanitize_snapshot_name`` でディストリ名を安全な文字列に変換した上で
    ``"{name}_{timestamp}"`` の形式で返します。呼び出し側で ``.tar`` や
    ``.json`` の拡張子を付与してください。
    """
    return f"{sanitize_snapshot_name(distro_name)}_{timestamp}"


def build_snapshot_metadata(
    distro_name: str,
    wsl_version: str,
    comment: str,
    size_bytes: int,
    created_at: str,
    tar_file: str,
    schema_version: int = CURRENT_SCHEMA_VERSION,
) -> dict[str, Any]:
    """スナップショットのメタデータ dict を生成します。

    ``tar_file`` には tar ファイルのベース名 (フルパスではない) を指定します。
    ``created_at`` は ISO-8601 形式の文字列を想定します。
    """
    return {
        "schema_version": schema_version,
        "distro_name": distro_name,
        "wsl_version": wsl_version,
        "comment": comment,
        "size_bytes": size_bytes,
        "created_at": created_at,
        "tar_file": tar_file,
    }


def normalize_snapshot_metadata(data: Any) -> dict[str, Any] | None:
    """任意のオブジェクトからスナップショットメタデータ dict を正規化します。

    ``data`` が dict でない場合、``distro_name`` または ``tar_file`` が
    空でない文字列でない場合、および ``tar_file`` がベース名以外
    (パス区切り文字や ``..`` を含む) の場合は ``None`` を返します。それ以外の場合は
    スキーマバージョンを含むキーを持つ新しい dict を返します。値の型・形式が不正な場合は
    妥当な値にフォールバックします。引数を破壊的に変更することはありません。
    """
    if not isinstance(data, dict):
        return None

    distro_name = data.get("distro_name")
    if not isinstance(distro_name, str) or not distro_name:
        return None

    tar_file = data.get("tar_file")
    if not isinstance(tar_file, str) or not tar_file:
        return None
    # tar_file はベース名のみ許可する。パス区切りや ".." を含む値を許すと
    # 保存先ディレクトリ外のファイルを指せてしまう (パストラバーサル)。
    if "/" in tar_file or "\\" in tar_file or tar_file in (".", ".."):
        return None

    schema_ver = data.get("schema_version", 1)
    if not (isinstance(schema_ver, int) and not isinstance(schema_ver, bool) and schema_ver > 0):
        schema_ver = 1

    wsl_version = data.get("wsl_version")
    if isinstance(wsl_version, str) and wsl_version in ("1", "2"):
        pass
    elif (
        isinstance(wsl_version, int)
        and not isinstance(wsl_version, bool)
        and wsl_version in (1, 2)
    ):
        wsl_version = str(wsl_version)
    else:
        wsl_version = ""

    comment = data.get("comment")
    if not isinstance(comment, str):
        comment = ""

    created_at = data.get("created_at")
    if not isinstance(created_at, str):
        created_at = ""

    size_bytes = data.get("size_bytes")
    if not (isinstance(size_bytes, int) and not isinstance(size_bytes, bool) and size_bytes >= 0):
        size_bytes = 0

    return {
        "schema_version": schema_ver,
        "distro_name": distro_name,
        "wsl_version": wsl_version,
        "comment": comment,
        "size_bytes": size_bytes,
        "created_at": created_at,
        "tar_file": tar_file,
    }


def load_snapshots(snapshot_dir: str) -> list[dict]:
    """指定ディレクトリ内のスナップショットメタデータを読み込んで返します。

    ``snapshot_dir`` 直下 (非再帰) の ``.json`` ファイルを走査し、各ファイルを
    ``normalize_snapshot_metadata`` で正規化します。読み込みや JSON の解析に
    失敗したファイル、正規化できなかったファイルは読み飛ばします。
    各エントリには ``json_path`` (json ファイルのフルパス)、``tar_path``
    (tar ファイルのフルパス)、``tar_exists`` (tar ファイルが存在するかどうか)
    を追加します。``created_at`` の降順 (新しい順、値が空のものは末尾) に
    ソートして返します。ディレクトリが存在しない、または一覧取得に失敗した
    場合は空リストを返します。例外は送出しません。
    """
    try:
        names = os.listdir(snapshot_dir)
    except OSError:
        return []

    results = []
    for name in names:
        if not name.endswith(".json"):
            continue
        json_path = os.path.join(snapshot_dir, name)
        try:
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        normalized = normalize_snapshot_metadata(data)
        if normalized is None:
            continue
        tar_path = os.path.join(snapshot_dir, normalized["tar_file"])
        normalized["json_path"] = json_path
        normalized["tar_path"] = tar_path
        normalized["tar_exists"] = os.path.isfile(tar_path)
        results.append(normalized)

    results.sort(key=lambda entry: entry["created_at"], reverse=True)
    return results


def total_snapshots_size(snapshots: list[dict]) -> int:
    """スナップショット一覧の合計サイズ (バイト) を返します。

    ``tar_exists`` が True (キーが存在しない場合も True として扱う) の
    エントリの ``size_bytes`` の合計を返します。``size_bytes`` が非負整数
    でないエントリは 0 として扱います。
    """
    total = 0
    for entry in snapshots:
        if not entry.get("tar_exists", True):
            continue
        size = entry.get("size_bytes")
        if isinstance(size, int) and not isinstance(size, bool) and size >= 0:
            total += size
    return total


def write_snapshot_metadata(json_path: str, metadata: dict) -> bool:
    """スナップショットのメタデータ dict を JSON ファイルとしてアトミックに保存します。

    書き込みは :func:`atomic_write_text` 経由で行うため、途中クラッシュで
    メタデータファイルが 0 バイトや切り詰めになることを防ぎます。
    成功した場合は True を、``OSError`` が発生した場合は False を返します。
    """
    payload = json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
    return atomic_write_text(json_path, payload)


def build_distro_snapshot(distros: list[dict], timestamp: str | None = None) -> dict:
    """ディストロ一覧のスナップショット dict を作成して返します。

    引数 distros は parse_distro_list が返すリストを想定します。
    timestamp が None の場合は現在時刻を ISO 8601 形式 (datetime.now().isoformat()) で設定します。
    返り値の構造:
        {
            "timestamp": <ISO 8601 文字列>,
            "distros": <distros のコピー>,
            "count": <ディストロ数>,
            "running": <state が "Running" のディストロ数>,
        }
    副作用は一切なく、I/O を行いません。
    """
    ts = timestamp if timestamp is not None else datetime.now().isoformat()
    running = sum(1 for d in distros if d.get("state") == "Running")
    return {
        "timestamp": ts,
        "distros": distros,
        "count": len(distros),
        "running": running,
    }


def format_snapshot_summary(snapshot: dict) -> str:
    """スナップショット dict を人間が読みやすい日本語の要約文字列にして返します。

    フォーマット:
        スナップショット: {timestamp}
        ディストリビューション数: {count} (実行中: {running})
          {name}: {state}
          ...
    各ディストロ行はスペース2文字のインデントで "{name}: {state}" の形式です。
    """
    lines: list[str] = []
    lines.append(f"スナップショット: {snapshot['timestamp']}")
    lines.append(
        f"ディストリビューション数: {snapshot['count']} (実行中: {snapshot['running']})"
    )
    for distro in snapshot.get("distros", []):
        lines.append(f"  {distro['name']}: {distro['state']}")
    return "\n".join(lines) + "\n"


def diff_snapshots(old: dict, new: dict) -> dict:
    """2 つのスナップショットを比較して差分 dict を返します。

    比較はディストロ名をキーとして行います。
    返り値の構造:
        {
            "added":         [新規ディストロ名のリスト],
            "removed":       [削除されたディストロ名のリスト],
            "state_changed": [
                {"name": <名前>, "old_state": <旧 state>, "new_state": <新 state>},
                ...
            ],
        }
    """
    old_map = {d["name"]: d for d in old.get("distros", [])}
    new_map = {d["name"]: d for d in new.get("distros", [])}

    old_names = set(old_map)
    new_names = set(new_map)

    added = sorted(new_names - old_names)
    removed = sorted(old_names - new_names)
    state_changed = []
    for name in sorted(old_names & new_names):
        old_state = old_map[name].get("state", "")
        new_state = new_map[name].get("state", "")
        if old_state != new_state:
            state_changed.append({"name": name, "old_state": old_state, "new_state": new_state})

    return {"added": added, "removed": removed, "state_changed": state_changed}
