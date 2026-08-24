"""
wsl_core.validation - WSL 設定値および入力値のバリデーションモジュール
"""

from __future__ import annotations

import re

# WSL ディストロ名はレジストリキー名・\\wsl.localhost\<name> パス・
# エクスポートファイル名として使われるため、Windows の予約デバイス名は
# 大文字小文字を区別せず使用禁止とする。
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

_MEMORY_RE = re.compile(r"^\d+(?:KB|MB|GB|TB)?$", re.IGNORECASE)
_LINUX_USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]*$")
_HOSTNAME_LABEL_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def validate_distro_name(name: str) -> tuple[bool, str]:
    """WSL ディストリビューション名を検証して (有効かどうか, 理由) のタプルを返します。

    ディストロ名はレジストリキー名・``\\\\wsl.localhost\\<name>`` パス・
    エクスポートファイル名として使われるため、Windows のファイル名規則に
    反する名前を無効とします。また、GUI のターミナル起動機能
    (:meth:`wslmgr.WSLManager._open_terminal`) がこの名前を含むコマンドラインで
    ``cmd.exe``/``wt.exe`` を起動するため、それらのコマンドラインインタプリタが
    特別扱いする文字も無効とします。以下のルールを検証します:
    - 空文字または空白のみは無効
    - 使用禁止文字 (/ \\ : * ? " < > | と、cmd.exe/wt.exe の
      コマンドライン区切り文字である & ; % ^ ( )) は無効
    - 64 文字を超える場合は無効
    - Windows の予約デバイス名 (CON, PRN, AUX, NUL, COM1〜9, LPT1〜9) および
      それらに拡張子を付けた名前 (例: "nul.txt") は無効 (大文字小文字を区別しない)
    - 末尾がドットまたは空白文字の場合は無効
    - 先頭が空白文字の場合は無効
    - 制御文字 (0x20 未満の文字) を含む場合は無効

    有効な場合は (True, "") を返します。
    無効な場合は (False, 理由の日本語文字列) を返します。
    """
    if not name or not name.strip():
        return False, "ディストリビューション名を入力してください"
    invalid_chars = set(r'/\:*?"<>|&;%^()')
    found = [c for c in name if c in invalid_chars]
    if found:
        return False, f"使用できない文字が含まれています: {''.join(sorted(set(found)))}"
    if len(name) > 64:
        return False, "ディストリビューション名は64文字以内にしてください"
    stem = name.split(".", 1)[0]
    if name.upper() in _WINDOWS_RESERVED_NAMES or stem.upper() in _WINDOWS_RESERVED_NAMES:
        return False, "Windows の予約デバイス名は使用できません"
    if name.endswith(".") or name[-1].isspace():
        return False, "名前の末尾にドットや空白は使用できません"
    if name[0].isspace():
        return False, "名前の先頭に空白は使用できません"
    if any(ord(c) < 0x20 for c in name):
        return False, "制御文字は使用できません"
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
        return False, (
            "メモリサイズは数値と単位 (KB/MB/GB/TB) の組み合わせで"
            "入力してください (例: 4GB)"
        )
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
