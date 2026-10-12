"""Windows 専用の定数とレジストリヘルパー。"""

from __future__ import annotations

import os
import sys

import wsl_core

try:
    import winreg
except ImportError:  # Windows 以外 (開発環境など)
    winreg = None  # type: ignore[assignment]


# ── Windows 専用フラグ ──────────────────────────────────────────────────────
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
CREATE_NEW_CONSOLE = 0x00000010 if sys.platform == "win32" else 0


def _iter_distro_registry() -> list[tuple[str, str]]:
    r"""レジストリから (DistributionName, BasePath) のペア一覧を取得します。

    HKCU\Software\Microsoft\Windows\CurrentVersion\Lxss 配下の各サブキーを走査し、
    BasePath は normalize_base_path で正規化済みの値を返します。
    """
    entries: list[tuple[str, str]] = []
    if winreg is None:
        return entries
    try:
        lxss = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Lxss",
        )
    except OSError:
        return entries
    with lxss:
        index = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(lxss, index)
            except OSError:
                break
            index += 1
            try:
                with winreg.OpenKey(lxss, subkey_name) as sub:
                    name, _ = winreg.QueryValueEx(sub, "DistributionName")
                    base_path, _ = winreg.QueryValueEx(sub, "BasePath")
            except OSError:
                continue
            entries.append((str(name), wsl_core.normalize_base_path(str(base_path))))
    return entries


def _get_distro_vhdx_sizes() -> dict[str, float]:
    """レジストリから各ディストリビューションの仮想ディスクサイズ (GB) を取得します。"""
    sizes: dict[str, float] = {}
    for name, base_path in _iter_distro_registry():
        vhdx_path = os.path.join(base_path, "ext4.vhdx")
        try:
            sizes[name] = os.path.getsize(vhdx_path) / (1024**3)
        except OSError:
            continue
    return sizes


def _get_distro_vhdx_path(name: str) -> str | None:
    """指定ディストリビューションの仮想ディスク (ext4.vhdx) の絶対パスを返します。"""
    for dname, base_path in _iter_distro_registry():
        if dname != name:
            continue
        vhdx_path = os.path.join(base_path, "ext4.vhdx")
        return vhdx_path if os.path.exists(vhdx_path) else None
    return None
