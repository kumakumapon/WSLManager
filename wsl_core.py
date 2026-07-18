"""
wsl_core - WSL Manager の純粋ロジックモジュール

tkinter・winreg に依存しない純粋関数のみを提供します。
subprocess 呼び出しも含まず、テキスト解析・エンコード・設定ファイルの
読み書きといったロジックを単体テスト可能な形で実装しています。
"""

from __future__ import annotations

import configparser
import io
import json
import os
import re
import sys
from datetime import datetime


def decode_wsl_output(raw: bytes) -> str:
    """WSL コマンドの出力を適切なエンコーディングでデコードします。

    wsl.exe の出力は UTF-16 LE (BOM 付き) で返ることが多いため、
    まず UTF-16 LE を試み、失敗した場合は UTF-8 にフォールバックします。
    """
    # BOM (FF FE) があれば取り除いてデコード
    if raw.startswith(b"\xff\xfe"):
        return raw[2:].decode("utf-16-le", errors="replace")
    # BOM なしで UTF-16 LE を試みる
    try:
        text = raw.decode("utf-16-le", errors="strict")
        # 意味のある文字列が得られたか簡易チェック
        if text.strip():
            return text
    except (UnicodeDecodeError, ValueError):
        pass
    # フォールバック: UTF-8 / cp932
    for enc in ("utf-8", "cp932", "latin-1"):
        try:
            return raw.decode(enc, errors="replace")
        except Exception:
            continue
    return raw.decode("ascii", errors="replace")


def is_numeric(val: str) -> bool:
    """文字列が float に変換可能かどうかを返します。"""
    try:
        float(val)
        return True
    except (ValueError, TypeError):
        return False


def normalize_base_path(base_path: str) -> str:
    """レジストリ BasePath の ``\\\\?\\`` プレフィックス（4文字）を除去して返します。

    BasePath が ``\\\\?\\C:\\...`` 形式の場合に先頭4文字を取り除き、
    通常の ``C:\\...`` 形式に正規化します。プレフィックスがない場合はそのまま返します。
    """
    if base_path.startswith("\\\\?\\"):
        return base_path[4:]
    return base_path


def parse_distro_list(output: str) -> list[dict]:
    """``wsl --list --verbose`` のデコード済みテキスト出力を解析してディストロ一覧を返します。

    先頭1行はヘッダ行としてスキップします。各行について ``*`` の有無でデフォルト判定を行い、
    2つ以上の連続空白でフィールドを分割します。
    返り値の各 dict のキーは name, state, version, default(bool), cpu, memory, disk です。
    subprocess 呼び出しは含まず、引数はデコード済みテキストを受け取ります。
    """
    distros: list[dict] = []
    lines = output.splitlines()
    # 1行目はヘッダ ("  NAME   STATE   VERSION") なのでスキップ
    for raw_line in lines[1:]:
        if not raw_line.strip():
            continue
        is_default = raw_line.lstrip().startswith("*") or raw_line.startswith("*")
        # 先頭の "* " と余分な空白を除去してからフィールドを分割
        clean = raw_line.strip().lstrip("*").strip()
        # 2 つ以上の連続空白でフィールドを分割
        parts = re.split(r"\s{2,}", clean)
        if len(parts) >= 3:
            name, state, version = parts[0], parts[1], parts[2]
        elif len(parts) == 2:
            name, state, version = parts[0], parts[1], ""
        elif len(parts) == 1 and parts[0]:
            name, state, version = parts[0], "", ""
        else:
            continue
        distros.append(
            {
                "name": name.strip(),
                "state": state.strip(),
                "version": version.strip(),
                "default": is_default,
                "cpu": "-",
                "memory": "-",
                "disk": "-",
                "ip": "-",
            }
        )
    return distros


def parse_online_distros(output: str) -> list[str]:
    """``wsl --list --online`` のデコード済みテキスト出力を解析してディストロ名一覧を返します。

    NAME で始まる行・``-`` で始まる行・空行はスキップします。
    各行を2つ以上の連続空白で分割し、先頭フィールドをディストロ名として収集します。
    subprocess 呼び出しは含まず、引数はデコード済みテキストを受け取ります。
    """
    names: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("NAME") or line.startswith("-"):
            continue
        parts = re.split(r"\s{2,}", line)
        if parts and parts[0]:
            names.append(parts[0].strip())
    return names


def parse_process_list(output: str) -> list[dict]:
    """``ps -eo pid,user,pcpu,rss,comm`` のデコード済みテキスト出力を解析してプロセス一覧を返します。

    先頭1行はヘッダ行としてスキップします。各行を最大5フィールドで分割し、
    5フィールド未満や数値変換失敗の行はスキップします。
    返り値の各 dict のキーは pid(int), user, cpu, memory, command です。
    cpu は ``f"{float:.1f}"``、memory は RSS(KB) を MB 換算した ``f"{rss/1024:.1f}"`` 形式です。
    """
    processes: list[dict] = []
    for line in output.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        try:
            processes.append({
                "pid": int(parts[0]),
                "user": parts[1],
                "cpu": f"{float(parts[2]):.1f}",
                "memory": f"{float(parts[3]) / 1024:.1f}",
                "command": parts[4],
            })
        except ValueError:
            continue
    return processes


