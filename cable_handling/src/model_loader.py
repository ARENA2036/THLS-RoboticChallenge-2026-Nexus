"""
Model loader for dual robot scene with programmatic robot attachment.

Uses MuJoCo's MjSpec API to attach the same robot assembly twice
with different prefixes (left/ and right/).
"""

import os
from typing import List, Optional

import mujoco


def load_dual_robot_scene(
    scene_path: str,
    robot_path: str,
    left_mount_pose: Optional[List[float]] = None,
    right_mount_pose: Optional[List[float]] = None,
    peg_visuals: Optional[List[dict]] = None,
    holder_visuals: Optional[List[dict]] = None,
    plug_visuals: Optional[List[dict]] = None,
) -> mujoco.MjModel:
    """
    Load the dual robot scene by programmatically attaching robots.
    
    Args:
        scene_path: Path to the base scene XML (dual_ur10e_scene.xml)
        robot_path: Path to the robot assembly XML (robot_assembly.xml)
        
    Returns:
        Compiled MuJoCo model with both robots attached
    """
    original_cwd = os.getcwd()
    scene_directory = os.path.dirname(os.path.abspath(scene_path))
    os.chdir(scene_directory)
    try:
        # Load scene spec
        scene_spec = mujoco.MjSpec.from_file(scene_path)
    
        # Find mount frames
        left_frame = None
        right_frame = None
        for frame in scene_spec.worldbody.frames:
            if frame.name == "left_robot_mount":
                left_frame = frame
            elif frame.name == "right_robot_mount":
                right_frame = frame
    
        if left_frame is None or right_frame is None:
            raise ValueError("Could not find robot mount frames in scene")
    
        # Optionally override mount frame poses from runtime config
        if left_mount_pose is not None:
            left_frame.pos = left_mount_pose[:3]
            left_frame.quat = left_mount_pose[3:]
        if right_mount_pose is not None:
            right_frame.pos = right_mount_pose[:3]
            right_frame.quat = right_mount_pose[3:]

        # Load robot assembly and attach left robot
        left_robot_spec = mujoco.MjSpec.from_file(robot_path)
        left_robot_body = left_robot_spec.worldbody.first_body()
        left_frame.attach_body(left_robot_body, "left/", "")
    
        # Load robot assembly again and attach right robot
        right_robot_spec = mujoco.MjSpec.from_file(robot_path)
        right_robot_body = right_robot_spec.worldbody.first_body()
        right_frame.attach_body(right_robot_body, "right/", "")
    
        # Add contact exclusions for both grippers
        _add_contact_exclusions(scene_spec, "left/")
        _add_contact_exclusions(scene_spec, "right/")
    
        # Add tendons for gripper coupling
        _add_gripper_tendons(scene_spec, "left/")
        _add_gripper_tendons(scene_spec, "right/")
    
        # Add equality constraints for grippers
        _add_gripper_equality(scene_spec, "left/")
        _add_gripper_equality(scene_spec, "right/")
    
        # Add actuators for both robots
        _add_robot_actuators(scene_spec, "left/")
        _add_robot_actuators(scene_spec, "right/")
    
        # Add sensors for both robots
        _add_robot_sensors(scene_spec, "left/")
        _add_robot_sensors(scene_spec, "right/")
    
        # Add non-physical scene visuals (pegs, connector holders, plugs)
        _add_peg_visuals(scene_spec, peg_visuals or [])
        _add_holder_visuals(scene_spec, holder_visuals or [])
        _add_plug_visuals(scene_spec, plug_visuals or [])
    
        # Add keyframe
        _add_keyframe(scene_spec)
    
        # Compile model
        model = scene_spec.compile()
    
        # Fix equality constraint data after compilation
        # MjSpec doesn't properly set data values, so we set them on compiled model
        return model
    finally:
        os.chdir(original_cwd)


