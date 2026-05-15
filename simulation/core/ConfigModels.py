"""
Typed configuration models for simulation package.
"""

from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, field_validator, model_validator


class WorldFrameConfig(BaseModel):
    units: Literal["meters"] = "meters"
    axis_up: Literal["z"] = "z"


class BoardConfig(BaseModel):
    length_m: float = Field(gt=0.0)
    width_m: float = Field(gt=0.0)
    thickness_m: float = Field(gt=0.0)
    position_m: Tuple[float, float, float]


class ViewerConfig(BaseModel):
    camera_name: str
    camera_position_m: Tuple[float, float, float]
    camera_quat_wxyz: Tuple[float, float, float, float]


class RobotLayoutConfig(BaseModel):
    base_to_base_translation_m: Tuple[float, float, float]
    base_to_base_rpy_rad: Tuple[float, float, float]


class StationConfig(BaseModel):
    world_frame: WorldFrameConfig
    board: BoardConfig
    viewer: ViewerConfig
    robot_layout: RobotLayoutConfig


class RobotDefinition(BaseModel):
    robot_name: str
    base_position_m: Tuple[float, float, float]
    base_quat_wxyz: Tuple[float, float, float, float]
    joint_names: List[str] = Field(min_length=6, max_length=6)
    joint_limits_rad: List[Tuple[float, float]] = Field(min_length=6, max_length=6)
    home_joint_angles_rad: List[float] = Field(min_length=6, max_length=6)

    @field_validator("joint_limits_rad")
    @classmethod
    def validate_joint_limits(cls, joint_limits_rad: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        for lower_limit, upper_limit in joint_limits_rad:
            if lower_limit >= upper_limit:
                raise ValueError("joint lower limit must be smaller than upper limit")
        return joint_limits_rad


class AssetSourceConfig(BaseModel):
    ur10e_model_source: str
    ur10e_mjcf_path: str = ""
    use_simplified_kinematic_visual: bool = True


class RobotsConfig(BaseModel):
    robots: List[RobotDefinition] = Field(min_length=2)
    asset_sources: AssetSourceConfig


class GripperDefinition(BaseModel):
    robot_name: str
    open_command_value: float
    close_command_value: float
    default_grip_force_n: float = Field(gt=0.0)
    finger_max_width_m: float = Field(gt=0.0)


class GrippersConfig(BaseModel):
    gripper_type: Literal["robotiq_2f85"] = "robotiq_2f85"
    grippers: List[GripperDefinition] = Field(min_length=2)


class PegShapeConfig(BaseModel):
    peg_shape_type: Literal["fork_standard", "round_pin", "t_peg"] = "fork_standard"
    post_radius_m: float = Field(gt=0.0)
    post_height_m: float = Field(gt=0.0)
    prong_length_m: float = Field(default=0.0, ge=0.0)
    prong_width_m: float = Field(default=0.0, ge=0.0)
    prong_gap_m: float = Field(default=0.0, ge=0.0)
    crossbar_length_m: float = Field(default=0.0, ge=0.0)
    crossbar_width_m: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def validate_shape_specific_fields(self) -> "PegShapeConfig":
        if self.peg_shape_type == "fork_standard":
            if self.prong_length_m <= 0.0 or self.prong_width_m <= 0.0 or self.prong_gap_m <= 0.0:
                raise ValueError("fork_standard requires prong_length_m, prong_width_m, and prong_gap_m > 0")
        elif self.peg_shape_type == "t_peg":
            if self.crossbar_length_m <= 0.0 or self.crossbar_width_m <= 0.0:
                raise ValueError("t_peg requires crossbar_length_m and crossbar_width_m > 0")
        return self


class PegInstanceConfig(BaseModel):
    object_id: str
    peg_type: str
    position_m: Tuple[float, float, float]
    orientation_quat_wxyz: Tuple[float, float, float, float]
    color_rgba: Tuple[float, float, float, float] = (0.72, 0.72, 0.74, 1.0)


class ConnectorHolderConfig(BaseModel):
    object_id: str
    position_m: Tuple[float, float, float]
    orientation_quat_wxyz: Tuple[float, float, float, float]
    size_m: Tuple[float, float, float]
    color_rgba: Tuple[float, float, float, float] = (0.2, 0.42, 0.86, 1.0)


class ConnectorPlugConfig(BaseModel):
    object_id: str
    position_m: Tuple[float, float, float]
    orientation_quat_wxyz: Tuple[float, float, float, float]
    plug_radius_m: float = Field(gt=0.0)
    plug_length_m: float = Field(gt=0.0)
    color_rgba: Tuple[float, float, float, float] = (0.85, 0.35, 0.1, 1.0)


class SceneObjectsConfig(BaseModel):
    peg_catalog: Dict[str, PegShapeConfig]
    peg_instances: List[PegInstanceConfig]
    connector_holder_instances: List[ConnectorHolderConfig]
    connector_plug_instances: List[ConnectorPlugConfig] = Field(default_factory=list)


# ============================================================================
# Board Setup Config -- pickup positions, grasp orientations, approach offsets
# ============================================================================

class ObjectPickupConfig(BaseModel):
    """Per-instance pickup position for a peg or connector holder."""
    object_id: str
    object_type: Literal["peg", "connector_holder"]
    pickup_position_m: Tuple[float, float, float]


class GraspOrientationConfig(BaseModel):
    """Per object-type grasp orientation and TCP offset."""
    object_type: Literal["peg", "connector_holder"]
    grasp_quat_wxyz: Tuple[float, float, float, float]
    grasp_offset_m: Tuple[float, float, float] = (0.0, 0.0, 0.0)


class AxisMappingConfig(BaseModel):
    """Configurable mapping from layout 2D axes to world XY axes."""
    layout_x_to_world: str = "x"
    layout_y_to_world: str = "y"


class BoardSetupConfig(BaseModel):
    """Top-level config for the board setup simulation phase."""
    config_version: int = 1
    approach_offset_m: float = Field(default=0.05, gt=0.0)
    retreat_offset_m: float = Field(default=0.05, gt=0.0)
    transport_height_offset_m: float = Field(default=0.30, gt=0.0)
    board_center_offset_mm: Tuple[float, float] = (0.0, 0.0)
    intersection_offset_mm: float = Field(default=0.0, ge=0.0)
    random_orientation_seed: int = 42
    gripper_open_value: float = Field(default=0.0, ge=0.0)
    gripper_close_value: float = Field(default=255.0, ge=0.0)
    gripper_settle_s: float = Field(default=0.3, ge=0.0)
    clearance_num_samples: int = Field(default=12, ge=1)
    pickup_clearance_radius_m: float = Field(default=0.45, gt=0.0)
    axis_mapping: AxisMappingConfig = Field(default_factory=AxisMappingConfig)
    grasp_orientations: List[GraspOrientationConfig] = Field(default_factory=list)
    pickup_positions: List[ObjectPickupConfig] = Field(default_factory=list)


# ============================================================================
# Wire Routing Config -- pickup positions, force thresholds, height policy
# ============================================================================

class WireEndPickupConfig(BaseModel):
    """Per-wire-end pickup position and crimp orientation."""
    wire_occurrence_id: str
    extremity_index: int = Field(ge=0, le=1)
    pickup_position_m: Tuple[float, float, float]
    crimp_orientation_deg: float = 0.0
    anchor_position_m: Optional[Tuple[float, float, float]] = None
    cable_axis_orientation_deg: float = 0.0


class PullTestThresholdConfig(BaseModel):
    """Pull-test acceptance force keyed by wire cross-section range."""
    min_cross_section_mm2: float = Field(ge=0.0)
    max_cross_section_mm2: float = Field(gt=0.0)
    threshold_force_n: float = Field(gt=0.0)


class WireRoutingConfig(BaseModel):
    """Top-level config for the wire routing simulation phase."""
    wire_end_pickups: List[WireEndPickupConfig] = Field(default_factory=list)
    pull_test_thresholds: List[PullTestThresholdConfig] = Field(default_factory=list)
    peg_pass_height_offset_m: float = Field(default=0.005, ge=0.0)
    between_peg_height_offset_m: float = Field(default=0.05, gt=0.0)
    insertion_pre_adjustment_m: float = Field(default=0.002, ge=0.0)
    regrasp_retract_m: float = Field(default=0.03, gt=0.0)
    gripper_open_value: float = Field(default=0.0, ge=0.0)
    gripper_close_value: float = Field(default=255.0, ge=0.0)
    gripper_settle_s: float = Field(default=0.3, ge=0.0)
    wire_color_map: Dict[str, Tuple[float, float, float, float]] = Field(
        default_factory=lambda: {
            "RD": (0.9, 0.1, 0.1, 1.0),
            "BU": (0.1, 0.3, 0.9, 1.0),
            "BK": (0.1, 0.1, 0.1, 1.0),
            "WH": (0.95, 0.95, 0.95, 1.0),
            "GN": (0.1, 0.7, 0.2, 1.0),
            "YE": (0.9, 0.85, 0.1, 1.0),
            "OG": (0.95, 0.55, 0.1, 1.0),
            "VT": (0.6, 0.1, 0.8, 1.0),
            "BN": (0.5, 0.3, 0.1, 1.0),
            "GY": (0.5, 0.5, 0.5, 1.0),
        },
    )
    default_wire_color: Tuple[float, float, float, float] = (0.95, 0.55, 0.1, 1.0)
    insertion_approach_distance_m: float = Field(default=0.08, gt=0.0)
    peg_slot_offset_m: float = Field(default=0.015, ge=0.0)
    peg_clearance_m: float = Field(default=0.04, ge=0.0)
    cable_hang_height_m: float = Field(default=0.30, gt=0.0)

