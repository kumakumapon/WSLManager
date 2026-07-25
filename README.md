# WSL Manager

[![CI](https://github.com/sj55576/WSLMgr/actions/workflows/ci.yml/badge.svg)](https://github.com/sj55576/WSLMgr/actions/workflows/ci.yml)

English | [日本語](README.ja.md)

## Disclaimer

**Important:** WSL Manager executes destructive WSL operations such as terminate, shutdown, unregister, import, export, version conversion, VHDX compaction, and snapshot deletion. Review the selected distribution and file paths before confirming an action. Back up important data first. This project is provided as-is, without any warranty or guarantee that it will prevent data loss, configuration damage, or service interruption.

## Overview

WSL Manager is a Windows desktop utility for managing WSL distributions from a Python/tkinter GUI. It also includes a command-line interface for common operations and keeps most parsing, validation, configuration, logging, and snapshot logic in a testable core module.

Key capabilities:

- List WSL distributions with state, WSL version, default marker, resource usage, IP address, and disk size.
- Start distributions, open terminals, terminate one distribution, or shut down all WSL instances.
- Set the default distribution and convert between WSL1 and WSL2.
- Install, unregister, import, export, clone, snapshot, restore, and delete distributions.
- Inspect and terminate processes inside a running distribution.
- Open a distribution in Explorer via `\\wsl.localhost\<name>`.
- Edit global `%USERPROFILE%\.wslconfig` and per-distribution `/etc/wsl.conf` settings.
- Optimize WSL2 VHDX disks using sparse VHD mode or `diskpart compact vdisk`.
- View WSL version/update information and run `wsl --update`.
- Manage `netsh interface portproxy` forwarding rules from the CLI.
- Persist app settings and operation logs.

## Requirements

- Windows 10 or Windows 11
- WSL installed and configured
- Python 3.10 or newer
- No runtime dependencies outside the Python standard library
- PyInstaller only when building `dist\WSLManager.exe`

## Usage

### Run The GUI

```powershell
python wslmgr.py
```

The main window shows installed distributions. Select a row, then use the toolbar, menu bar, double-click action, or right-click context menu to manage it.

Common GUI workflows:

- Refresh the distribution list or enable automatic refresh.
- Start a distribution by opening it in Windows Terminal when available, otherwise `cmd.exe`.
- Stop a selected distribution or shut down all WSL instances.
- Open process details for a running distribution and send `SIGTERM` or `SIGKILL`.
- Export, import, clone, snapshot, restore, or unregister a distribution.
- Edit `.wslconfig` or per-distribution `wsl.conf` settings.
- Compact or enable sparse mode for a WSL2 VHDX disk.

### Run The CLI

```powershell
python wslmgr_cli.py --help
python wslmgr_cli.py list
python wslmgr_cli.py list --format json
python wslmgr_cli.py start Ubuntu
python wslmgr_cli.py stop Ubuntu
python wslmgr_cli.py shutdown
python wslmgr_cli.py export Ubuntu C:\backup\Ubuntu.tar
python wslmgr_cli.py import UbuntuClone C:\WSL\UbuntuClone C:\backup\Ubuntu.tar
python wslmgr_cli.py config
python wslmgr_cli.py portproxy list
python wslmgr_cli.py snapshot create Ubuntu --comment "before upgrade"
python wslmgr_cli.py snapshot list
python wslmgr_cli.py snapshot restore Ubuntu_20260101-000000.tar --install-path C:\WSL\Restored
python wslmgr_cli.py clone Ubuntu UbuntuClone --install-path C:\WSL\UbuntuClone
```

CLI subcommands include `list`, `start`, `stop`, `shutdown`, `status`, `export`, `import`, `config`, `set-default`, `unregister`, `install`, `optimize`, `set-version`, `processes`, `log`, `portproxy`, `snapshot` (`create`/`list`/`restore`/`delete`), and `clone`.

### Build An Executable

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller --clean WSLManager.spec
```

The executable is written to:

```text
dist\WSLManager.exe
```

The checked-in `WSLManager.spec` and `pyinstaller_hooks/` directory are intentional. They make builds more reliable in conda/miniforge environments where unrelated package hooks or Tcl/Tk detection can break PyInstaller analysis.

## Implementation Notes

### Modules

| File | Responsibility |
|------|----------------|
| `wslmgr.py` | tkinter GUI, dialogs, background command execution, UI state, and user confirmations |
| `wslmgr_cli.py` | argparse-based command-line interface for scriptable WSL operations |
| `wsl_core.py` | Pure parsing, formatting, validation, settings, log, snapshot, and progress helpers |
| `tests/` | unittest coverage for the core module and CLI behavior |
| `WSLManager.spec` | PyInstaller build definition |
| `pyinstaller_hooks/` | Local PyInstaller hooks for tkinter/Tcl/Tk packaging |

### Architecture

- GUI code is Windows-focused and uses `tkinter`, `ttk`, `subprocess`, and `winreg`.
- Core logic avoids GUI, registry, and subprocess dependencies where practical so it can be tested on non-Windows CI.
- WSL command output is decoded by `wsl_core.decode_wsl_output()` to handle UTF-16 LE, UTF-8, CP932, and fallback encodings.
- Long-running operations run in background workers to keep the GUI responsive.
- Destructive actions use confirmation dialogs or explicit CLI commands rather than automatic execution.
- Settings are normalized before use, and `.wslconfig` / `wsl.conf` editors preserve unknown keys where possible.

### WSL Operations

The app wraps existing Windows commands instead of using a service or daemon:

- `wsl --list --verbose`
- `wsl --distribution <name>`
- `wsl --terminate <name>`
- `wsl --shutdown`
- `wsl --set-default <name>`
- `wsl --set-version <name> <1|2>`
- `wsl --install --distribution <name> --no-launch`
- `wsl --unregister <name>`
- `wsl --export <name> <path>`
- `wsl --import <name> <install-path> <image-path>`
- `wsl --manage <name> --set-sparse true`
- `diskpart` with a generated `compact vdisk` script
- `netsh interface portproxy` for CLI port forwarding management

### Snapshots And Logs

- Snapshots are stored as tar files plus JSON metadata.
- The default snapshot directory is under the user profile.
- Snapshot restore imports into a new distribution name instead of overwriting the source distribution.
- Operation logs are serialized as structured records and rotated by helper functions in `wsl_core.py`.

### Packaging

PyInstaller builds should use `WSLManager.spec`, not a raw `pyinstaller wslmgr.py` command. The spec collects conda/miniforge DLLs when present, and the local hooks make tkinter data files available as `_tcl_data` and `_tk_data` for PyInstaller's runtime hook.

### Testing

Run the test suite:

```powershell
python -m py_compile wslmgr.py wslmgr_cli.py wsl_core.py
python -m unittest discover -s tests -v
```

Linux/macOS can run most non-GUI checks with `python3`.

### CI

GitHub Actions runs compile checks and unit tests on Ubuntu and Windows across supported Python versions. Windows jobs also smoke-test importing the GUI module.

## License

MIT License. See [LICENSE](LICENSE).
