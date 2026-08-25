"""
wsl_core - WSL Manager の純粋ロジックパッケージ

tkinter・winreg に依存しないロジックを提供します。
責務別に分割されたサブモジュールから構成され、後方互換性のために
すべての公開 API をトップレベル名前空間に再エクスポートしています。
"""

from __future__ import annotations

import configparser  # noqa: F401
import io  # noqa: F401
import json  # noqa: F401
import os  # noqa: F401
import queue  # noqa: F401
import re  # noqa: F401
import subprocess  # noqa: F401
import sys  # noqa: F401
import tempfile  # noqa: F401
import threading  # noqa: F401
from dataclasses import dataclass  # noqa: F401
from datetime import datetime  # noqa: F401
from typing import Any, TypedDict  # noqa: F401

from .i18n import (
    LANGUAGE_AUTO,
    SUPPORTED_LANGUAGES,
    detect_system_language,
    normalize_language,
    resolve_language,
    translate,
)
from .logging import (
    AsyncLogWriter,
    append_log_entry,
    delete_log_files,
    deserialize_log_entries,
    format_log_entry_from_dict,
    format_operation_log_entry,
    get_default_log_dir,
    log_file_paths,
    rotate_log_files,
    serialize_log_entry,
    tail_entries,
)
from .parsing import (
    _WSL_UPDATE_UP_TO_DATE_PATTERNS,  # noqa: F401
    _WSL_UPDATE_VERSION_RE_EN,  # noqa: F401
    _WSL_UPDATE_VERSION_RE_JA,  # noqa: F401
    WslConfigParseError,
    build_diskpart_compact_script,
    build_wsl_mount_args,
    build_wsl_unmount_args,
    dump_wslconfig,
    is_numeric,
    normalize_base_path,
    parse_disk_usage,
    parse_distro_list,
    parse_ip_addresses,
    parse_online_distros,
    parse_os_release,
    parse_process_list,
    parse_resource_usage,
    parse_uptime,
    parse_wsl_update_output,
    parse_wsl_version,
    parse_wslconfig,
)
from .portproxy import (
    _SS_PROCESS_RE,  # noqa: F401
    detect_network_mode,
    parse_portproxy_output,
    parse_ss_output,
)
from .resource_history import (
    DEFAULT_PALETTE,
    ChartAxisTick,
    ChartLayout,
    ChartPoint,
    ChartSeries,
    ResourceHistory,
    ResourceSample,
    calculate_nice_ceiling,
    find_nearest_chart_point,
    get_distro_color,
    parse_numeric_resource,
    prepare_chart_layout,
)
from .runner import (
    decode_wsl_output,
    run_wsl,
)
from .settings import (
    _GEOMETRY_RE,  # noqa: F401
    DEFAULT_SETTINGS,
    PARTIAL_WRITE_SUFFIX,
    atomic_write_text,
    discard_partial_write,
    finalize_partial_write,
    get_default_settings_path,
    is_valid_geometry,
    load_settings,
    normalize_settings,
    partial_write_path,
    save_settings,
    save_wslconfig,
)
from .snapshot import (
    _SNAPSHOT_FORBIDDEN_CHARS,  # noqa: F401
    SNAPSHOT_TIMESTAMP_FORMAT,
    build_distro_snapshot,
    build_snapshot_basename,
    build_snapshot_metadata,
    diff_snapshots,
    format_snapshot_summary,
    get_default_snapshot_dir,
    load_snapshots,
    normalize_snapshot_metadata,
    sanitize_snapshot_name,
    snapshots_to_prune,
    total_snapshots_size,
    write_snapshot_metadata,
)
from .transfer import (
    estimate_remaining_seconds,
    estimate_transfer_progress,
    format_bytes,
    format_duration,
    format_transfer_status,
)
from .types import (
    CURRENT_SCHEMA_VERSION,
    DiskUsage,
    DistroInfo,
    ListeningSocket,
    LogEntry,
    PortproxyRule,
    ProcessInfo,
    Settings,
    SnapshotMetadata,
    WslResult,
)
from .validation import (
    _HOSTNAME_LABEL_RE,  # noqa: F401
    _LINUX_USERNAME_RE,  # noqa: F401
    _MEMORY_RE,  # noqa: F401
    _WINDOWS_RESERVED_NAMES,  # noqa: F401
    default_clone_name,
    parse_memory_to_bytes,
    validate_clone_name,
    validate_distro_name,
    validate_hostname,
    validate_linux_username,
    validate_memory_string,
    validate_mount_root,
    validate_port_number,
    validate_processors_string,
    validate_swap_string,
    validate_wslconf_bool,
)