def parse_resource_usage(output: str) -> tuple[str, str]:
    """awk による CPU・メモリ集計出力を解析して (cpu, memory) のタプルを返します。

    ``output.split()`` で分割し、2要素未満や数値変換失敗の場合は ``("-", "-")`` を返します。
    cpu は ``f"{float:.1f}"``、memory は ``f"{float:.1f}"`` 形式です（単位は呼び出し元依存）。
    """
    parts = output.split()
    if len(parts) < 2:
        return "-", "-"
    try:
        cpu = float(parts[0])
        memory_mb = float(parts[1])
    except ValueError:
        return "-", "-"
    return f"{cpu:.1f}", f"{memory_mb:.1f}"


def build_diskpart_compact_script(vhdx_path: str) -> str:
    """diskpart で仮想ディスク (vhdx) を圧縮するスクリプトテキストを生成します。

    対象の vhdx を読み取り専用でアタッチし、``compact vdisk`` で
    未使用領域を解放してからデタッチします。パスは空白を含む場合があるため
    必ずダブルクォートで囲みます。diskpart の ``compact`` には管理者権限が必要です。
    """
    return (
        f'select vdisk file="{vhdx_path}"\n'
        "attach vdisk readonly\n"
        "compact vdisk\n"
        "detach vdisk\n"
        "exit\n"
    )


def parse_wslconfig(text: str) -> dict[str, dict[str, str]]:
    """INI 形式の ``.wslconfig`` テキストをパースして ``{section: {key: value}}`` の dict を返します。

    空文字や None を渡した場合は空 dict を返します。
    重複セクションや不正な行に対しては ``strict=False`` で可能な範囲でパースし、
    パース失敗時も例外を投げず空 dict を返します。
    """
    if not text:
        return {}
    parser = configparser.RawConfigParser(strict=False)
    # .wslconfig のキーは camelCase (localhostForwarding 等) のため小文字化しない
    parser.optionxform = str  # type: ignore[assignment]
    try:
        parser.read_string(text)
    except Exception:
        return {}
    result: dict[str, dict[str, str]] = {}
    for section in parser.sections():
        result[section] = dict(parser.items(section))
    return result


def parse_wsl_version(output: str) -> dict[str, str]:
    """``wsl --version`` のデコード済みテキスト出力を解析してバージョン情報の dict を返します。

    各行を ``:`` (最初の出現のみ) で分割し、左辺のキーワードを正規化キーに対応付けます。
    対応する正規化キーは以下の通りです:

    - 「WSL」を含むが「WSLg」を含まない行 → ``"wsl"``
    - 「カーネル」または「Kernel」を含む行  → ``"kernel"``
    - 「WSLg」を含む行                     → ``"wslg"``
    - 「MSRDC」を含む行                    → ``"msrdc"``
    - 「Direct3D」を含む行                 → ``"direct3d"``
    - 「DXCore」を含む行                   → ``"dxcore"``
    - 「Windows」を含む行                  → ``"windows"``

    いずれのパターンにも一致しない行、または ``:`` を含まない行はスキップします。
    ``output`` が空文字または None の場合は空 dict を返します。
    """
    if not output:
        return {}
    result: dict[str, str] = {}
    for raw_line in output.splitlines():
        if ":" not in raw_line:
            continue
        left, _, right = raw_line.partition(":")
        left_strip = left.strip()
        value = right.strip()
        if "WSLg" in left_strip:
            result["wslg"] = value
        elif "WSL" in left_strip:
            result["wsl"] = value
        elif "カーネル" in left_strip or "Kernel" in left_strip:
            result["kernel"] = value
        elif "MSRDC" in left_strip:
            result["msrdc"] = value
        elif "Direct3D" in left_strip:
            result["direct3d"] = value
        elif "DXCore" in left_strip:
            result["dxcore"] = value
        elif "Windows" in left_strip:
            result["windows"] = value
    return result


_WSL_UPDATE_UP_TO_DATE_PATTERNS = (
    re.compile(r"already installed", re.IGNORECASE),
    re.compile(r"up[\s-]?to[\s-]?date", re.IGNORECASE),
    re.compile(r"既にインストールされています"),
)

# 英語: "Updating ... to version: 2.1.5." / "... successfully updated to version 2.1.5"
_WSL_UPDATE_VERSION_RE_EN = re.compile(
    r"to version:?\s*([0-9]+(?:\.[0-9]+)*)", re.IGNORECASE
)
# 日本語: "Windows Subsystem for Linux をバージョン 2.1.5 に更新しています。"
_WSL_UPDATE_VERSION_RE_JA = re.compile(
    r"バージョン\s*([0-9]+(?:\.[0-9]+)*)\s*に(?:更新|インストール)"
)


