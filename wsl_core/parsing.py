"""
wsl_core.parsing - WSL 出力および設定ファイルのパース・シリアライズモジュール
"""

from __future__ import annotations

import configparser
import io
import re
from typing import Any


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
    """``ps -eo pid,user,pcpu,rss,comm`` のデコード済みテキスト出力を解析して
    プロセス一覧を返します。

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


class WslConfigParseError(ValueError):
    """.wslconfig / wsl.conf のパースに失敗したことを示す例外。"""


def parse_wslconfig(text: str) -> dict[str, dict[str, str]]:
    """INI 形式の ``.wslconfig`` テキストをパースして
    ``{section: {key: value}}`` の dict を返します。

    空文字や None を渡した場合は空 dict を返します。
    重複セクションや不正な行に対しては ``strict=False`` で可能な範囲でパースしますが、
    パース失敗時は :class:`WslConfigParseError` を送出します。
    """
    if not text:
        return {}
    parser = configparser.RawConfigParser(strict=False)
    # .wslconfig のキーは camelCase (localhostForwarding 等) のため小文字化しない
    parser.optionxform = str  # type: ignore[assignment]
    try:
        parser.read_string(text)
    except (configparser.Error, ValueError) as e:
        raise WslConfigParseError(str(e)) from e
    result: dict[str, dict[str, str]] = {}
    for section in parser.sections():
        result[section] = dict(parser.items(section))
    return result


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


def parse_wsl_version(output: str) -> dict[str, str | list[str]]:
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

    いずれのパターンにも一致しない行 (既知パターン非一致、または ``:`` を含まない非空行) は
    ``result["_unparsed_lines"]`` (list[str]) に集約されます。未解析行が1件もない場合は
    ``_unparsed_lines`` キー自体が結果 dict に含まれません。
    ``output`` が空文字または None の場合は空 dict を返します。
    """
    if not output:
        return {}
    result: dict[str, str | list[str]] = {}
    unparsed_lines: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if ":" not in line:
            unparsed_lines.append(line)
            continue
        left, _, right = line.partition(":")
        left_strip = left.strip()
        value = right.strip()
        matched = False
        if "WSLg" in left_strip:
            result["wslg"] = value
            matched = True
        elif "WSL" in left_strip:
            result["wsl"] = value
            matched = True
        elif "カーネル" in left_strip or "Kernel" in left_strip:
            result["kernel"] = value
            matched = True
        elif "MSRDC" in left_strip:
            result["msrdc"] = value
            matched = True
        elif "Direct3D" in left_strip:
            result["direct3d"] = value
            matched = True
        elif "DXCore" in left_strip:
            result["dxcore"] = value
            matched = True
        elif "Windows" in left_strip:
            result["windows"] = value
            matched = True

        if not matched:
            unparsed_lines.append(line)

    if unparsed_lines:
        result["_unparsed_lines"] = unparsed_lines
    return result


_WSL_UPDATE_UP_TO_DATE_PATTERNS = (
    re.compile(r"already installed", re.IGNORECASE),
    re.compile(r"up[\s-]?to[\s-]?date", re.IGNORECASE),
    re.compile(r"既にインストールされています"),
    re.compile(r"最新.*インストールされています"),
)

# 英語: "Updating ... to version: 2.1.5." / "... successfully updated to version 2.1.5"
_WSL_UPDATE_VERSION_RE_EN = re.compile(
    r"(?:to version:?|installed version:?)\s*([0-9]+(?:\.[0-9]+)*)", re.IGNORECASE
)
# 日本語: "Windows Subsystem for Linux をバージョン 2.1.5 に更新しています。"
_WSL_UPDATE_VERSION_RE_JA = re.compile(
    r"バージョン\s*([0-9]+(?:\.[0-9]+)*)\s*(?:に(?:更新|インストール)|が(?:更新|インストール))"
)


def parse_wsl_update_output(output: str) -> dict[str, Any]:
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


def build_wsl_mount_args(
    disk: str,
    bare: bool = False,
    fs_type: str | None = None,
    partition: int | None = None,
    vhd: bool = False,
    name: str | None = None,
) -> list[str]:
    """``wsl --mount`` コマンドの引数リストを生成します。"""
    args = ["--mount", disk]
    if vhd:
        args.append("--vhd")
    if bare:
        args.append("--bare")
    if name:
        args.extend(["--name", name])
    if fs_type:
        args.extend(["--type", fs_type])
    if partition is not None and partition > 0:
        args.extend(["--partition", str(partition)])
    return args


def build_wsl_unmount_args(disk: str | None = None) -> list[str]:
    """``wsl --unmount`` コマンドの引数リストを生成します。"""
    if disk:
        return ["--unmount", disk]
    return ["--unmount"]


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
