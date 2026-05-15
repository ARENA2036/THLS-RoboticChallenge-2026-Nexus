"""
Force-torque sensor service protocol and mock implementation.

The protocol abstracts force/torque readings so that a real F/T
sensor can replace the mock with minimal executor changes.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import List, Protocol, runtime_checkable


@dataclass
class ForceTorqueReading:
    """A single force-torque measurement."""
    force_x_n: float = 0.0
    force_y_n: float = 0.0
    force_z_n: float = 0.0
    torque_x_nm: float = 0.0
    torque_y_nm: float = 0.0
    torque_z_nm: float = 0.0


@dataclass
class ForceProfile:
    """Recorded force readings over time for QA review."""
    readings: List[ForceTorqueReading] = field(default_factory=list)
    timestamps_s: List[float] = field(default_factory=list)

    def addReading(self, reading: ForceTorqueReading, timestamp_s: float) -> None:
        self.readings.append(reading)
        self.timestamps_s.append(timestamp_s)


@runtime_checkable
class ForceTorqueService(Protocol):
    """Protocol for force-torque sensing during insertion."""

    def readForceTorque(self) -> ForceTorqueReading:
        """Return the current force-torque reading."""
        ...

    def isInsertionComplete(self, reading: ForceTorqueReading) -> bool:
        """Return True when z-force indicates the crimp is fully seated."""
        ...

    def evaluatePullTest(
        self,
        reading: ForceTorqueReading,
        threshold_force_n: float,
    ) -> bool:
        """Return True when the pull-test reading meets the threshold."""
        ...


class ForceTorqueMockServiceImpl:
    """Mock F/T sensor that returns configurable ramp-style readings.

    - ``readForceTorque`` returns a force that increases with each
      successive call, simulating progressive insertion contact.
    - ``isInsertionComplete`` checks whether z-force exceeds the
      configured completion threshold.
    - ``evaluatePullTest`` always returns True (mock behaviour).
    """

    def __init__(
        self,
        insertion_complete_force_n: float = 15.0,
        force_ramp_step_n: float = 5.0,
        seed: int = 42,
    ) -> None:
        self._insertion_complete_force_n = insertion_complete_force_n
        self._force_ramp_step_n = force_ramp_step_n
        self._rng = random.Random(seed)
        self._call_count = 0

    def readForceTorque(self) -> ForceTorqueReading:
        self._call_count += 1
        ramped_force = self._call_count * self._force_ramp_step_n
        noise = self._rng.uniform(-0.5, 0.5)
        return ForceTorqueReading(
            force_z_n=ramped_force + noise,
        )

    def isInsertionComplete(self, reading: ForceTorqueReading) -> bool:
        return abs(reading.force_z_n) >= self._insertion_complete_force_n

    def evaluatePullTest(
        self,
        reading: ForceTorqueReading,
        threshold_force_n: float,
    ) -> bool:
        return True

    def resetRamp(self) -> None:
        """Reset the internal call counter for the next insertion cycle."""
        self._call_count = 0
