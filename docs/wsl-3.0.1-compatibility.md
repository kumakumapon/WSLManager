# WSL 3.0.1 compatibility

Draft PR #64 was opened with this plan before implementation. The baseline is
Microsoft's `3.0.1` tag, commit `91f161fa240dc355c1a88daabc8aac4273e35ba5`.
This work corrects the existing read-only integration, not the entire WSLc feature set.

## Verified contracts

| Operation | Official output/behavior | App handling |
| --- | --- | --- |
| `container list --format json` | One object per line; no output when empty | Strict NDJSON, including CRLF/BOM, error on malformed records |
| List fields | `ID`, `Names`, `Image`, `Status`, `HealthStatus`, `CreatedAt` | Shared six-column summary; no guessed collection wrapper |
| List scope/IDs | Running only by default; `--all`, `--no-trunc` supported | Optional stopped view; always request full IDs |
| `container inspect <name-or-id>` | JSON array by default; nested state/health | Preserve nested array, use full ID from the selected row |
| `system info --format json` | Object with `Client`, `Server`, `Server.Sessions` | Preserve object, validate shape/version, reuse successful CLI probe |
| `--session <name>` | Opens an existing session by display name | Required in CLI; existing-session selector in GUI |
| No `--session` on list/inspect | Resolves/creates default session | Never used by the app |

Sources (pinned tag):

- [ContainerListCommand.cpp](https://github.com/microsoft/WSL/blob/3.0.1/src/windows/wslc/commands/ContainerListCommand.cpp)
- [ContainerTasks.cpp](https://github.com/microsoft/WSL/blob/3.0.1/src/windows/wslc/tasks/ContainerTasks.cpp): `ToContainerOutput`, `ListContainers`, `InspectContainers`.
- [SessionTasks.cpp](https://github.com/microsoft/WSL/blob/3.0.1/src/windows/wslc/tasks/SessionTasks.cpp): `ShowSystemInfo`, `ResolveSession`.
- [SessionService.cpp](https://github.com/microsoft/WSL/blob/3.0.1/src/windows/wslc/services/SessionService.cpp): `OpenSession`, `OpenOrCreateDefaultSession`.
- [RootCommand.cpp](https://github.com/microsoft/WSL/blob/3.0.1/src/windows/wslc/commands/RootCommand.cpp): global session option.
- [Official list end-to-end tests](https://github.com/microsoft/WSL/blob/3.0.1/test/windows/wslc/e2e/WSLCE2EContainerListTests.cpp): NDJSON, full IDs, stopped containers.

## Compatibility and safety

- Stable WSL package versions 3.0.1+ (three/four numeric components) pass the
  version gate; preview/unrecognized strings do not. This is an app support
  policy, not a claim that every future WSL version has been validated.
- `doctor` reports `wslc.version_supported` separately from `wslc.available`.
  Availability means system-info succeeded with a recognized contract, not that
  every container operation will succeed. Windows versions remain diagnostic
  evidence; actual service errors determine availability instead of a guessed OS gate.
- Service contact may start the service. No command creates a session or
  changes container lifecycle/network state. Errors do not trigger fallback,
  privilege elevation, or updates.
- `container system-info --format json` and `doctor.wslc_system` are now objects,
  not one-element arrays. `list` JSON remains the normalized summary array.
- `list` and `inspect` now require `--session NAME`. A missing option is an
  argparse error (2); WSLc/response failures exit 4, writing diagnostics to stderr.
  `doctor --format json` still emits its report when unavailable, then exits 4.
- GUI work is serialized. Workers only enqueue results; Tk polling and widget
  changes happen on the UI thread. Closing cancels polling and ignores late results.
- No distribution conversion, destructive prompts, build hooks or dependencies changed.

## Automated checks

`tests/test_wsl_containers.py` uses source-shaped synthetic fixtures and mocked
commands: NDJSON/empty/error cases, official field names, version boundaries,
service policy errors, exact command arrays, explicit sessions, full IDs, CLI
JSON/CSV/table output, and headless tests of the actual dialog class's workers,
selection, close/poll lifecycle and inspect targeting.

```sh
python -m unittest discover -s tests -v
ruff check .  # pinned 0.15.8
python -m py_compile wslmgr.py wslmgr_cli.py wsl_core/*.py
```

## Windows 3.0.1 smoke checklist (not executed in the Linux editing environment)

- [ ] Compare `doctor --format json` with `wsl --version` / `wslc system info --format json`.
- [ ] With zero sessions, open Containers; verify no session is created.
- [ ] Select an already-existing session; compare default/`--all` lists with native WSLc.
- [ ] Verify multiple rows, Japanese names, full-ID inspect and nested health.
- [ ] Remove a session externally, then refresh; verify an error without default-session creation.
- [ ] Check missing executable, policy denial and service failure diagnostics.
- [ ] Rapidly refresh/inspect and close during a request; no Tcl errors or post-close dialogs.
- [ ] Check scrollbars, English/Japanese labels, and existing distro operations.

実装・自動テストは完了対象ですが、Windows 実機と実際の WSLc サービスの確認は
この環境では未実施です。上記チェックリストで別途確認してください。