def parse_wsl_update_output(output: str) -> dict:
    """``wsl --update`` のデコード済みテキスト出力を解析して更新結果の dict を返します。

    wsl --update の出力は環境により日本語・英語のいずれにもなり得るため、
    両言語の代表的な表現に寛容なパーサーとしています。例:

    - 「最新バージョンの Windows Subsystem for Linux は既にインストールされています。」
    - "The most recent version of Windows Subsystem for Linux is already installed."
    - 「Windows Subsystem for Linux をバージョン 2.1.5 に更新しています。」
    - "Updating Windows Subsystem for Linux to version: 2.1.5."

    返り値の dict のキー:
    - ``"updated"``: bool - 新しいバージョンへの更新が行われたと判定できたか
    - ``"up_to_date"``: bool - 既に最新版であると判定できたか
    - ``"version"``: str | None - 検出できた新バージョン番号 (検出できない場合は None)
    - ``"message"``: str - 表示用メッセージ。判別できない場合は入力テキストを
      そのまま設定し、安全側 (更新なし扱い) に倒します。

    ``output`` が空文字または None の場合は全て False/None の dict を返します。
    """
    if not output:
        return {"updated": False, "up_to_date": False, "version": None, "message": ""}

    text = output.strip()

    up_to_date = any(pattern.search(text) for pattern in _WSL_UPDATE_UP_TO_DATE_PATTERNS)

    version: str | None = None
    m = _WSL_UPDATE_VERSION_RE_EN.search(text)
    if m:
        version = m.group(1)
    else:
        m = _WSL_UPDATE_VERSION_RE_JA.search(text)
        if m:
            version = m.group(1)

    updated = bool(version) and not up_to_date

    if up_to_date:
        message = "WSL は既に最新の状態です。"
    elif updated:
        message = f"WSL をバージョン {version} に更新しました。"
    else:
        # 判別できない場合は安全側に倒し、生の出力をそのままメッセージとする
        message = text

    return {
        "updated": updated,
        "up_to_date": up_to_date,
        "version": version,
        "message": message,
    }


def parse_ip_addresses(output: str) -> list[str]:
    """``hostname -I`` のデコード済みテキスト出力を解析して IP アドレスの一覧を返します。

    ``hostname -I`` はスペース区切りで IP アドレスを返します (末尾にスペースが付くことがあります)。
    空白で分割し、空でない要素のみをリストとして返します。
    IPv4 アドレスおよび IPv6 アドレスの両方をそのまま含みます。
    ``output`` が空文字または None の場合は空リストを返します。
    """
    if not output:
        return []
    return [part for part in output.split() if part]


def dump_wslconfig(sections: dict[str, dict[str, str]]) -> str:
    """``{section: {key: value}}`` の dict を ``.wslconfig`` テキストにシリアライズして返します。

    値が空文字のキーは出力しません。セクション内にキーが残らない場合はそのセクション見出しも出力しません。
    末尾は改行1つで終えます。
    """
    parser = configparser.RawConfigParser()
    # camelCase のキー名を保持する (localhostForwarding 等)
    parser.optionxform = str  # type: ignore[assignment]
    for section, items in sections.items():
        # 値が空文字でないキーだけを対象にする
        non_empty = {k: v for k, v in items.items() if v != ""}
        if not non_empty:
            continue
        parser.add_section(section)
        for key, value in non_empty.items():
            parser.set(section, key, value)

    buf = io.StringIO()
    parser.write(buf)
    text = buf.getvalue()
    # configparser は末尾に余分な改行を付けることがあるので正規化する
    text = text.rstrip("\n") + "\n"
    return text


def parse_os_release(text: str | None) -> dict[str, str]:
    """/etc/os-release のテキスト出力を解析してキーと値の dict を返します。

    フォーマットは ``KEY=value`` または ``KEY="value"`` の形式です。
    値のダブルクォートは除去します。空行およびコメント行 (# で始まる行) はスキップします。
    ``=`` を含まない行もスキップします。
    ``text`` が空文字または None の場合は空 dict を返します。
    """
    if not text:
        return {}
    result: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        # ダブルクォートを除去する
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        result[key.strip()] = value
    return result


def parse_disk_usage(text: str | None) -> list[dict]:
    """``df -B1`` (バイト単位) のテキスト出力を解析してディスク使用状況の一覧を返します。

    先頭1行はヘッダ行としてスキップします。各行のフィールドは:
    Filesystem, 1B-blocks, Used, Available, Use%, Mounted-on の順です。
    6フィールド未満の行、またはサイズフィールドが数値でない行はスキップします。
    返り値の各 dict のキーは filesystem, total(int), used(int), available(int),
    use_percent(str), mount_point です。
    ``text`` が空文字または None の場合は空リストを返します。
    """
    if not text:
        return []
    result: list[dict] = []
    lines = text.splitlines()
    # 先頭1行はヘッダ行なのでスキップ
    for raw_line in lines[1:]:
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 6:
            continue
        filesystem = parts[0]
        total_str = parts[1]
        used_str = parts[2]
        available_str = parts[3]
        use_percent = parts[4]
        mount_point = parts[5]
        try:
            total = int(total_str)
            used = int(used_str)
            available = int(available_str)
        except ValueError:
            continue
        result.append({
            "filesystem": filesystem,
            "total": total,
            "used": used,
            "available": available,
            "use_percent": use_percent,
            "mount_point": mount_point,
        })
    return result


