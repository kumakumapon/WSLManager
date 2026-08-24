"""
wsl_core.transfer - データ転送進捗計算およびバイト数フォーマットモジュール
"""

from __future__ import annotations


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
        ``"1.5 KiB / 4.0 KiB (37.5%) ・ 経過 1:23 ・ 残り約 2:18"``
    total_bytes が不明な場合:
        ``"1.5 KiB 書き込み済み ・ 経過 1:23"``

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
