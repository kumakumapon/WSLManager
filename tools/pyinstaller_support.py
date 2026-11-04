"""PyInstaller の spec ファイル (WSLManager.spec / WSLManagerCLI.spec) が共有する補助関数。

- バージョンは ``wsl_core/__init__.py`` の ``__version__`` (= pyproject.toml) から読む。
  ``wsl_core`` を import しないので、ビルド環境に依存しない。
- exe に埋め込む Windows のバージョン情報 (エクスプローラーの「プロパティ → 詳細」に
  表示される製品名・バージョン・著作権) をここで組み立てる。

spec からは ``importlib`` でファイルを直接読み込む (``sys.path`` は変えない)。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

PRODUCT_NAME = "WSL Manager"
COMPANY_NAME = "kumakumapon"
COPYRIGHT = "Copyright (c) kumakumapon. MIT License."

_VERSION_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)


def read_version(root: str | Path) -> str:
    """リポジトリの ``wsl_core/__init__.py`` から ``__version__`` を読み取ります。"""
    text = (Path(root) / "wsl_core" / "__init__.py").read_text(encoding="utf-8")
    match = _VERSION_RE.search(text)
    if not match:
        raise ValueError("__version__ was not found in wsl_core/__init__.py")
    return match.group(1)


def version_tuple(version: str) -> tuple[int, int, int, int]:
    """``"1.2.3"`` → ``(1, 2, 3, 0)``。Windows のバージョン情報は 4 つの数値を要求する。"""
    parts = version.split(".")
    if not 1 <= len(parts) <= 4 or not all(p.isdigit() for p in parts):
        raise ValueError(f"the version must be numeric X.Y.Z, got {version!r}")
    numbers = [int(p) for p in parts] + [0] * (4 - len(parts))
    return numbers[0], numbers[1], numbers[2], numbers[3]


def version_strings(version: str, *, description: str, internal_name: str) -> dict[str, str]:
    """バージョン情報の文字列表 (``StringFileInfo``) の内容。"""
    exe_name = f"{internal_name}.exe"
    return {
        "CompanyName": COMPANY_NAME,
        "FileDescription": description,
        "FileVersion": version,
        "InternalName": internal_name,
        "LegalCopyright": COPYRIGHT,
        "OriginalFilename": exe_name,
        "ProductName": PRODUCT_NAME,
        "ProductVersion": version,
    }


def build_version_info(
    root: str | Path, *, description: str, internal_name: str, platform: str = sys.platform
) -> Any:
    """PyInstaller の ``EXE(version=...)`` に渡す ``VSVersionInfo`` を作ります。

    バージョン情報は Windows の exe にだけ埋め込まれる (PyInstaller はほかの OS では無視する)。
    Windows 以外ではバージョンの形式だけ確かめて ``None`` を返す
    (``PyInstaller.utils.win32`` が Windows 専用の ``pefile`` を必要とするため)。
    """
    version = read_version(root)
    numbers = version_tuple(version)
    if platform != "win32":
        return None

    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    strings = version_strings(version, description=description, internal_name=internal_name)
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[
            # 040904B0 = 英語 (米国) / Unicode
            StringFileInfo(
                [StringTable("040904B0", [StringStruct(k, v) for k, v in strings.items()])]
            ),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    )
