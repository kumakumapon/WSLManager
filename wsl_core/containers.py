"""Read-only WSLc 3.0.1 contracts shared by CLI/GUI.

List uses NDJSON, inspect an array, system info an object. Explicit session
names prevent WSLc from implicitly creating a default session.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from .runner import run_command
from .types import WslResult

WSLC_MINIMUM_VERSION = (3, 0, 1)
_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:\.\d+)?")


class WslcError(ValueError):
    """A failed command or invalid response, never an empty success."""


def parse_semantic_version(value: str | None) -> tuple[int, int, int] | None:
    """Accept stable three/four-part WSL versions, not preview suffixes."""
    match = _VERSION_RE.fullmatch(value.strip()) if value else None
    return tuple(int(part) for part in match.groups()) if match else None


def wslc_capability(wsl_version: str | None) -> dict[str, Any]:
    """Version eligibility only; availability requires a successful service probe."""
    parsed = parse_semantic_version(wsl_version)
    supported = parsed is not None and parsed >= WSLC_MINIMUM_VERSION
    return {
        "available": False,
        "version_supported": supported,
        "minimum_version": "3.0.1",
        "detected_version": wsl_version or "",
        "reason": ""
        if supported
        else "A detected stable WSL version of 3.0.1 or later is required.",
    }


def parse_wslc_json(output: str, *, ndjson: bool = False) -> list[dict[str, Any]]:
    """Parse strictly; only NDJSON may legitimately have empty output."""
    text = output.lstrip("\ufeff").strip()
    if not text:
        if ndjson:
            return []
        raise WslcError("WSLc returned empty JSON output.")
    try:
        if ndjson:
            records = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            value = json.loads(text)
            records = value if isinstance(value, list) else [value]
    except json.JSONDecodeError as exc:
        raise WslcError(f"Invalid WSLc JSON output: {exc}") from exc
    if any(not isinstance(record, dict) for record in records):
        raise WslcError("WSLc JSON records must be objects.")
    return records


def container_summary(record: dict[str, Any]) -> dict[str, str]:
    """Official list fields with inspect/legacy field fallbacks."""

    def display(value: Any) -> str:
        if value is None or value == "":
            return "-"
        if isinstance(value, list):
            return ", ".join(str(item) for item in value) or "-"
        return str(value)

    def first(*keys: str) -> Any:
        return next((record[key] for key in keys if record.get(key) not in (None, "")), None)

    state = first("State", "state")
    health = first("HealthStatus", "health", "Health")
    status = first("Status", "status")
    if isinstance(state, dict):
        status = status or state.get("Status") or state.get("status")
        health = health or state.get("Health") or state.get("health")
    else:
        status = status or state
    if isinstance(health, dict):
        health = health.get("Status") or health.get("status")
    return {
        "id": display(first("ID", "Id", "id", "container_id")),
        "name": display(first("Names", "Name", "name", "names")),
        "image": display(first("Image", "image")),
        "status": display(status),
        "health": display(health),
        "created": display(first("CreatedAt", "Created", "created", "created_at")),
    }


def _identifier(value: str, label: str) -> str:
    # Reject option-like tokens even if supplied after argparse's '--'.
    if not value or not value.strip() or value.startswith("-") or any(ord(c) < 32 for c in value):
        raise WslcError(f"Invalid {label}: a nonempty name/ID, not an option, is required.")
    return value


class WslcClient:
    """Command allowlist. Never creates sessions or changes containers."""

    def __init__(self, runner: Callable[[list[str]], WslResult] | None = None) -> None:
        self._runner = runner or (lambda args: run_command(["wslc", *args], timeout=15.0))

    def _run(self, args: list[str]) -> str:
        result = self._runner(args)
        if result.returncode != 0:
            raise WslcError(
                result.stderr.strip()
                or result.stdout.strip()
                or f"wslc failed (exit {result.returncode})."
            )
        return result.stdout

    def system_info(self) -> dict[str, Any]:
        output = self._run(["system", "info", "--format", "json"])
        records = parse_wslc_json(output)
        if not output.lstrip("\ufeff \t\r\n").startswith("{") or len(records) != 1:
            raise WslcError("WSLc system info must be a JSON object.")
        info = records[0]
        client, server = info.get("Client"), info.get("Server")
        if not isinstance(client, dict) or not isinstance(server, dict):
            raise WslcError("WSLc system info is missing Client/Server.")
        if not wslc_capability(str(client.get("Version", "")))["version_supported"]:
            raise WslcError("The wslc client must be stable version 3.0.1 or later.")
        sessions = server.get("Sessions")
        if not isinstance(sessions, list) or any(
            not isinstance(item, dict)
            or not isinstance(item.get("Name"), str)
            or not item["Name"].strip()
            for item in sessions
        ):
            raise WslcError("WSLc system info has invalid Server.Sessions.")
        return info

    def list_containers(
        self, session: str, *, all_containers: bool = False
    ) -> list[dict[str, Any]]:
        args = [
            "container",
            "list",
            "--session",
            _identifier(session, "session"),
            "--format",
            "json",
            "--no-trunc",
        ]
        if all_containers:
            args.append("--all")
        records = parse_wslc_json(self._run(args), ndjson=True)
        if any(not isinstance(row.get("ID"), str) or not row["ID"] for row in records):
            raise WslcError("WSLc container list records must include an ID.")
        return records

    def inspect_container(self, session: str, name: str) -> list[dict[str, Any]]:
        output = self._run(
            [
                "container",
                "inspect",
                "--session",
                _identifier(session, "session"),
                _identifier(name, "container"),
            ]
        )
        if not output.lstrip("\ufeff \t\r\n").startswith("["):
            raise WslcError("WSLc inspect must return a JSON array.")
        return parse_wslc_json(output)