__version__ = "1.0.0"

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "DEFAULT_PALETTE",
    "DEFAULT_SETTINGS",
    "LANGUAGE_AUTO",
    "PARTIAL_WRITE_SUFFIX",
    "SNAPSHOT_TIMESTAMP_FORMAT",
    "SUPPORTED_LANGUAGES",
    "AsyncLogWriter",
    "ChartAxisTick",
    "ChartLayout",
    "ChartPoint",
    "ChartSeries",
    "DiskUsage",
    "DistroInfo",
    "ListeningSocket",
    "LogEntry",
    "PortproxyRule",
    "ProcessInfo",
    "ResourceHistory",
    "ResourceSample",
    "Settings",
    "SnapshotMetadata",
    "WslConfigParseError",
    "WslResult",
    "__version__",
    "append_log_entry",
    "atomic_write_text",
    "build_diskpart_compact_script",
    "build_distro_snapshot",
    "build_snapshot_basename",
    "build_snapshot_metadata",
    "build_wsl_mount_args",
    "build_wsl_unmount_args",
    "calculate_nice_ceiling",
    "decode_wsl_output",
    "default_clone_name",
    "delete_log_files",
    "deserialize_log_entries",
    "detect_network_mode",
    "detect_system_language",
    "diff_snapshots",
    "discard_partial_write",
    "dump_wslconfig",
    "estimate_remaining_seconds",
    "estimate_transfer_progress",
    "finalize_partial_write",
    "find_nearest_chart_point",
    "format_bytes",
    "format_duration",
    "format_log_entry_from_dict",
    "format_operation_log_entry",
    "format_snapshot_summary",
    "format_transfer_status",
    "get_default_log_dir",
    "get_default_settings_path",
    "get_default_snapshot_dir",
    "get_distro_color",
    "is_numeric",
    "is_valid_geometry",
    "load_settings",
    "load_snapshots",
    "log_file_paths",
    "normalize_base_path",
    "normalize_language",
    "normalize_settings",
    "normalize_snapshot_metadata",
    "parse_disk_usage",
    "parse_distro_list",
    "parse_ip_addresses",
    "parse_memory_to_bytes",
    "parse_numeric_resource",
    "parse_online_distros",
    "parse_os_release",
    "parse_portproxy_output",
    "parse_process_list",
    "parse_resource_usage",
    "parse_ss_output",
    "parse_uptime",
    "parse_wsl_update_output",
    "parse_wsl_version",
    "parse_wslconfig",
    "partial_write_path",
    "prepare_chart_layout",
    "resolve_language",
    "rotate_log_files",
    "run_wsl",
    "sanitize_snapshot_name",
    "save_settings",
    "save_wslconfig",
    "serialize_log_entry",
    "snapshots_to_prune",
    "tail_entries",
    "total_snapshots_size",
    "translate",
    "validate_clone_name",
    "validate_distro_name",
    "validate_hostname",
    "validate_linux_username",
    "validate_memory_string",
    "validate_mount_root",
    "validate_port_number",
    "validate_processors_string",
    "validate_swap_string",
    "validate_wslconf_bool",
    "write_snapshot_metadata",
]
