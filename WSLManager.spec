# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

conda_bin = Path(sys.base_prefix) / 'Library' / 'bin'
conda_binaries = [
    (str(conda_bin / dll), '.')
    for dll in ('liblzma.dll', 'libbz2.dll', 'ffi-8.dll')
    if (conda_bin / dll).exists()
]

a = Analysis(
    ['wslmgr.py'],
    pathex=[],
    binaries=conda_binaries,
    datas=[],
    hiddenimports=['tkinter', 'tkinter.filedialog', 'tkinter.messagebox', 'tkinter.simpledialog', 'tkinter.ttk'],
    hookspath=['pyinstaller_hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='WSLManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
