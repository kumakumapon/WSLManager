from pathlib import Path
import sys


CONDA_ROOT = Path(sys.base_prefix)
TCL_TK_LIB = CONDA_ROOT / "Library" / "lib"
TCL_TK_BIN = CONDA_ROOT / "Library" / "bin"

binaries = [
    (str(dll_path), ".")
    for dll_path in (TCL_TK_BIN / "tcl86t.dll", TCL_TK_BIN / "tk86t.dll")
    if dll_path.exists()
]

datas = [
    (str(data_path), target)
    for data_path, target in (
        (TCL_TK_LIB / "tcl8.6", "_tcl_data"),
        (TCL_TK_LIB / "tk8.6", "_tk_data"),
    )
    if data_path.exists()
]
