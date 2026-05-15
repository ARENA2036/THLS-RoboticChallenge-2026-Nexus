"""
Middle-out peg-split and robot assignment for dual-arm wire routing.

Given an ordered list of peg IDs along a wire route and the 3D world
positions of those pegs and of the two robot bases, this module:

  1. Splits the peg list into two sub-sequences that diverge from the
     geometric centre outward.
  2. Assigns each wire extremity (connector end) to the robot whose
     base is closer to that connector's board position.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


@dataclass
class MiddleOutAssignment:
    """Result of the middle-out split for one wire route."""
    left_robot_name: str
    right_robot_name: str
    left_peg_sequence: List[str] = field(default_factory=list)
    right_peg_sequence: List[str] = field(default_factory=list)


@dataclass
class ExtremityAssignment:
    """Maps each wire extremity index to a robot name."""
    assignments: Dict[int, str] = field(default_factory=dict)

    def getRobotForExtremity(self, extremity_index: int) -> str:
        return self.assignments[extremity_index]


def splitPegsMiddleOut(
    ordered_peg_ids: List[str],
    peg_positions_world: Dict[str, Tuple[float, float, float]],
    robot_bases: Dict[str, Tuple[float, float, float]],
) -> MiddleOutAssignment:
    """Split an ordered peg list from the centre outward for two robots.

    The robot names are determined from *robot_bases*.  The robot whose
    base has the smaller X coordinate is labelled "left".

    For an odd number of pegs the centre peg is assigned to whichever
    robot's base is closer to it.
    """
    robot_names = sorted(
        robot_bases.keys(),
        key=lambda robot_name: robot_bases[robot_name][0],
    )
    left_robot = robot_names[0]
    right_robot = robot_names[1] if len(robot_names) > 1 else robot_names[0]

    if not ordered_peg_ids:
        return MiddleOutAssignment(
            left_robot_name=left_robot,
            right_robot_name=right_robot,
        )

    num_pegs = len(ordered_peg_ids)
    center_index = num_pegs // 2

    if num_pegs % 2 == 1:
        center_peg_id = ordered_peg_ids[center_index]
        center_position = peg_positions_world.get(center_peg_id, (0.0, 0.0, 0.0))

        distance_to_left = _euclideanDistanceXY(center_position, robot_bases[left_robot])
        distance_to_right = _euclideanDistanceXY(center_position, robot_bases[right_robot])

        if distance_to_left <= distance_to_right:
            left_sequence = list(reversed(ordered_peg_ids[: center_index + 1]))
            right_sequence = ordered_peg_ids[center_index + 1:]
        else:
            left_sequence = list(reversed(ordered_peg_ids[:center_index]))
            right_sequence = ordered_peg_ids[center_index:]
    else:
        left_sequence = list(reversed(ordered_peg_ids[:center_index]))
        right_sequence = ordered_peg_ids[center_index:]

    logger.info(
        "Middle-out split: left(%s)=%s, right(%s)=%s",
        left_robot, left_sequence, right_robot, right_sequence,
    )

    return MiddleOutAssignment(
        left_robot_name=left_robot,
        right_robot_name=right_robot,
        left_peg_sequence=left_sequence,
        right_peg_sequence=right_sequence,
    )


def assignExtremityToRobot(
    connector_positions: Dict[str, Tuple[float, float, float]],
    extremity_connector_ids: List[str],
    robot_bases: Dict[str, Tuple[float, float, float]],
) -> ExtremityAssignment:
    """Assign each wire extremity to the robot closest to its connector.

    Args:
        connector_positions: connector_occurrence_id -> world (x, y, z).
        extremity_connector_ids: ordered list (index 0, 1) of
            connector_occurrence_id for this wire's two ends.
        robot_bases: robot_name -> world (x, y, z).

    Returns:
        Mapping from extremity index (0 or 1) to robot_name.
    """
    assignments: Dict[int, str] = {}
    assigned_robots: set = set()

    scored: List[Tuple[float, int, str]] = []
    for extremity_index, connector_id in enumerate(extremity_connector_ids):
        connector_position = connector_positions.get(connector_id, (0.0, 0.0, 0.0))
        for robot_name, base_position in robot_bases.items():
            distance = _euclideanDistanceXY(connector_position, base_position)
            scored.append((distance, extremity_index, robot_name))

    scored.sort(key=lambda item: item[0])

    for _distance, extremity_index, robot_name in scored:
        if extremity_index in assignments:
            continue
        if robot_name in assigned_robots and len(extremity_connector_ids) <= len(robot_bases):
            continue
        assignments[extremity_index] = robot_name
        assigned_robots.add(robot_name)
        if len(assignments) == len(extremity_connector_ids):
            break

    for extremity_index in range(len(extremity_connector_ids)):
        if extremity_index not in assignments:
            fallback_robot = list(robot_bases.keys())[0]
            assignments[extremity_index] = fallback_robot

    logger.info("Extremity assignments: %s", assignments)
    return ExtremityAssignment(assignments=assignments)


def _euclideanDistanceXY(
    point_a: Tuple[float, float, float],
    point_b: Tuple[float, float, float],
) -> float:
    """XY-plane Euclidean distance between two 3D points."""
    return math.sqrt(
        (point_a[0] - point_b[0]) ** 2 + (point_a[1] - point_b[1]) ** 2
    )
