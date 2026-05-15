"""
Reactive step-by-step execution model for board setup.

Unlike the batch executor (BoardSetupExecutor) that pre-queues all motions
upfront, the ReactiveExecutor plans and executes one step at a time.
Before each step it queries the OrientationSource for the actual object
orientation, recomputing the motion plan if the measured angle differs
from the pre-planned one.

This matches the real-robot workflow where a camera provides orientation
feedback between steps.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from simulation.core.CoordinateTransform import WorldToRobotBaseTransform
from simulation.core.RotationUtils import (
    composeZRotation,
    normaliseAngleDeg,
    quatWxyzToRotationMatrix,
    rotationMatrixToQuatWxyz,
)
from simulation.planning.BoardSetupExecutor import OverlayEvent
from simulation.planning.GraspOrientationPlanner import GraspOrientationPlanner
from simulation.planning.LayoutToSimulationBridge import BoardSetupMotionPlan
from simulation.planning.OrientationSource import OrientationSource

logger = logging.getLogger(__name__)

ORIENTATION_REPLAN_THRESHOLD_DEG = 0.5


class ProcessStepResult(BaseModel):
    """Result of executing a single process step."""
    success: bool
    step_id: str
    error_message: Optional[str] = None
    overlay_events: List[OverlayEvent] = Field(default_factory=list)

    model_config = ConfigDict(arbitrary_types_allowed=True)


@runtime_checkable
class ProcessStepExecutor(Protocol):
    """Protocol for executing a single board-setup motion plan step."""

    def executeStep(
        self,
        plan: BoardSetupMotionPlan,
        last_joint_target: Dict[str, List[float]],
        overlay_events: List[OverlayEvent],
        step_label: str,
    ) -> bool: ...


class ReactiveExecutor:
    """Executes board setup steps one at a time with live orientation feedback.

    Recomputes poses when the orientation source reports an angle differing
    from the pre-planned one by more than ORIENTATION_REPLAN_THRESHOLD_DEG.
    """

    def __init__(
        self,
        step_executor: ProcessStepExecutor,
        orientation_source: OrientationSource,
        robot_base_transforms: Dict[str, WorldToRobotBaseTransform],
        grasp_planner: GraspOrientationPlanner,
    ) -> None:
        self._step_executor = step_executor
        self._orientation_source = orientation_source
        self._robot_base_transforms = robot_base_transforms
        self._grasp_planner = grasp_planner

    def executeNextStep(
        self,
        motion_plan: BoardSetupMotionPlan,
        last_joint_target: Dict[str, List[float]],
        overlay_events: List[OverlayEvent],
        step_label: str = "",
    ) -> ProcessStepResult:
        """Execute one step, re-planning if orientation has changed."""
        actual_orientation = self._orientation_source.getObjectOrientation(
            motion_plan.object_id,
        )

        orientation_delta_deg = abs(
            normaliseAngleDeg(actual_orientation - motion_plan.pickup_orientation_deg),
        )
        if orientation_delta_deg > ORIENTATION_REPLAN_THRESHOLD_DEG:
            logger.info(
                "Orientation changed for %s: planned=%.1f, actual=%.1f, delta=%.2f -- replanning",
                motion_plan.object_id,
                motion_plan.pickup_orientation_deg,
                actual_orientation,
                orientation_delta_deg,
            )
            motion_plan = self._recomputePosesForOrientation(
                motion_plan, actual_orientation,
            )

        success = self._step_executor.executeStep(
            motion_plan, last_joint_target, overlay_events, step_label,
        )

        return ProcessStepResult(
            success=success,
            step_id=motion_plan.step_id,
            error_message=None if success else f"Step {motion_plan.step_id} failed",
            overlay_events=overlay_events,
        )

    def _recomputePosesForOrientation(
        self,
        plan: BoardSetupMotionPlan,
        actual_orientation_deg: float,
    ) -> BoardSetupMotionPlan:
        """Rebuild the 8-pose motion plan with the actual measured orientation.

        Uses BoardToWorldTransform, WorldToRobotBaseTransform, and
        GraspOrientationPlanner to recompute all pickup/placement poses.
        """
        robot_base_tf = self._robot_base_transforms.get(plan.robot_name)
        if robot_base_tf is None:
            logger.warning(
                "Missing robot base transform for '%s'; cannot replan orientation.",
                plan.robot_name,
            )
            return plan

        pickup_robot_quat = tuple(plan.pickup_pose.quat_wxyz)
        pickup_robot_rot = quatWxyzToRotationMatrix(*pickup_robot_quat)
        pickup_world_rot = robot_base_tf.rotation_matrix @ pickup_robot_rot
        pickup_world_quat = rotationMatrixToQuatWxyz(pickup_world_rot)

        # Recover the base grasp orientation by removing the planned world-Z pickup rotation.
        base_grasp_quat = composeZRotation(
            pickup_world_quat,
            -plan.pickup_orientation_deg,
        )

        grasp_plan = self._grasp_planner.computeGraspPlan(
            base_grasp_quat_wxyz=base_grasp_quat,
            pickup_orientation_deg=actual_orientation_deg,
            placement_orientation_deg=plan.placement_orientation_deg,
        )

        pickup_quat = grasp_plan.pickup_grasp_quat_wxyz
        placement_quat = grasp_plan.placement_grasp_quat_wxyz
        if not grasp_plan.is_feasible:
            pickup_quat = placement_quat

        pickup_world = plan.pickup_world_m
        placement_world = plan.placement_world_m

        pickup_approach_world = robot_base_tf.inverseTransformPosition(tuple(plan.pickup_approach_pose.position_m))
        pickup_retreat_world = robot_base_tf.inverseTransformPosition(tuple(plan.pickup_retreat_pose.position_m))
        pickup_transport_world = robot_base_tf.inverseTransformPosition(tuple(plan.pickup_transport_pose.position_m))
        placement_approach_world = robot_base_tf.inverseTransformPosition(tuple(plan.placement_approach_pose.position_m))
        placement_retreat_world = robot_base_tf.inverseTransformPosition(tuple(plan.placement_retreat_pose.position_m))
        placement_transport_world = robot_base_tf.inverseTransformPosition(tuple(plan.placement_transport_pose.position_m))

        updated_plan = BoardSetupMotionPlan(
            step_id=plan.step_id,
            object_id=plan.object_id,
            object_type=plan.object_type,
            robot_name=plan.robot_name,
            pickup_orientation_deg=actual_orientation_deg,
            placement_orientation_deg=plan.placement_orientation_deg,
            pickup_world_m=plan.pickup_world_m,
            placement_world_m=plan.placement_world_m,
            pickup_pose=robot_base_tf.transformPose(pickup_world, pickup_quat),
            pickup_approach_pose=robot_base_tf.transformPose(pickup_approach_world, pickup_quat),
            pickup_retreat_pose=robot_base_tf.transformPose(pickup_retreat_world, pickup_quat),
            pickup_transport_pose=robot_base_tf.transformPose(pickup_transport_world, pickup_quat),
            placement_pose=robot_base_tf.transformPose(placement_world, placement_quat),
            placement_approach_pose=robot_base_tf.transformPose(placement_approach_world, placement_quat),
            placement_retreat_pose=robot_base_tf.transformPose(placement_retreat_world, placement_quat),
            placement_transport_pose=robot_base_tf.transformPose(placement_transport_world, placement_quat),
        )

        return updated_plan