def parse_uptime(text: str | None) -> str:
    """``uptime -p`` のテキスト出力を解析して稼働時間の文字列を返します。

    入力テキストをそのまま前後の空白を除去して返します。
    ``text`` が空文字または None の場合は ``"-"`` を返します。
    """
    if not text:
        return "-"
    stripped = text.strip()
    if not stripped:
        return "-"
    return stripped


def validate_distro_name(name: str) -> tuple[bool, str]:
    """WSL ディストリビューション名を検証して (有効かどうか, 理由) のタプルを返します。

    以下のルールを検証します:
    - 空文字または空白のみは無効
    - 使用禁止文字 (/ \\ : * ? " < > |) は無効
    - 64 文字を超える場合は無効

    有効な場合は (True, "") を返します。
    無効な場合は (False, 理由の日本語文字列) を返します。
    """
    if not name or not name.strip():
        return False, "ディストリビューション名を入力してください"
    invalid_chars = set(r'/\:*?"<>|')
    found = [c for c in name if c in invalid_chars]
    if found:
        return False, f"使用できない文字が含まれています: {''.join(sorted(set(found)))}"
    if len(name) > 64:
        return False, "ディストリビューション名は64文字以内にしてください"
    return True, ""


def default_clone_name(base_name: str, existing: list[str]) -> str:
    """複製先ディストリビューション名の初期値を生成して返します。

    まず ``"{base_name}-copy"`` を候補とし、existing と大文字小文字を
    区別せず (casefold) 比較して衝突する場合は ``-copy2``, ``-copy3``, ...
    と連番を増やして最初に衝突しない名前を返します。
    """
    existing_casefold = {name.casefold() for name in existing}
    candidate = f"{base_name}-copy"
    if candidate.casefold() not in existing_casefold:
        return candidate
    n = 2
    while True:
        candidate = f"{base_name}-copy{n}"
        if candidate.casefold() not in existing_casefold:
            return candidate
        n += 1


def validate_clone_name(name: str, existing: list[str]) -> tuple[bool, str]:
    """複製先ディストリビューション名を検証して (有効かどうか, 理由) のタプルを返します。

    まず :func:`validate_distro_name` による検証を行い、無効であればその
    結果をそのまま返します。次に existing と大文字小文字を区別せず
    (casefold) 比較して重複していないかを確認します。

    有効な場合は (True, "") を返します。
    無効な場合は (False, 理由の日本語文字列) を返します。
    """
    valid, reason = validate_distro_name(name)
    if not valid:
        return False, reason
    existing_casefold = {existing_name.casefold() for existing_name in existing}
    if name.casefold() in existing_casefold:
        return False, "同名のディストリビューションが既に存在します。"
    return True, ""


def format_bytes(size_bytes: int | float) -> str:
    """バイト数を人間が読みやすい形式の文字列に変換して返します。

    バイナリ単位 (KiB, MiB, GiB, TiB) を使用します。
    0 以下の場合は ``"0 B"`` を返します。
    1 KiB 未満の場合は ``"{n} B"`` の形式で返します。
    1 KiB 以上の場合は小数点1桁で表示します (例: ``"1.5 KiB"``)。
    """
    if size_bytes <= 0:
        return "0 B"
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    size = float(size_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} {units[-1]}"


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


def format_operation_log_entry(
    operation: str,
    target: str,
    result: str,
    timestamp: str | None = None,
) -> str:
    """操作ログの1行を生成して返します。

    フォーマット:
        [{timestamp}] {operation} | {target} | {result}

    timestamp が None の場合は現在時刻を ISO 8601 形式で設定します。
    operation の例: "起動", "停止", "インストール", "エクスポート"
    """
    ts = timestamp if timestamp is not None else datetime.now().isoformat()
    return f"[{ts}] {operation} | {target} | {result}"


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


# ---------------------------------------------------------------------------
# .wslconfig バリデーション・パース ユーティリティ
# ---------------------------------------------------------------------------

_MEMORY_RE = re.compile(r"^\d+(?:KB|MB|GB|TB)?$", re.IGNORECASE)


def validate_memory_string(value: str) -> tuple[bool, str]:
    """メモリサイズ文字列を検証して (有効かどうか, 理由) のタプルを返します。

    受け付けるフォーマット: 1 つ以上の数字に続けてオプションの単位 (KB / MB / GB / TB、
    大文字・小文字不問)。空文字列は「未設定」として有効とみなします。

    有効な場合は (True, "") を返します。
    無効な場合は (False, 理由の日本語文字列) を返します。
    """
    if value == "":
        return True, ""
    if not _MEMORY_RE.match(value):
        return False, "メモリサイズは数値と単位 (KB/MB/GB/TB) の組み合わせで入力してください (例: 4GB)"
    # 先頭の数値部分を取り出して 0 より大きいことを確認
    num_part = re.match(r"^\d+", value)
    if num_part and int(num_part.group()) == 0:
        return False, "メモリサイズには 0 より大きい値を指定してください"
    return True, ""


