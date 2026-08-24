"""wsl_core - Backward-compatible module shim for wsl_core package.

This module re-exports all public symbols and internal constants from the
wsl_core package to maintain full backward compatibility with existing imports
and callers.
"""

from __future__ import annotations

import os  # noqa: F401
import sys  # noqa: F401

from wsl_core import *  # noqa: F403
