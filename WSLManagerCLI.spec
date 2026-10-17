# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for the command-line build (dist\wslmgr.exe).
#
# The GUI build lives in WSLManager.spec. This one is deliberately independent of it:
# it does not use pyinstaller_hooks/ (those hooks only collect Tcl/Tk for the GUI) and it
# excludes tkinter, because wslmgr_cli.py and wsl_core never import it. The result is a
# console executable, so output, redirection and exit codes behave like a normal CLI tool.

from pathlib import Path
import sys

conda_bin = Path(sys.base_prefix) / 'Library' / 'bin'
conda_binaries = [
    (str(conda_bin / dll), '.')
    for dll in ('liblzma.dll', 'libbz2.dll', 'ffi-8.dll')
    if (conda_bin / dll).exists()
]

a = Analysis(
    ['wslmgr_cli.py'],
    pathex=[],
    binaries=conda_binaries,
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', '_tkinter', 'turtle'],
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
    name='wslmgr',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX is off on purpose: it makes antivirus false positives more likely.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