def validate_processors_string(value: str) -> tuple[bool, str]:
    """プロセッサ数文字列を検証して (有効かどうか, 理由) のタプルを返します。

    空文字列は「未設定」として有効とみなします。
    それ以外は 1 以上の正の整数でなければなりません。

    有効な場合は (True, "") を返します。
    無効な場合は (False, 理由の日本語文字列) を返します。
    """
    if value == "":
        return True, ""
    if not re.match(r"^\d+$", value):
        return False, "プロセッサ数は正の整数で入力してください"
    if int(value) == 0:
        return False, "プロセッサ数には 1 以上の値を指定してください"
    return True, ""


def validate_swap_string(value: str) -> tuple[bool, str]:
    """スワップサイズ文字列を検証して (有効かどうか, 理由) のタプルを返します。

    ルールは :func:`validate_memory_string` と同じです。
    空文字列は「未設定」として有効とみなします。

    有効な場合は (True, "") を返します。
    無効な場合は (False, 理由の日本語文字列) を返します。
    """
    valid, reason = validate_memory_string(value)
    if not valid:
        # メモリ向けのメッセージをスワップ向けに差し替える
        return False, reason.replace("メモリサイズ", "スワップサイズ")
    return True, ""


def parse_memory_to_bytes(value: str) -> int | None:
    """メモリサイズ文字列をバイト数の整数に変換して返します。

    対応単位と乗数:
    - KB → 1024^1
    - MB → 1024^2
    - GB → 1024^3
    - TB → 1024^4
    単位を省略した場合はそのままバイト数として扱います。

    パースできない場合は None を返します。
    """
    if not value:
        return None
    m = re.match(r"^(\d+)(KB|MB|GB|TB)?$", value, re.IGNORECASE)
    if not m:
        return None
    number = int(m.group(1))
    unit = (m.group(2) or "").upper()
    multipliers = {
        "": 1,
        "KB": 1024,
        "MB": 1024 ** 2,
        "GB": 1024 ** 3,
        "TB": 1024 ** 4,
    }
    return number * multipliers[unit]


# ---------------------------------------------------------------------------
# wsl.conf バリデーション ユーティリティ
# ---------------------------------------------------------------------------

_LINUX_USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]*$")
_HOSTNAME_LABEL_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def validate_wslconf_bool(value: str) -> tuple[bool, str]:
    """wsl.conf の真偽値文字列を検証して (有効かどうか, 理由) のタプルを返します。

    受け付ける値は ``"true"`` または ``"false"`` のみです。
    空文字列は「未設定」として有効とみなします。

    有効な場合は (True, "") を返します。
    無効な場合は (False, 理由の日本語文字列) を返します。
    """
    if value == "":
        return True, ""
    if value not in ("true", "false"):
        return False, "true または false を入力してください"
    return True, ""


def validate_linux_username(name: str) -> tuple[bool, str]:
    """Linux ユーザー名を検証して (有効かどうか, 理由) のタプルを返します。

    POSIX のユーザー名規則 (``[a-z_][a-z0-9_-]*``、32文字以内) に従います。
    空文字列は「未設定」として有効とみなします。

    有効な場合は (True, "") を返します。
    無効な場合は (False, 理由の日本語文字列) を返します。
    """
    if name == "":
        return True, ""
    if len(name) > 32:
        return False, "ユーザー名は32文字以内にしてください"
    if not _LINUX_USERNAME_RE.match(name):
        return False, (
            "ユーザー名は英小文字またはアンダースコアで始まり、"
            "英小文字・数字・アンダースコア・ハイフンのみ使用できます"
        )
    return True, ""


def validate_mount_root(path: str) -> tuple[bool, str]:
    """automount のマウント先ルートパスを検証して (有効かどうか, 理由) のタプルを返します。

    ``/`` から始まる絶対パスのみを許可します。
    空文字列は「未設定」として有効とみなします。

    有効な場合は (True, "") を返します。
    無効な場合は (False, 理由の日本語文字列) を返します。
    """
    if path == "":
        return True, ""
    if not path.startswith("/"):
        return False, "マウント先は / から始まる絶対パスで入力してください"
    return True, ""