def _add_contact_exclusions(spec: mujoco.MjSpec, prefix: str):
    """Add contact exclusions for gripper parts."""
    exclusions = [
        ("base", "shoulder_link"),
        ("gripper_base", "left_driver"),
        ("gripper_base", "right_driver"),
        ("gripper_base", "left_spring_link"),
        ("gripper_base", "right_spring_link"),
        ("right_coupler", "right_follower"),
        ("left_coupler", "left_follower"),
    ]
    for body1, body2 in exclusions:
        exclude = spec.add_exclude()
        exclude.name = f"{prefix}exclude_{body1}_{body2}"
        exclude.bodyname1 = f"{prefix}{body1}"
        exclude.bodyname2 = f"{prefix}{body2}"


def _add_gripper_tendons(spec: mujoco.MjSpec, prefix: str):
    """Add tendon for gripper finger coupling."""
    tendon = spec.add_tendon()
    tendon.name = f"{prefix}gripper_split"
    
    # Add joint wraps using wrap_joint(joint_name, coefficient)
    tendon.wrap_joint(f"{prefix}right_driver_joint", 0.485)
    tendon.wrap_joint(f"{prefix}left_driver_joint", 0.485)


def _add_gripper_equality(spec: mujoco.MjSpec, prefix: str):
    """Add equality constraints for gripper mechanism."""
    # Connect constraints for follower-coupler pairs
    for side in ["right", "left"]:
        connect = spec.add_equality()
        connect.name = f"{prefix}{side}_follower_coupler"
        connect.type = mujoco.mjtEq.mjEQ_CONNECT
        connect.objtype = mujoco.mjtObj.mjOBJ_BODY
        connect.name1 = f"{prefix}{side}_follower"
        connect.name2 = f"{prefix}{side}_coupler"
        # data for connect: anchor[3], then padding
        connect.data = [-0.0179014, -0.00651468, 0.0044, 0, 0, 0, 0, 0, 0, 0, 0]
        connect.solref = [0.005, 1]
        connect.solimp = [0.95, 0.99, 0.001, 0, 0]
    
    # Joint equality for synchronized driver joints
    joint_eq = spec.add_equality()
    joint_eq.name = f"{prefix}driver_sync"
    joint_eq.type = mujoco.mjtEq.mjEQ_JOINT
    joint_eq.objtype = mujoco.mjtObj.mjOBJ_JOINT
    joint_eq.name1 = f"{prefix}right_driver_joint"
    joint_eq.name2 = f"{prefix}left_driver_joint"
    # data for joint equality: polycoef[5], then padding
    joint_eq.data = [0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    joint_eq.solref = [0.005, 1]
    joint_eq.solimp = [0.95, 0.99, 0.001, 0, 0]


def _add_robot_actuators(spec: mujoco.MjSpec, prefix: str):
    """Add actuators for robot joints and gripper."""
    # Robot joint actuators
    joint_configs = [
        ("shoulder_pan", "shoulder_pan_joint", "size4"),
        ("shoulder_lift", "shoulder_lift_joint", "size4"),
        ("elbow", "elbow_joint", "size3_limited"),
        ("wrist_1", "wrist_1_joint", "size2"),
        ("wrist_2", "wrist_2_joint", "size2"),
        ("wrist_3", "wrist_3_joint", "size2"),
    ]
    
    for act_name, joint_name, size_class in joint_configs:
        actuator = spec.add_actuator()
        actuator.name = f"{prefix}{act_name}"
        actuator.trntype = mujoco.mjtTrn.mjTRN_JOINT
        actuator.target = f"{prefix}{joint_name}"
        actuator.biastype = mujoco.mjtBias.mjBIAS_AFFINE
        actuator.ctrllimited = True
        actuator.ctrlrange = [-6.2831, 6.2831]
        actuator.gainprm = [5000, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        actuator.biasprm = [0, -5000, -500, 0, 0, 0, 0, 0, 0, 0]
        actuator.forcelimited = True
        
        if size_class == "size4":
            actuator.forcerange = [-330, 330]
        elif size_class == "size3_limited":
            actuator.forcerange = [-150, 150]
            actuator.ctrlrange = [-3.1415, 3.1415]
        else:  # size2
            actuator.forcerange = [-56, 56]
    
    # Gripper actuator (tendon-based)
    gripper_act = spec.add_actuator()
    gripper_act.name = f"{prefix}gripper"
    gripper_act.trntype = mujoco.mjtTrn.mjTRN_TENDON
    gripper_act.target = f"{prefix}gripper_split"
    gripper_act.biastype = mujoco.mjtBias.mjBIAS_AFFINE
    gripper_act.ctrllimited = True
    gripper_act.ctrlrange = [0, 255]
    gripper_act.forcelimited = True
    gripper_act.forcerange = [-5, 5]
    gripper_act.gainprm = [0.3137255, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    gripper_act.biasprm = [0, -100, -10, 0, 0, 0, 0, 0, 0, 0]


def _add_robot_sensors(spec: mujoco.MjSpec, prefix: str):
    """Add sensors for robot state feedback."""
    # Force/torque sensor
    force_sensor = spec.add_sensor()
    force_sensor.name = f"{prefix}fts_force"
    force_sensor.type = mujoco.mjtSensor.mjSENS_FORCE
    force_sensor.objtype = mujoco.mjtObj.mjOBJ_SITE
    force_sensor.objname = f"{prefix}fts_site"
    
    torque_sensor = spec.add_sensor()
    torque_sensor.name = f"{prefix}fts_torque"
    torque_sensor.type = mujoco.mjtSensor.mjSENS_TORQUE
    torque_sensor.objtype = mujoco.mjtObj.mjOBJ_SITE
    torque_sensor.objname = f"{prefix}fts_site"
    
    # Joint position sensors
    joint_names = [
        "shoulder_pan_joint", "shoulder_lift_joint", "elbow_joint",
        "wrist_1_joint", "wrist_2_joint", "wrist_3_joint"
    ]
    for joint_name in joint_names:
        sensor = spec.add_sensor()
        sensor.name = f"{prefix}{joint_name.replace('_joint', '')}_pos"
        sensor.type = mujoco.mjtSensor.mjSENS_JOINTPOS
        sensor.objtype = mujoco.mjtObj.mjOBJ_JOINT
        sensor.objname = f"{prefix}{joint_name}"
    
    # Gripper position sensor
    gripper_sensor = spec.add_sensor()
    gripper_sensor.name = f"{prefix}gripper_pos"
    gripper_sensor.type = mujoco.mjtSensor.mjSENS_JOINTPOS
    gripper_sensor.objtype = mujoco.mjtObj.mjOBJ_JOINT
    gripper_sensor.objname = f"{prefix}left_driver_joint"


def _add_peg_visuals(spec: mujoco.MjSpec, peg_visuals: List[dict]) -> None:
    """Add peg visuals to the world body (fork_standard, round_pin, or t_peg)."""
    for peg_definition in peg_visuals:
        body = spec.worldbody.add_body()
        body.name = peg_definition["object_id"]
        body.pos = peg_definition["position_m"]
        body.quat = peg_definition["orientation_quat_wxyz"]

        post_color = list(peg_definition.get("color_rgba", [0.72, 0.72, 0.74, 1.0]))
        accent_color = [max(0.0, channel - 0.04) for channel in post_color[:3]] + [post_color[3]]
        shape_type = peg_definition.get("peg_shape_type", "fork_standard")

        post_geom = body.add_geom()
        post_geom.type = mujoco.mjtGeom.mjGEOM_CYLINDER
        post_geom.size = [peg_definition["post_radius_m"], peg_definition["post_height_m"] / 2.0, 0.0]
        post_geom.pos = [0.0, 0.0, peg_definition["post_height_m"] / 2.0]
        post_geom.rgba = post_color

        if shape_type == "fork_standard":
            prong_offset = peg_definition["prong_gap_m"] / 2.0 + peg_definition["prong_width_m"] / 2.0
            for direction in [-1.0, 1.0]:
                prong_geom = body.add_geom()
                prong_geom.type = mujoco.mjtGeom.mjGEOM_BOX
                prong_geom.size = [
                    peg_definition["prong_length_m"] / 2.0,
                    peg_definition["prong_width_m"] / 2.0,
                    peg_definition["prong_width_m"] / 2.0,
                ]
                prong_geom.pos = [
                    0.0,
                    direction * prong_offset,
                    peg_definition["post_height_m"] + peg_definition["prong_width_m"] / 2.0,
                ]
                prong_geom.rgba = accent_color

        elif shape_type == "t_peg":
            crossbar_length = peg_definition.get("crossbar_length_m", 0.02)
            crossbar_width = peg_definition.get("crossbar_width_m", 0.004)
            crossbar_geom = body.add_geom()
            crossbar_geom.type = mujoco.mjtGeom.mjGEOM_BOX
            crossbar_geom.size = [
                crossbar_length / 2.0,
                crossbar_width / 2.0,
                crossbar_width / 2.0,
            ]
            crossbar_geom.pos = [
                0.0,
                0.0,
                peg_definition["post_height_m"] + crossbar_width / 2.0,
            ]
            crossbar_geom.rgba = accent_color


def _add_holder_visuals(spec: mujoco.MjSpec, holder_visuals: List[dict]) -> None:
    """Add connector-holder visuals to the world body."""
    for holder_definition in holder_visuals:
        body = spec.worldbody.add_body()
        body.name = holder_definition["object_id"]
        body.pos = holder_definition["position_m"]
        body.quat = holder_definition["orientation_quat_wxyz"]

        holder_geom = body.add_geom()
        holder_geom.type = mujoco.mjtGeom.mjGEOM_BOX
        holder_geom.size = [
            holder_definition["size_m"][0] / 2.0,
            holder_definition["size_m"][1] / 2.0,
            holder_definition["size_m"][2] / 2.0,
        ]
        holder_geom.rgba = list(holder_definition.get("color_rgba", [0.2, 0.42, 0.86, 1.0]))


def _add_plug_visuals(spec: mujoco.MjSpec, plug_visuals: List[dict]) -> None:
    """Add connector-plug cylinder visuals to the world body."""
    for plug_definition in plug_visuals:
        body = spec.worldbody.add_body()
        body.name = plug_definition["object_id"]
        body.pos = plug_definition["position_m"]
        body.quat = plug_definition["orientation_quat_wxyz"]

        plug_geom = body.add_geom()
        plug_geom.type = mujoco.mjtGeom.mjGEOM_CYLINDER
        plug_geom.size = [
            plug_definition["plug_radius_m"],
            plug_definition["plug_length_m"] / 2.0,
            0.0,
        ]
        plug_geom.pos = [0.0, 0.0, plug_definition["plug_length_m"] / 2.0]
        plug_geom.rgba = list(plug_definition.get("color_rgba", [0.85, 0.35, 0.1, 1.0]))


def _add_keyframe(spec: mujoco.MjSpec):
    """Add home keyframe for initial robot positions."""
    key = spec.add_key()
    key.name = "home"
    
    # Note: qpos and ctrl will be set after compilation based on joint/actuator order
    # For now, we'll handle this in the simulation by setting positions directly


def get_model_paths(models_dir: Optional[str] = None) -> tuple:
    """
    Get paths to scene and robot XML files.
    
    Args:
        models_dir: Optional path to models directory. If None, uses default.
        
    Returns:
        Tuple of (scene_path, robot_path)
    """
    if models_dir is None:
        # Assume running from project root or src directory
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        models_dir = os.path.join(base_dir, "models")
    
    scene_path = os.path.join(models_dir, "dual_ur10e_scene.xml")
    robot_path = os.path.join(models_dir, "robot_assembly.xml")
    
    return scene_path, robot_path


if __name__ == "__main__":
    # Test the loader
    scene_path, robot_path = get_model_paths()
    print(f"Loading scene from: {scene_path}")
    print(f"Loading robot from: {robot_path}")
    
    model = load_dual_robot_scene(scene_path, robot_path)
    print(f"\nModel loaded successfully!")
    print(f"  Bodies: {model.nbody}")
    print(f"  Joints: {model.njnt}")
    print(f"  Actuators: {model.nu}")
    print(f"  Sensors: {model.nsensor}")
    
    # List some bodies
    print("\nBody names:")
    for i in range(min(model.nbody, 20)):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, i)
        print(f"  {i}: {name}")
    
    print("\nActuator names:")
    for i in range(model.nu):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_ACTUATOR, i)
        print(f"  {i}: {name}")
