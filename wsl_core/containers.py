"""WSL Containers (WSLc) capability and output helpers.

The helpers in this module do not execute commands.  Keeping capability checks and
JSON parsing here makes them usable from both the CLI and the tkinter UI, and lets
Linux CI exercise the behaviour without a Windows WSL installation.
"""

from __future__ import annotations

import json
import re
from typing import Any

WSLC_MINIMUM_VERSION = (3, 0, 1)
_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def parse_semantic_version(value: str | None) -> tuple[int, int, int] | None:
    """Return the first ``major.minor.patch`` tuple in *value*, if present."""
    if not value:
        return None
    match = _VERSION_RE.search(value)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def wslc_capability(wsl_version: str | None) -> dict[str, Any]:
    """Describe whether the installed WSL version can provide WSL Containers."""
    parsed = parse_semantic_version(wsl_version)
    if parsed is None:
        return {
            "available": False,
            "minimum_version": ".".join(map(str, WSLC_MINIMUM_VERSION)),
            "reason": "WSL version could not be detected.",
        }
    available = parsed >= WSLC_MINIMUM_VERSION
    return {
        "available": available,
        "minimum_version": ".".join(map(str, WSLC_MINIMUM_VERSION)),
        "detected_version": ".".join(map(str, parsed)),
        "reason": "" if available else "Update WSL to version 3.0.1 or later.",
    }


def parse_wslc_json(output: str) -> list[dict[str, Any]]:
    """Parse JSON returned by a read-only ``wslc`` command into records.

    WSLc commands may return a top-level list or an object containing a common
    collection key.  Unknown shapes are represented as one record so callers can
    still show the information rather than failing on a newer WSLc release.
    """
    try:
        value = json.loads(output)
    except (TypeError, json.JSONDecodeError):
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("containers", "items", "data"):
            items = value.get(key)
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
        return [value]
    return []


def container_summary(record: dict[str, Any]) -> dict[str, str]:
    """Normalize a WSLc container record for table and GUI presentation."""
    def first(*keys: str) -> str:
        for key in keys:
            value = record.get(key)
            if value is not None:
                return str(value)
        return "-"

    state = record.get("state") or record.get("State") or {}
    if isinstance(state, dict):
        status = first_from(state, "status", "Status", "running", "Running")
        health = first_from(state, "health", "Health")
    else:
        status = str(state) if state else first("status", "Status")
        health = first("health", "Health")
    return {
        "id": first("id", "Id", "ID", "container_id"),
        "name": first("name", "Name", "names"),
        "image": first("image", "Image"),
        "status": status or "-",
        "health": health or "-",
        "created": first("created", "Created", "created_at"),
    }


def first_from(record: dict[str, Any], *keys: str) -> str:
    """Return a display value from a nested JSON object."""
    for key in keys:
        value = record.get(key)
        if value is not None:
            return str(value)
    return ""