def validate_hostname(name: str) -> tuple[bool, str]:
    """ホスト名を検証して (有効かどうか, 理由) のタプルを返します。

    RFC 952 / RFC 1123 に準拠した簡易チェックを行います。``.`` で区切られた
    各ラベルは英数字とハイフンのみで構成され、ハイフンで開始・終了しないこと、
    各ラベルは63文字以内、全体は253文字以内であることを検証します。
    空文字列は「未設定」として有効とみなします。

    有効な場合は (True, "") を返します。
    無効な場合は (False, 理由の日本語文字列) を返します。
    """
    if name == "":
        return True, ""
    if len(name) > 253:
        return False, "ホスト名は253文字以内にしてください"
    labels = name.split(".")
    for label in labels:
        if not _HOSTNAME_LABEL_RE.match(label):
            return False, "ホスト名は英数字とハイフンのみ使用でき、ハイフンで開始・終了できません"
    return True, ""


# ---------------------------------------------------------------------------
# 操作ログ永続化ユーティリティ
# ---------------------------------------------------------------------------


def get_default_log_dir() -> str:
    """操作ログを保存するデフォルトディレクトリのパスを返します。

    Windows (``sys.platform == "win32"``) では環境変数 ``APPDATA`` 配下の
    ``WSLManager/logs`` を、それ以外では ``~/.wslmgr/logs`` を返します。
    ディレクトリの作成などの I/O は一切行いません。
    """
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        return os.path.join(appdata, "WSLManager", "logs")
    return os.path.expanduser("~/.wslmgr/logs")


def serialize_log_entry(
    operation: str,
    target: str,
    result: str,
    timestamp: str | None = None,
) -> str:
    """操作ログ1件を JSON Lines 形式の1行 (改行なし) にシリアライズして返します。

    キーは "timestamp", "operation", "target", "result" です。
    timestamp が None の場合は現在時刻を ISO 8601 形式で設定します。
    日本語をエスケープしないように ``json.dumps(ensure_ascii=False)`` を使用します。
    """
    ts = timestamp if timestamp is not None else datetime.now().isoformat()
    entry = {
        "timestamp": ts,
        "operation": operation,
        "target": target,
        "result": result,
    }
    return json.dumps(entry, ensure_ascii=False)


def deserialize_log_entries(text: str) -> list[dict]:
    """JSON Lines 形式の操作ログテキストを解析して dict のリストを返します。

    1行につき1つの JSON オブジェクトを想定します。空行や JSON として
    パースできない行はスキップします。
    ``text`` が空文字または None の場合は空リストを返します。
    """
    if not text:
        return []
    entries: list[dict] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def format_log_entry_from_dict(entry: dict) -> str:
    """操作ログの dict を人間が読みやすい1行の文字列にして返します。

    フォーマット:
        [{timestamp}] {operation} | {target} | {result}

    キーが欠けている場合はそれぞれ "-" をデフォルト値として使用します。
    """
    timestamp = entry.get("timestamp", "-")
    operation = entry.get("operation", "-")
    target = entry.get("target", "-")
    result = entry.get("result", "-")
    return f"[{timestamp}] {operation} | {target} | {result}"


def rotate_log_files(
    log_dir: str,
    base_name: str = "operations.jsonl",
    max_size: int = 1_048_576,
    max_backups: int = 10,
) -> None:
    """ログファイルが最大サイズを超えた場合にローテーションを行います。

    ``log_dir/base_name`` が ``max_size`` バイトを超えていれば、
    ``operations.jsonl`` → ``operations.1.jsonl`` → ``operations.2.jsonl`` ...
    のように番号を1つずつ繰り上げてリネームします。
    ``max_backups`` を超える番号のバックアップファイルは削除します。
    対象ファイルが存在しない場合は何もしません。
    """
    base_path = os.path.join(log_dir, base_name)
    if not os.path.exists(base_path):
        return
    if os.path.getsize(base_path) <= max_size:
        return

    stem, ext = os.path.splitext(base_name)

    def backup_path(n: int) -> str:
        return os.path.join(log_dir, f"{stem}.{n}{ext}")

    # max_backups を超える古いバックアップを削除する
    oldest = backup_path(max_backups)
    if os.path.exists(oldest):
        os.remove(oldest)

    # 既存バックアップを番号の大きい方から繰り上げる (衝突を避けるため降順)
    for n in range(max_backups - 1, 0, -1):
        src = backup_path(n)
        if os.path.exists(src):
            os.rename(src, backup_path(n + 1))

    # 現在のログファイルを .1 にリネームする
    os.rename(base_path, backup_path(1))


def tail_entries(entries: list, n: int) -> list:
    """リストの末尾 n 件を返します。

    ``n <= 0`` の場合は空リストを返します。``n >= len(entries)`` の場合は
    全件のコピーを返します。副作用はなく、引数の entries 自体は変更しません。
    """
    if n <= 0:
        return []
    if n >= len(entries):
        return list(entries)
    return entries[-n:]


# ---------------------------------------------------------------------------
# アプリ設定永続化ユーティリティ
# ---------------------------------------------------------------------------


DEFAULT_SETTINGS: dict = {
    "theme": None,           # ttk テーマ名 (None はシステムデフォルト)
    "auto_refresh": False,   # 自動更新の ON/OFF
    "window_geometry": None, # ウィンドウジオメトリ "WxH+X+Y" (None は未保存)
    "sort_column": None,     # メイン一覧のソート列 ID (None は未ソート)
    "sort_desc": False,      # ソートが降順かどうか
    "snapshot_dir": None,    # スナップショット保存先 (None はデフォルト)
}


