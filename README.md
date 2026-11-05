# WSL Manager

[![CI](https://github.com/kumakumapon/WSLManager/actions/workflows/ci.yml/badge.svg)](https://github.com/kumakumapon/WSLManager/actions/workflows/ci.yml)

English | [日本語](README.ja.md)

## Disclaimer

**Important:** WSL Manager executes destructive WSL operations such as terminate, shutdown, unregister, import, export, version conversion, VHDX compaction, and snapshot deletion. Review the selected distribution and file paths before confirming an action. Back up important data first. This project is provided as-is, without any warranty or guarantee that it will prevent data loss, configuration damage, or service interruption.

## Overview

WSL Manager is a Windows desktop app for managing WSL distributions: see them all in one list, start and stop them, open a terminal or Explorer, back them up and restore them, and edit their settings, without typing `wsl.exe` commands. It ships as ready-to-run executables (no Python needed) and also includes a command-line tool (`wslmgr.exe`) for scripts and Task Scheduler.

Key capabilities:

- List WSL distributions with state, WSL version, default marker, resource usage, IP address, disk size and install location.
- View 30-minute CPU and memory history graphs, with timestamps and exact values on hover.
- Start distributions in the background or in a terminal (Windows Terminal when available, otherwise `cmd.exe`), stop one distribution, or shut down WSL.
- Set the default distribution and convert between WSL1 and WSL2.
- Install, unregister, import (tar or VHDX), export (tar or VHDX), clone, snapshot, restore, and delete distributions, with progress and cancel for long operations.
- Inspect and terminate processes inside a running distribution.
- Open a distribution in Explorer via `\\wsl.localhost\<name>`.
- Edit global `%USERPROFILE%\.wslconfig` and per-distribution `/etc/wsl.conf` settings.
- Optimize WSL2 VHDX disks using sparse VHD mode or `diskpart compact vdisk`.
- View WSL version/update information and run `wsl --update`.
- Diagnose WSL 3.0.1 / WSL Containers availability and inspect containers in a read-only GUI or CLI view.
- Manage `netsh interface portproxy` forwarding rules from the CLI.
- Japanese and English interface (switch at any time from **View → Language**).

## Download

Get the files from the [latest release](https://github.com/kumakumapon/WSLManager/releases/latest). Pick one:

| File | Choose it when |
|------|----------------|
| `WSLManager-Setup-X.Y.Z.exe` | **Recommended.** Installs the app (GUI and `wslmgr.exe`) with a Start menu shortcut and an uninstaller. No administrator rights needed. Optionally adds the command-line tool to `PATH`. |
| `WSLManager-X.Y.Z-portable.zip` | You do not want to install anything. Unzip it anywhere and run `WSLManager.exe`. Contains `wslmgr.exe`, README and LICENSE too. |
| `WSLManager.exe` | You only want the GUI as one file. |
| `wslmgr.exe` | You only want the command-line tool as one file. |
| `SHA256SUMS.txt` | Checksums of the files above. |

None of the executables need Python. They are not code-signed, so Windows SmartScreen may show a warning the first time ("More info" → "Run anyway"). Settings and logs are stored in `%APPDATA%\WSLManager` and snapshots in `%USERPROFILE%\WSLSnapshots`, whichever file you use.

## Requirements

- Windows 10 or Windows 11 with WSL installed (`wsl --install` in an administrator PowerShell)
- To run from source or build the executables: Python 3.10 or newer (standard library only)

## Usage

### The GUI

Start **WSL Manager** from the Start menu (installer), or run `WSLManager.exe`.

```text
+---------------------------------------------------------------------------+
| File  Distribution  WSL  View  Help                                       |
| [> Start] [# Stop] [Terminal] [Explorer] | [+ Add v] [Snapshots]  Search: [___] [Refresh] |
+--------------------------------------------------+------------------------+
| Default  Distribution   State      WSL  CPU ...  | Ubuntu-24.04           |
|    *     Ubuntu-24.04   * Running  WSL2  3.2     | (Running) (WSL 2) (*)  |
|          Debian         o Stopped  WSL2  -       | CPU / Memory / Disk    |
|                                                  | IP [Copy]  Location    |
|                                                  | [Open terminal]        |
|                                                  | [Start] [Stop] ...     |
|                                                  | Backup / Settings /    |
|                                                  | Delete                 |
+--------------------------------------------------+------------------------+
| Ready                         2 distribution(s), 1 running   Updated 12:34 |
+---------------------------------------------------------------------------+
```

- **List (left):** every installed distribution. Click a column heading to sort, type in **Search** (Ctrl+F) to filter. Double-click a row or press Enter to open a terminal; press Delete to stop it; right-click (or Shift+F10) for every action.
- **Detail panel (right):** the selected distribution's state, resources, IP address (with a Copy button) and install location, plus buttons for all of its actions, grouped into *Backup*, *Settings* and *Delete*. Hide it from **View → Detail panel**.
- **Buttons follow the state:** actions that cannot be used are greyed out (for example *Start* for a running distribution, *Processes* for a stopped one, *Set as default* for the default one).
- **Toolbar:** *Start* boots the distribution in the background without opening a window (like `wslmgr start`; if nothing keeps running inside it, WSL stops it again on its own after a short idle time, so open a terminal or run a service to keep it up); *Terminal* opens a shell; **+ Add** installs an official distribution or imports a backup.
- **Forms instead of question chains:** export, import and clone each open one form with sensible defaults (file name with today's date, install folder `%USERPROFILE%\WSL\<name>`), choose tar or VHDX with radio buttons, and show input problems right in the form. Importing a `.vhdx` passes `--vhd` automatically.
- **Feedback:** the status bar shows a busy indicator while WSL works, the number of distributions and the last refresh time. Failures are also shown in an error dialog together with the message from `wsl.exe`, so they are not missed.
- **Empty list:** when nothing is installed the list offers *Install* and *Import*; when WSL is missing it explains how to install it and offers *Try again*.
- **View menu:** detail panel, resource history chart, auto refresh and its interval (5/10/30/60 s), theme, language (applied immediately), operation log.
- Destructive actions (stop, shut down, unregister, import, export overwrite, version conversion, VHDX compaction, snapshot deletion) still ask for confirmation; unregistering asks you to type the distribution name.

Keyboard shortcuts (also in **Help → Keyboard shortcuts**, F1):

| Key | Action |
|-----|--------|
| Enter / double-click | Open a terminal |
| Ctrl+Shift+S | Start in the background |
| Delete | Stop |
| F5 / Ctrl+R | Refresh |
| Ctrl+F | Search |
| Ctrl+N / Ctrl+I / Ctrl+E | Install / Import / Export |
| Ctrl+S | Create a snapshot |
| Ctrl+D / Ctrl+P | Details / Processes |
| Ctrl+, | Global WSL settings (`.wslconfig`) |
| Ctrl+L | Operation log |
| Ctrl+Shift+Q | Shut down WSL |

### Run From Source

```powershell
python wslmgr.py
```

On Windows, you can also double-click `start_wslmanager.bat`. It launches
`dist\WSLManager.exe` when available, otherwise it uses the local `.venv` or
the Python Launcher.

### Run The CLI

The installer and the portable ZIP include `wslmgr.exe`, a console executable that needs no Python (choose **Add the command-line tool to PATH** in the installer to run `wslmgr` from any folder). **Help → Command-line tool** in the GUI shows where it is.

```powershell
wslmgr list --format json
wslmgr snapshot create Ubuntu --comment "before upgrade"
```

When running from source, `wslmgr.bat` in the repository root is a CLI launcher: it finds Python
(`.venv`, then the Python Launcher, then `python`), runs `wslmgr_cli.py` with every
argument you pass, and returns its exit code unchanged (0 success, 1 error, 2 bad
arguments, 3 cancelled, 4 WSL failure, 5 partial failure), so it is safe to use from
scripts. Add the repository folder to `PATH` to run it from anywhere as `wslmgr`.
`dist\WSLManager.exe` is a windowed GUI build and cannot be used as a command-line tool; build `dist\wslmgr.exe` instead (see "Command-line executable" below).
Wrap arguments that contain `&`, `|` or `^` in double quotes. If `py -3` fails because no Python 3 is
installed, create a `.venv` in the repository folder.

```powershell
.\wslmgr.bat list --format json
```

Without the launcher, run the script directly:

```powershell
python wslmgr_cli.py --help
python wslmgr_cli.py --language en --help
python wslmgr_cli.py --version
python wslmgr_cli.py list --with-ip --with-disk
python wslmgr_cli.py list --format json
python wslmgr_cli.py doctor --format json
python wslmgr_cli.py container system-info
python wslmgr_cli.py container list --session "<session-name>" --all --format json
python wslmgr_cli.py container inspect --session "<session-name>" <name-or-id>
python wslmgr_cli.py start Ubuntu
python wslmgr_cli.py stop Ubuntu
python wslmgr_cli.py shutdown
python wslmgr_cli.py export Ubuntu C:\backup\Ubuntu.tar
python wslmgr_cli.py import UbuntuClone C:\WSL\UbuntuClone C:\backup\Ubuntu.tar
python wslmgr_cli.py config
python wslmgr_cli.py config --distro Ubuntu
python wslmgr_cli.py portproxy list
python wslmgr_cli.py snapshot create Ubuntu --comment "before upgrade"
python wslmgr_cli.py snapshot list
python wslmgr_cli.py snapshot restore Ubuntu_20260101-000000.tar --install-path C:\WSL\Restored
python wslmgr_cli.py snapshot set-dir D:\WSLSnapshots
python wslmgr_cli.py snapshot prune --keep 7 --name Ubuntu       # dry-run
python wslmgr_cli.py snapshot prune --keep 7 --name Ubuntu --yes # delete old generations
python wslmgr_cli.py snapshot schedule create Ubuntu --time 03:00 --keep 7
python wslmgr_cli.py clone Ubuntu UbuntuClone --install-path C:\WSL\UbuntuClone
python wslmgr_cli.py mount C:\disks\data.vhdx --vhd
python wslmgr_cli.py unmount C:\disks\data.vhdx
python wslmgr_cli.py log clear --yes
```

CLI subcommands include `list`, `doctor`, `container` (`system-info`/`list`/`inspect`), `start`, `stop`, `shutdown`, `status`, `export`, `import`, `config`, `set-default`, `unregister`, `install`, `optimize`, `set-version`, `processes`, `log` (`clear`), `portproxy` (`list`/`add`/`delete`), `snapshot` (`create`/`list`/`restore`/`delete`/`prune`/`set-dir`/`schedule`), `clone`, `mount`, and `unmount`.

### WSL Containers (WSLc)

This integration targets the official **WSL 3.0.1** CLI contract and accepts stable
3.0.1+ package versions. WSL package versions are separate from distribution
types (WSL1/WSL2); there is no distribution conversion to type 3.

Run `doctor --format json` to check package eligibility and the WSLc service.
An eligible version alone does not prove availability. Missing executables,
policy/service errors, timeouts and invalid responses are reported; failed
diagnostics exit with code 4. Updates are never started automatically.

First run `container system-info --format json`, then pass a session **Name**
from `Server.Sessions` to `list`/`inspect` using the required `--session` option.
Session IDs are not names. The GUI provides an existing-session selector and
selects automatically only when exactly one exists. No sessions means no list
request; multiple sessions require a selection. This prevents WSLc's implicit
default-session creation. If a selected session disappears, the error is shown
without falling back to a new/default session.

Lists show running containers by default; `--all` (GUI: Include stopped
containers) includes stopped ones. WSLc's NDJSON is normalized to an array of
`id`, `name`, `image`, `status`, `health`, `created` in CLI JSON output. Full IDs
are used for inspect. System-info preserves the official **object** (changed
from the previous one-element array); inspect preserves its nested array.

These commands may contact/start the WSLc service but do not create sessions,
create/stop/remove containers, prune, or change networks. Traditional WSL2
distribution features remain usable without WSLc. See the
[contract references and Windows validation checklist](docs/wsl-3.0.1-compatibility.md).

The CLI uses the saved GUI language preference (or the system language) for its
localized top-level/list help and standard list output. Override it per invocation with
`--language auto`, `--language ja`, or `--language en` before the subcommand.

### Exit Codes

`wslmgr_cli.py` uses the following exit codes:

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | General error (input validation failure, e.g. an invalid distro name, port number, missing file, or `.wslconfig` parse error) |
| `2` | Command-line argument error (standard `argparse` behavior, unchanged) |
| `3` | Confirmation denied (the user declined a destructive-operation prompt, or `--yes` was required but not supplied in a non-interactive environment) |
| `4` | Underlying command failure (`wsl.exe`, `diskpart`, or `netsh` returned a non-zero exit code, timed out, or could not be found) |
| `5` | Partial failure (the command completed but part of the result failed, e.g. `status` could not read every distro's resource usage, or `snapshot create` exported the tar but failed to write its JSON metadata) |

**Breaking change:** prior to this scheme, every failure exited with code `1`. Scripts that only check for "exit code != 0 means failure" are unaffected, but scripts that specifically check `exit code == 1` to distinguish failure types should be updated to check the new codes above.

### Build The Executables

One command builds every distribution file (Windows, Python 3.10+):

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

It creates (or reuses) `.venv`, installs a pinned PyInstaller, runs the unit tests, and writes to `dist\`:

```text
dist\WSLManager.exe                          GUI (one file, no Python needed)
dist\wslmgr.exe                              command-line tool
dist\installer\WSLManager-Setup-X.Y.Z.exe     installer (when Inno Setup 6.3+ is installed)
dist\WSLManager-X.Y.Z-portable.zip           both executables + README + LICENSE
dist\SHA256SUMS.txt                          checksums
```

Options: `-SkipTests`, `-SkipInstaller`, `-RequireInstaller` (fail instead of skipping when Inno Setup is missing; install it with `winget install JRSoftware.InnoSetup`), `-Python <python.exe>`, `-Iscc <ISCC.exe>`. CI runs the same script, so local builds match release builds.

Both executables carry the application icon (`assets/wslmanager.ico`) and Windows version information (product name and version in Explorer's file properties), generated from `wsl_core.__version__`. UPX is not used, to reduce antivirus false positives.

The checked-in `WSLManager.spec` and `pyinstaller_hooks/` directory are intentional. They make builds more reliable in conda/miniforge environments where unrelated package hooks or Tcl/Tk detection can break PyInstaller analysis. To run PyInstaller by hand: `python -m PyInstaller --clean WSLManager.spec` (GUI) and `python -m PyInstaller --clean WSLManagerCLI.spec` (CLI).

#### Command-line executable

`dist\WSLManager.exe` is a windowed GUI build, so it prints nothing to a terminal. The command-line tool `dist\wslmgr.exe` is built separately from `WSLManagerCLI.spec`. It is a console executable that does not need Python, so output, redirection and exit codes behave like any other command-line tool (0 success, 1 error, 2 bad arguments, 3 cancelled, 4 WSL failure, 5 partial failure). It does not include tkinter and does not use `pyinstaller_hooks/`.

- Startup takes about 0.6 seconds because a one-file executable unpacks itself on every run (running `python wslmgr_cli.py` directly takes about 0.15 seconds).
- When output is redirected to a file or pipe, text is encoded with the Windows ANSI code page (for example cp932 on Japanese Windows). On a system whose code page cannot represent Japanese, messages that contain Japanese can fail to encode. `PYTHONIOENCODING` is ignored by the one-file executable. This is the same limitation as the Python script and is tracked as a separate issue.
- `snapshot schedule create` registers the installed `wslmgr.exe` itself in Task Scheduler, with its absolute path. If you move or uninstall the executable, delete the task first with `snapshot schedule delete`.
- Do not confuse `wslmgr.exe` (this build) with `wslmgr.bat` in the repository root, which is a launcher that runs the Python script and needs Python.

#### Windows installer

`installer/WSLManager.iss` is an [Inno Setup](https://jrsoftware.org/isinfo.php) 6.3+ script that builds `WSLManager-Setup-<version>.exe` (`build.ps1` runs it for you). To compile it by hand, build `dist\WSLManager.exe` and `dist\wslmgr.exe` first, then pass the version from `pyproject.toml` (it must be a plain `X.Y.Z`):

```powershell
iscc /DAppVersion=1.0.0 installer\WSLManager.iss
```

```text
dist\installer\WSLManager-Setup-1.0.0.exe
```

CI compiles the installer on every push and pull request and uploads it as the `WSLManager-installer` artifact. What the installer does:

- **Per-user by default.** No administrator rights are needed and the files go to `%LOCALAPPDATA%\Programs\WSL Manager`. The install dialog can switch to an all-users install (`Program Files`, needs administrator rights).
- Installs `WSLManager.exe` (GUI) and `wslmgr.exe` (command line) and adds a Start menu shortcut. A desktop shortcut and **Add the command-line tool to PATH** are optional and **off by default**. The PATH entry goes to your user `PATH`, or to the system `PATH` for an all-users install, and only the entry for the install folder is removed again on uninstall. A terminal that is already open does not see the change.
- Refuses to install over, or uninstall, a running WSL Manager. Close it first. It does not close a running `wslmgr.exe` on its own, because that may be in the middle of an export or a scheduled snapshot: if a file is in use, Setup retries a few times and then stops (Setup's exit code 5, which is unrelated to the exit codes of `wslmgr.exe`) with the installed files untouched. Wait for the command to finish and run Setup again.
- **Uninstalling keeps your data**: settings and logs (`%APPDATA%\WSLManager`) and snapshots (`%USERPROFILE%\WSLSnapshots`) are never removed, because snapshots are backups of your WSL distributions.
- Scheduled snapshot tasks are not removed either. They point at the installed `wslmgr.exe` by its full path, so delete them with `wslmgr.exe snapshot schedule delete` (run it from the install folder) before you move or uninstall WSL Manager.
- The installer is available in English and Japanese. It is not code-signed, so Windows SmartScreen may warn when you run it.

Silent installation (for scripts):

```powershell
.\WSLManager-Setup-1.0.0.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER /DIR="C:\Tools\WSLManager" /TASKS=addtopath_user
```

Use `/ALLUSERS` instead of `/CURRENTUSER` (and `/TASKS=addtopath_system`) for an all-users install. For an all-users install keep the default `Program Files` folder: do not combine `addtopath_system` with a `/DIR` that ordinary users can write to, because that folder would then be on the system `PATH` for everyone. To uninstall silently, run `unins000.exe /VERYSILENT /SUPPRESSMSGBOXES` from the install folder (it stops, like Setup, while WSL Manager is running).

Releases and downloads: pushing a tag `vX.Y.Z` that matches the version in `pyproject.toml` (and `wsl_core.__version__`) makes CI publish a GitHub Release with `WSLManager-Setup-X.Y.Z.exe`, `WSLManager-X.Y.Z-portable.zip`, the standalone `WSLManager.exe` (GUI) and `wslmgr.exe` (command line), and `SHA256SUMS.txt`. The files are not code-signed, so the checksums only help you notice a damaged or swapped download. Compare them with the file you downloaded:

```powershell
Get-FileHash .\WSLManager-Setup-1.0.0.exe -Algorithm SHA256
Get-Content .\SHA256SUMS.txt
```

CI also installs the installer for real on every run (`installer\verify-installer.ps1`: silent install, upgrade, uninstall, the PATH and desktop-shortcut tasks, and a file in use). You can run it yourself with `pwsh -File installer\verify-installer.ps1 -Setup <Setup.exe> -InstallDir <temporary folder>`. It refuses to run on a machine where WSL Manager is already installed (it uses the same AppId and would replace that installation) and deletes `-InstallDir`, so it only accepts an empty folder under your temporary folder unless you pass `-Force`. It never starts WSL Manager or touches WSL or your data; it changes your user `PATH` only while its PATH checks run and restores the original value and type exactly.

## Implementation Notes

### Modules

| File | Responsibility |
|------|----------------|
| `wslmgr.py` | tkinter main window (`WSLManager`): toolbar, list, detail panel, status bar, menus, and every action with its confirmations |
| `wslmgr_gui/` | GUI building blocks: `detail_panel.py`, `style.py` (shared styles and colors), `ui_queue.py` (hands results from worker threads to the Tk main thread), `resources.py` (bundled icon, locating `wslmgr.exe`), `dialogs/` (forms and dialogs), `app/` (mixins of the main window), Windows constants and registry helpers |
| `wslmgr_cli.py` | argparse-based command-line interface for scriptable WSL operations |
| `wsl_core/` | Pure logic: parsing, formatting, validation, settings, logs, snapshots, progress, translations, and which actions are available for a distribution |
| `tests/` | unittest coverage for the core package, the CLI, and the GUI (with mocks; no real windows) |
| `WSLManager.spec` / `WSLManagerCLI.spec` | PyInstaller build definitions (GUI / CLI) |
| `pyinstaller_hooks/` | Local PyInstaller hooks for tkinter/Tcl/Tk packaging |
| `tools/pyinstaller_support.py` | Version information for the executables, shared by both spec files |
| `assets/` | Application icon (`.ico` for the executables and the installer, `.png` for the window) |
| `build.ps1` | One-command build of the executables, installer, portable ZIP and checksums |
| `installer/` | Inno Setup script and its verification script |

### Architecture

- GUI code is Windows-focused and uses `tkinter`, `ttk`, `subprocess`, and `winreg`.
- Core logic avoids GUI, registry, and subprocess dependencies where practical so it can be tested on non-Windows CI.
- WSL command output is decoded by `wsl_core.decode_wsl_output()` to handle UTF-16 LE, UTF-8, CP932, and fallback encodings.
- Long-running operations run in background workers to keep the GUI responsive. Workers never touch Tk widgets: they post results to a queue that the main thread drains (`wslmgr_gui/ui_queue.py`).
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
- `snapshot prune --keep N` shows deletion candidates by default; it removes old tar/metadata pairs only with `--yes`, keeping the newest N snapshots per distribution.
- On Windows, `snapshot schedule create <name> --time HH:MM --keep N` registers a daily Task Scheduler job. Registration and removal both require confirmation; the created job explicitly carries `--yes` because its retention deletion was approved during registration. Use `snapshot schedule list` or `delete <name>` to manage it.
- Operation logs are serialized as structured records and rotated by helper functions in `wsl_core/logging.py`.

### Packaging

Use `build.ps1` (or the spec files), not a raw `pyinstaller wslmgr.py` command. The GUI spec collects conda/miniforge DLLs when present, bundles the window icon, and the local hooks make tkinter data files available as `_tcl_data` and `_tk_data` for PyInstaller's runtime hook.

### Testing

Run the test suite:

```powershell
python -m py_compile wslmgr.py wslmgr_cli.py
python -m compileall -q wsl_core wslmgr_gui tools
python -m unittest discover -s tests -v
```

Linux/macOS can run most non-GUI checks with `python3`.

### CI

GitHub Actions runs compile checks and unit tests on Ubuntu and Windows across supported Python versions, ruff and mypy, and on Windows builds every distribution file with `build.ps1`, checks the executables' version information, installs and uninstalls the installer for real, and checks the portable ZIP.

## License

MIT License. See [LICENSE](LICENSE).
