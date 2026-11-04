# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for the GUI build (dist\WSLManager.exe): one windowed executable that
# needs no Python. The command-line build is WSLManagerCLI.spec.
#
# The local hooks in pyinstaller_hooks/ collect Tcl/Tk reliably (also from conda/miniforge).
# The icon and the Windows version information (Explorer > Properties > Details) come from
# assets/ and tools/pyinstaller_support.py; the version is read from wsl_core/__init__.py.

import importlib.util
import os
import sys
from pathlib import Path

_support_spec = importlib.util.spec_from_file_location(
    'wslmgr_pyinstaller_support', os.path.join(SPECPATH, 'tools', 'pyinstaller_support.py')
)
support = importlib.util.module_from_spec(_support_spec)
_support_spec.loader.exec_module(support)

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
    # The window icon is loaded at runtime (wslmgr_gui/resources.py looks in sys._MEIPASS).
    datas=[('assets/wslmanager.ico', 'assets'), ('assets/wslmanager.png', 'assets')],
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
    # UPX is off on purpose: it makes antivirus false positives more likely.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/wslmanager.ico',
    version=support.build_version_info(
        SPECPATH, description='WSL Manager', internal_name='WSLManager'
    ),
)
