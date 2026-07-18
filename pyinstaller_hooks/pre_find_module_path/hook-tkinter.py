def pre_find_module_path(hook_api):
    # The conda-based build environment can import tkinter but PyInstaller's
    # Tcl/Tk probe fails, which otherwise makes the built-in hook hide tkinter.
    return
