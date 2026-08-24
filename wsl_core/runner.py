"""
wsl_core.runner - WSL コマンド実行および出力デコードモジュール
"""

from __future__ import annotations

import subprocess
import sys

from .types import WslResult


def decode_wsl_output(raw: bytes) -> str:
    """WSL コマンドの出力を適切なエンコーディングでデコードします。

    wsl.exe の出力は UTF-16 LE (BOM 付き) で返ることが多いため、
    まず UTF-16 LE を試み、失敗した場合は UTF-8 にフォールバックします。
    BOM がない場合は、偶数バイト長かつ NUL バイトを含むときに限り
    UTF-16 LE とみなします (``wsl -d <name> -- <cmd>`` の UTF-8 出力を
    UTF-16 と誤判定して文字化けさせないためのヒューリスティックです)。
    """
    # BOM (FF FE) があれば取り除いてデコード
    if raw.startswith(b"\xff\xfe"):
        return raw[2:].decode("utf-16-le", errors="replace")
    # BOM なしで UTF-16 LE を試みる。ただし偶数長の ASCII/UTF-8 バイト列も
    # utf-16-le として「成功」してしまい CJK の文字化けになるため、
    # NUL バイトを含む場合のみ試す。wsl.exe の UTF-16 LE 出力は ASCII 文字
    # (改行・空白・英数字) を必ず含むため、その上位バイト 0x00 が現れる。
    # 一方、UTF-8 / cp932 のテキスト出力に NUL バイトは通常含まれない。
    if len(raw) % 2 == 0 and b"\x00" in raw:
        try:
            text = raw.decode("utf-16-le", errors="strict")
            # 意味のある文字列が得られたか簡易チェック
            if text.strip():
                return text
        except (UnicodeDecodeError, ValueError):
            pass
    # フォールバック: UTF-8 → cp932 の順に厳密デコードを試す。
    # errors="replace" は不正バイトがあっても例外を送出しないため、
    # ここで使うと必ず1周目の utf-8 で return してしまい cp932 に
    # 進めなくなる。errors="strict" で試し、UnicodeDecodeError の
    # ときだけ次のエンコーディングに進む。
    for enc in ("utf-8", "cp932"):
        try:
            return raw.decode(enc, errors="strict")
        except UnicodeDecodeError:
            continue
    # どちらも失敗した場合、latin-1 は任意のバイト列をデコードできるため
    # 必ず何らかの文字列を返す。
    return raw.decode("latin-1", errors="replace")


def run_wsl(
    args: list[str],
    timeout: float = 30.0,
    creationflags: int | None = None,
) -> WslResult:
    """WSL コマンドを実行し、出力をデコードして WslResult を返します。

    wsl.exe の不在、タイムアウト、OSError などを捕捉し、統一された
    エラーメッセージと error 種別を設定した WslResult を返します。
    """
    if creationflags is None:
        creationflags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
    cmd = ["wsl", *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            creationflags=creationflags,
        )
        stdout = decode_wsl_output(proc.stdout)
        stderr = decode_wsl_output(proc.stderr)
        return WslResult(
            returncode=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            error=None,
        )
    except FileNotFoundError:
        return WslResult(
            returncode=-1,
            stdout="",
            stderr="wsl.exe が見つかりません。WSL2 がインストールされているか確認してください。",
            error="not_found",
        )
    except subprocess.TimeoutExpired:
        return WslResult(
            returncode=-1,
            stdout="",
            stderr="コマンドがタイムアウトしました。",
            error="timeout",
        )
    except OSError as e:
        return WslResult(
            returncode=-1,
            stdout="",
            stderr=f"コマンド実行エラー: {e}",
            error="os_error",
        )
