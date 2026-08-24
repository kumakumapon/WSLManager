"""
wsl_core.types - WSL Manager のデータ構造・型定義モジュール
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

CURRENT_SCHEMA_VERSION = 1


class DistroInfo(TypedDict, total=False):
    name: str
    state: str
    version: str
    default: bool
    cpu: str
    memory: str
    disk: str
    ip: str


class ProcessInfo(TypedDict):
    pid: int
    user: str
    command: str


class DiskUsage(TypedDict):
    filesystem: str
    size: str
    used: str
    avail: str
    use_percent: str
    mountpoint: str


class LogEntry(TypedDict, total=False):
    timestamp: str
    operation: str
    target: str
    result: str
    source: str
    schema_version: int


class Settings(TypedDict, total=False):
    schema_version: int
    theme: str | None
    auto_refresh: bool
    window_geometry: str | None
    sort_column: str | None
    sort_desc: bool
    snapshot_dir: str | None


class SnapshotMetadata(TypedDict, total=False):
    schema_version: int
    distro_name: str
    wsl_version: str
    comment: str
    size_bytes: int
    created_at: str
    tar_file: str
    json_path: str
    tar_path: str
    tar_exists: bool


class PortproxyRule(TypedDict):
    listen_address: str
    listen_port: int
    connect_address: str
    connect_port: int


class ListeningSocket(TypedDict):
    state: str
    local_address: str
    local_port: int
    process: str


@dataclass
class WslResult:
    """wsl コマンド実行結果を保持するデータクラスです。"""

    returncode: int
    stdout: str
    stderr: str
    error: str | None = None  # None | "not_found" | "timeout" | "os_error"
