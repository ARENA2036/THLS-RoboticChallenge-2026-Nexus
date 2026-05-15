"""
Explicit conflict-handling policy for multi-robot coordination.

Replaces implicit retry behavior with an auditable policy object.
"""

from __future__ import annotations

from enum import StrEnum


class SafetyPolicy(StrEnum):
    STRICT_WAIT = "STRICT_WAIT"
    ABORT_ON_CONFLICT = "ABORT_ON_CONFLICT"
