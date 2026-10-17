# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- WSL 3.0.1 / WSL Containers (WSLc) support, read-only: `doctor` (`--format table|json|csv`), `container system-info` / `list` / `inspect` CLI commands, and a **Tools → WSL Containers…** GUI view. Container lifecycle and network mutations are intentionally not provided (#61, #62).
- Multilingual support (Japanese / English): automatic system-language detection, GUI language menu, and CLI `--language {auto,ja,en}` (#2, #57, #59).
- CPU / memory resource history graphs (last 30 minutes per distribution) with hover details (#3, #54, #56).
- `snapshot prune` (dry-run by default; deletion requires `--yes`) with generation retention, and scheduled snapshots via Windows Task Scheduler (create / list / delete, with confirmation) (#4, #56).
- `start_wslmanager.bat` launcher that prefers `dist\WSLManager.exe` and falls back to `.venv` or the Python Launcher (#55).
- `wslmgr.bat` CLI launcher: finds Python (`.venv`, then `py -3`, then `python`), runs `wslmgr_cli.py` with every argument passed through, and returns the CLI exit code unchanged so it can be used from scripts. `.gitattributes` keeps `*.bat` files on CRLF line endings, which `goto` labels need.
- Static type checking with `mypy` (pinned, run in CI) for `wsl_core`, `wslmgr_gui`, `wslmgr.py` and `wslmgr_cli.py`; `platform = "win32"` is set so Windows-only APIs such as `winreg` are typed on any OS (#68, #76).
- Automated tests for the GUI confirmation prompts of destructive operations: stop, shutdown, unregister (two-step), WSL version conversion, snapshot deletion, export overwrite, import, snapshot restore, VHDX compaction / sparse, WSL update, transfer cancel, and quitting with a running transfer (#67, #75).
- Tests that guard the `WSLManager` split: structure checks (Tk last in the MRO, mixins define no `__init__`, no method is defined twice, and the members the dialogs rely on stay on `WSLManager`) (#78), and behavior tests for the operation log, settings / theme / language / auto refresh (#79) and the distribution data fetching (#80).

### Changed
- Split `wsl_core.py` into a responsibility-based `wsl_core/` package; the top-level `wsl_core` module remains a backward-compatible shim (#30, #53).
- `container list` now parses NDJSON output (multi-line, empty, CRLF/BOM) and reports malformed output instead of showing 0 items. Containers are listed with `ID / Names / Image / Status / HealthStatus / CreatedAt` and inspected by full ID; an existing session name is always passed explicitly to avoid creating a default WSLc session (#64).
- Split `wslmgr.py` (4,766 lines) into the `wslmgr_gui` package, leaving 1,753 lines. Behavior is unchanged, and confirmation prompts were moved as-is. Existing names such as `wslmgr.SnapshotManagerDialog` remain importable.
  - Windows helpers, `TreeviewSorter` and all 14 dialogs moved to `wslmgr_gui/` (`winutil.py`, `widgets.py`, `dialogs/`) (#69-#74).
  - `WSLManager` is now assembled from mixins in `wslmgr_gui/app/`: `ResourceHistoryMixin` (resource history graph, #78), `OperationLogMixin` (operation log) and `SettingsMixin` (auto refresh, theme, language, settings persistence) (#79). `AppBase` declares the members the mixins use for type checking; at runtime it derives from `object`, so the MRO is unchanged.
  - Distribution list / CPU / memory / IP fetching became plain functions in `wslmgr_gui/distro_data.py` (`get_distros`, `get_distro_ip`, `get_distro_resource_usage`) (#80).
  - `WSLManager` keeps `__init__`, UI construction, the refresh core and the operations that show confirmation prompts (stop / shutdown, unregister, export / import, version conversion, snapshots, mount, WSL update, quit).
- Narrowed broad `except Exception` handling in the GUI. Failures swallowed while collecting per-distribution resource usage and IP addresses are now logged at debug level (#66).
- CI and docs now also byte-compile `wsl_core` and `wslmgr_gui` (#69).

### Fixed
- GUI WSL Containers Inspect now uses the container `Id` field instead of the `-` placeholder (#63).
- Restored localized process-kill success feedback and translated remaining CLI help text (#58, #59).

### Security
- Prevented `cmd.exe` / `wt.exe` argument injection via distribution names (#52).

## [1.0.0] - 2026-08-22

### Added
- `--version` CLI option and application version display in GUI About dialog (#32).
- `pyproject.toml` `[project]` metadata with `wslmgr` console script entry point (#32).
- `CONTRIBUTING.md`, issue templates (bug report, feature request), and pull request template (#39).
- Enhanced CI workflow with PyInstaller build verification and coverage tracking (#31).
- `TypedDict` definitions for structured data (`DistroInfo`, `SnapshotMetadata`, `LogEntry`, `Settings`, etc.) (#37).
- Schema versioning (`schema_version = 1`) and migration structure for settings, snapshots metadata, and logs (#33).
- Queue size limit (1000 items) and error/drop counters in `AsyncLogWriter` (#35).
- Visible unparsed line reporting in `parse_wsl_version` and GUI WSL Version dialog (#41).
- Unified WSL command execution helper `run_wsl` and `WslResult` in `wsl_core` (#29).
- High DPI awareness support and single instance protection via Windows Named Mutex (#38).
- Standardized CLI exit codes (0: success, 1: general error, 2: argument error, 3: user cancelled, 4: WSL command failure, 5: partial failure) (#28).
- Full CLI parity: IP address and disk size display, `/etc/wsl.conf` editing, `log clear`, and `--format json` / `--quiet` flags across subcommands (#15, #36).
- Snapshot directory configuration UI in GUI and `snapshot set-dir` CLI command (#17).
- `wsl --update` progress dialog, `wsl --mount` / `--unmount` dialog/CLI support, and extended `.wslconfig` `[wsl2]` fields (#40).
- Safe comment preserving / fallback text editing for `.wslconfig` and `/etc/wsl.conf` (#34).