_GEOMETRY_RE = re.compile(r"^\d+x\d+([+-]-?\d+[+-]-?\d+)?$")


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


def is_valid_geometry(value) -> bool:
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
    width = int(width_str)
    height = int(height_digits.group())
    return width > 0 and height > 0


def normalize_settings(data) -> dict:
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

    return result


def load_settings(path: str) -> dict:
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


def save_settings(path: str, settings: dict) -> bool:
    """設定 dict を正規化した上で JSON ファイルとして保存します。

    保存先ディレクトリが存在しない場合は作成します。
    成功した場合は True を、``OSError`` が発生した場合は False を返します
    (例外は送出しません)。
    """
    normalized = normalize_settings(settings)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n")
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------------
# スナップショット管理ユーティリティ
# ---------------------------------------------------------------------------


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
) -> dict:
    """スナップショットのメタデータ dict を生成します。

    ``tar_file`` には tar ファイルのベース名 (フルパスではない) を指定します。
    ``created_at`` は ISO-8601 形式の文字列を想定します。
    """
    return {
        "distro_name": distro_name,
        "wsl_version": wsl_version,
        "comment": comment,
        "size_bytes": size_bytes,
        "created_at": created_at,
        "tar_file": tar_file,
    }


def normalize_snapshot_metadata(data) -> dict | None:
    """任意のオブジェクトからスナップショットメタデータ dict を正規化します。

    ``data`` が dict でない場合、``distro_name`` または ``tar_file`` が
    空でない文字列でない場合、および ``tar_file`` がベース名以外
    (パス区切り文字や ``..`` を含む) の場合は ``None`` を返します。それ以外の場合は
    6つのキーを持つ新しい dict を返します。値の型・形式が不正な場合は
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
    """スナップショットのメタデータ dict を JSON ファイルとして保存します。

    保存先ディレクトリが存在しない場合は作成します。
    成功した場合は True を、``OSError`` が発生した場合は False を返します
    (例外は送出しません)。
    """
    try:
        os.makedirs(os.path.dirname(json_path), exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------------
# ポートフォワーディング管理ユーティリティ
# ---------------------------------------------------------------------------


def validate_port_number(value: str) -> tuple[bool, str]:
    """ポート番号文字列を検証して (有効かどうか, 理由) のタプルを返します。

    以下のルールを検証します:
    - 空文字または None は無効
    - 整数に変換できない場合は無効
    - 1〜65535 の範囲外は無効

    有効な場合は (True, "") を返します。
    無効な場合は (False, 理由の日本語文字列) を返します。
    """
    if not value:
        return False, "ポート番号を入力してください"
    try:
        port = int(value)
    except (TypeError, ValueError):
        return False, "ポート番号は整数で入力してください"
    if port < 1 or port > 65535:
        return False, "ポート番号は 1〜65535 の範囲で指定してください"
    return True, ""


def parse_portproxy_output(output: str) -> list[dict]:
    """``netsh interface portproxy show all`` のテキスト出力を解析してルール一覧を返します。

    出力には "Listen on ipv4:" のようなヘッダ行、列名行 (Address / Port ...)、
    区切り線 (---- ...)、空行が含まれるため、それらはスキップします。
    実データ行は ``listen_address listen_port connect_address connect_port`` の
    4フィールドで構成されることを想定し、空白区切りで分割します。
    返り値の各 dict のキーは listen_address, listen_port(int),
    connect_address, connect_port(int) です。
    ``output`` が空文字または None の場合は空リストを返します。
    """
    if not output:
        return []
    rules: list[dict] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("Listen on") or line.startswith("Address"):
            continue
        # 区切り線 ("--------------- ----------  --------------- ----------") はスキップ
        if set(line.replace(" ", "")) <= {"-"}:
            continue
        parts = line.split()
        if len(parts) != 4:
            continue
        listen_address, listen_port_str, connect_address, connect_port_str = parts
        try:
            listen_port = int(listen_port_str)
            connect_port = int(connect_port_str)
        except ValueError:
            continue
        rules.append(
            {
                "listen_address": listen_address,
                "listen_port": listen_port,
                "connect_address": connect_address,
                "connect_port": connect_port,
            }
        )
    return rules


_SS_PROCESS_RE = re.compile(r'users:\(\("([^"]+)"')


def parse_ss_output(output: str) -> list[dict]:
    """``ss -tlnp`` のテキスト出力を解析してリスニングソケット一覧を返します。

    先頭1行はヘッダ行としてスキップします。"Local Address:Port" フィールドは
    IPv4 (``addr:port``) と IPv6 (``[addr]:port``) の両方の形式に対応します。
    プロセス名は ``users:(("name",...))`` 形式から正規表現で抽出し、
    一致しない場合は元の文字列をそのまま使用します。
    返り値の各 dict のキーは state, local_address, local_port(int), process です。
    ``output`` が空文字または None の場合は空リストを返します。
    """
    if not output:
        return []
    results: list[dict] = []
    lines = output.splitlines()
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("State") or line.startswith("Netid"):
            continue
        parts = line.split(None, 5)
        if len(parts) < 4:
            continue
        state = parts[0]
        local_field = parts[3]

        # IPv6: "[::]:22" 形式
        m = re.match(r"^\[(.+)\]:(\d+)$", local_field)
        if m:
            local_address = m.group(1)
            port_str = m.group(2)
        else:
            # IPv4: "0.0.0.0:22" 形式 (最後の ':' でポートを分離)
            if ":" not in local_field:
                continue
            local_address, _, port_str = local_field.rpartition(":")

        try:
            local_port = int(port_str)
        except ValueError:
            continue

        remainder = " ".join(parts[5:]) if len(parts) > 5 else ""
        proc_match = _SS_PROCESS_RE.search(remainder)
        if proc_match:
            process = proc_match.group(1)
        else:
            process = remainder.strip() if remainder.strip() else "-"

        results.append(
            {
                "state": state,
                "local_address": local_address,
                "local_port": local_port,
                "process": process,
            }
        )
    return results


def detect_network_mode(config: dict[str, dict[str, str]]) -> str:
    """.wslconfig の dict からネットワークモードを判定して返します。

    ``config["wsl2"]["networkingMode"]`` の値 (大小文字を区別しない) を確認します。
    値が "mirrored" であれば "mirrored" を返します。
    値が "nat" または空文字 (未設定) であれば "nat" を返します。
    それ以外の値の場合は、その値を小文字化したものをそのまま返します。
    """
    mode = config.get("wsl2", {}).get("networkingMode", "")
    normalized = mode.strip().lower()
    if normalized == "mirrored":
        return "mirrored"
    if normalized in ("", "nat"):
        return "nat"
    return normalized


def estimate_transfer_progress(
    current_bytes: int | float, total_bytes: int | float | None
) -> float | None:
    """転送済みバイト数から進捗率 (0.0〜100.0) を推定して返します。

    total_bytes が None または 0 以下の場合は進捗率を計算できないため
    None を返します。current_bytes が負の場合は 0 として扱います。
    tar とディスクイメージのサイズ差により current が total を超えることが
    あるため、結果は 100.0 で頭打ちにします。
    """
    if total_bytes is None or total_bytes <= 0:
        return None
    current = max(0.0, float(current_bytes))
    return min(100.0, current / float(total_bytes) * 100.0)


def estimate_remaining_seconds(
    current_bytes: int | float,
    total_bytes: int | float | None,
    elapsed_seconds: int | float,
) -> float | None:
    """平均転送速度から残り時間 (秒) を推定して返します。

    これまでの平均速度 (current_bytes / elapsed_seconds) が今後も続くと
    仮定した単純な線形推定です。以下の場合は推定不能として None を返します。

    - total_bytes が None または 0 以下 (分母が不明)
    - elapsed_seconds が 0 以下 (速度が計算できない)
    - current_bytes が 0 以下 (転送がまだ始まっていない)

    current が total 以上に達している場合は 0.0 を返します。
    """
    if total_bytes is None or total_bytes <= 0:
        return None
    if elapsed_seconds <= 0 or current_bytes <= 0:
        return None
    remaining = float(total_bytes) - float(current_bytes)
    if remaining <= 0:
        return 0.0
    rate = float(current_bytes) / float(elapsed_seconds)
    return remaining / rate


def format_duration(seconds: int | float) -> str:
    """秒数を ``M:SS`` または ``H:MM:SS`` 形式の文字列にして返します。

    負の値は 0 として扱います。秒は整数に切り捨てます。
    """
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_transfer_status(
    current_bytes: int | float,
    total_bytes: int | float | None,
    elapsed_seconds: int | float,
) -> str:
    """進捗ダイアログに表示するステータス文字列を組み立てて返します。

    total_bytes が分かる場合:
        ``"1.5 GiB / 4.0 GiB (37.5%) ・ 経過 1:23 ・ 残り約 2:18"``
    total_bytes が不明な場合:
        ``"1.5 GiB 書き込み済み ・ 経過 1:23"``

    残り時間が推定できない間 (転送開始直後など) は残り時間部分を省略します。
    """
    written = format_bytes(current_bytes)
    elapsed = format_duration(elapsed_seconds)
    percent = estimate_transfer_progress(current_bytes, total_bytes)
    if percent is None:
        return f"{written} 書き込み済み ・ 経過 {elapsed}"

    parts = [
        f"{written} / {format_bytes(total_bytes)} ({percent:.1f}%)",
        f"経過 {elapsed}",
    ]
    remaining = estimate_remaining_seconds(current_bytes, total_bytes, elapsed_seconds)
    if remaining is not None:
        parts.append(f"残り約 {format_duration(remaining)}")
    return " ・ ".join(parts)
