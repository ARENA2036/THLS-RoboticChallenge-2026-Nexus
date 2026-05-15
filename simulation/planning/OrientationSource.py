"""
Orientation source protocol and implementations.

Abstracts how object orientations are obtained -- random (simulation),
camera-based (future real robot), or fixed (testing).  The planner and
executor consume this protocol without caring about the concrete source.
"""

from __future__ import annotations

import random
from typing import Protocol, runtime_checkable


@runtime_checkable
class OrientationSource(Protocol):
    """Returns the Z-rotation in degrees for a given object."""

    def getObjectOrientation(self, object_id: str) -> float: ...


class RandomOrientationSource:
    """Reproducible random Z-rotation per object (seeded RNG)."""

    def __init__(self, seed: int = 42) -> None:
        self._rng = random.Random(seed)

    def getObjectOrientation(self, object_id: str) -> float:
        return self._rng.uniform(0.0, 360.0)


class FixedOrientationSource:
    """Returns a fixed orientation for all objects -- useful for testing."""

    def __init__(self, orientation_deg: float = 0.0) -> None:
        self._orientation_deg = orientation_deg

    def getObjectOrientation(self, object_id: str) -> float:
        return self._orientation_deg
