# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
