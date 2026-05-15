"""
Snapshot save/load for board setup state.

Serialises overlay events and per-robot joint targets to JSON so that
``run_full_assembly.py`` can skip board setup and start wire routing
from a previously completed board state.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List

from simulation.planning.BoardSetupExecutor import OverlayEvent, OverlayEventType

logger = logging.getLogger(__name__)


class SnapshotData:
    """Deserialized snapshot payload."""

    def __init__(
        self,
        overlay_events: List[OverlayEvent],
        robot_home_joints: Dict[str, List[float]],
    ) -> None:
        self.overlay_events = overlay_events
        self.robot_home_joints = robot_home_joints


def saveSnapshot(
    path: str,
    overlay_events: List[OverlayEvent],
    robot_home_joints: Dict[str, List[float]],
) -> None:
    """Persist board setup state to a JSON file."""
    events_serialized = []
    for event in overlay_events:
        event_dict = asdict(event)
        event_dict["position_m"] = list(event_dict["position_m"])
        events_serialized.append(event_dict)

    payload = {
        "version": 1,
        "overlay_events": events_serialized,
        "robot_home_joints": robot_home_joints,
    }

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file_handle:
        json.dump(payload, file_handle, indent=2)

    logger.info("Snapshot saved to %s (%d events)", path, len(overlay_events))


def loadSnapshot(path: str) -> SnapshotData:
    """Load board setup state from a JSON file."""
    file_path = Path(path)
    with file_path.open("r", encoding="utf-8") as file_handle:
        payload = json.load(file_handle)

    overlay_events: List[OverlayEvent] = []
    for event_dict in payload.get("overlay_events", []):
        overlay_events.append(
            OverlayEvent(
                timestamp_s=event_dict["timestamp_s"],
                event_type=OverlayEventType(event_dict["event_type"]),
                object_id=event_dict["object_id"],
                object_type=event_dict["object_type"],
                position_m=tuple(event_dict.get("position_m", (0.0, 0.0, 0.0))),
                robot_name=event_dict.get("robot_name", ""),
                orientation_deg=event_dict.get("orientation_deg", 0.0),
            )
        )

    robot_home_joints: Dict[str, List[float]] = payload.get("robot_home_joints", {})

    logger.info("Snapshot loaded from %s (%d events)", path, len(overlay_events))
    return SnapshotData(
        overlay_events=overlay_events,
        robot_home_joints=robot_home_joints,
    )
