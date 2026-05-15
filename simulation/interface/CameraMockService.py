"""
Camera orientation service protocol and mock implementation.

The protocol abstracts pose-offset computation so that a real
camera service can replace the mock with minimal executor changes.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Protocol, Tuple, runtime_checkable


@dataclass
class PoseOffset:
    """Small Cartesian + angular correction between a target and an
    observed frame."""
    delta_x_m: float = 0.0
    delta_y_m: float = 0.0
    delta_z_m: float = 0.0
    delta_yaw_deg: float = 0.0


@runtime_checkable
class CameraOrientationService(Protocol):
    """Protocol for camera-based pose offset computation."""

    def computeInsertionOffset(
        self,
        target_position_m: Tuple[float, float, float],
        target_yaw_deg: float,
    ) -> PoseOffset:
        """Return the small pose offset between the ideal target and
        the observed insertion frame."""
        ...


class CameraMockServiceImpl:
    """Mock camera that returns small random offsets.

    Useful for testing the pre-adjustment logic without real hardware.
    """

    def __init__(
        self,
        max_translation_m: float = 0.002,
        max_yaw_deg: float = 1.5,
        seed: int = 42,
    ) -> None:
        self._max_translation_m = max_translation_m
        self._max_yaw_deg = max_yaw_deg
        self._rng = random.Random(seed)

    def computeInsertionOffset(
        self,
        target_position_m: Tuple[float, float, float],
        target_yaw_deg: float,
    ) -> PoseOffset:
        return PoseOffset(
            delta_x_m=self._rng.uniform(-self._max_translation_m, self._max_translation_m),
            delta_y_m=self._rng.uniform(-self._max_translation_m, self._max_translation_m),
            delta_z_m=0.0,
            delta_yaw_deg=self._rng.uniform(-self._max_yaw_deg, self._max_yaw_deg),
        )
