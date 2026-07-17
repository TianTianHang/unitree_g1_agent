from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


FloatArray = NDArray[np.float32]


@dataclass(frozen=True)
class RobotState:
    anchor_position_w: FloatArray
    anchor_orientation_wxyz: FloatArray
    linear_velocity_w: FloatArray
    angular_velocity_b: FloatArray
    joint_position_unitree: FloatArray
    joint_velocity_unitree: FloatArray


@dataclass(frozen=True)
class MotorCommand:
    q: FloatArray
    dq: FloatArray
    tau: FloatArray
    kp: FloatArray
    kd: FloatArray


def _quat_conjugate(q: FloatArray) -> FloatArray:
    return np.array([q[0], -q[1], -q[2], -q[3]], dtype=np.float32)


def _quat_multiply(a: FloatArray, b: FloatArray) -> FloatArray:
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return np.array(
        [
            aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
        ],
        dtype=np.float32,
    )


def _quat_rotate_inverse(q: FloatArray, vector: FloatArray) -> FloatArray:
    pure = np.array([0.0, *vector], dtype=np.float32)
    return _quat_multiply(_quat_multiply(_quat_conjugate(q), pure), q)[1:]


def _matrix_from_quat(q: FloatArray) -> FloatArray:
    w, x, y, z = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float32,
    )


def build_observation(
    future_joint_position: FloatArray,
    future_joint_velocity: FloatArray,
    future_anchor_position_w: FloatArray,
    future_anchor_orientation_wxyz: FloatArray,
    state: RobotState,
    last_action_isaaclab: FloatArray,
    *,
    default_q_unitree: FloatArray,
    unitree_to_isaaclab: tuple[int, ...],
) -> FloatArray:
    robot_q_inv = _quat_conjugate(state.anchor_orientation_wxyz)
    relative_positions = np.stack(
        [_quat_rotate_inverse(state.anchor_orientation_wxyz, item - state.anchor_position_w) for item in future_anchor_position_w]
    )
    relative_orientations = np.stack(
        [_matrix_from_quat(_quat_multiply(robot_q_inv, item))[:, :2].reshape(-1) for item in future_anchor_orientation_wxyz]
    )
    projected_gravity = _quat_rotate_inverse(
        state.anchor_orientation_wxyz, np.array([0.0, 0.0, -1.0], dtype=np.float32)
    )
    base_linear_velocity = _quat_rotate_inverse(state.anchor_orientation_wxyz, state.linear_velocity_w)
    index = np.asarray(unitree_to_isaaclab, dtype=np.int64)
    joint_position = (state.joint_position_unitree - default_q_unitree)[index]
    joint_velocity = state.joint_velocity_unitree[index]
    observation = np.concatenate(
        (
            future_joint_position.reshape(-1),
            future_joint_velocity.reshape(-1),
            relative_positions.reshape(-1),
            relative_orientations.reshape(-1),
            projected_gravity,
            base_linear_velocity,
            state.angular_velocity_b,
            joint_position,
            joint_velocity,
            last_action_isaaclab,
        )
    ).astype(np.float32, copy=False)
    if observation.shape != (431,) or not np.isfinite(observation).all():
        raise ValueError("tracker observation must contain 431 finite values")
    return observation


def decode_action(
    raw_action_isaaclab: FloatArray,
    *,
    isaaclab_to_unitree: tuple[int, ...],
    default_q_unitree: FloatArray,
    action_scale_unitree: FloatArray,
    kp_unitree: FloatArray,
    kd_unitree: FloatArray,
) -> MotorCommand:
    if raw_action_isaaclab.shape != (29,) or not np.isfinite(raw_action_isaaclab).all():
        raise ValueError("policy action must contain 29 finite values")
    raw_unitree = np.empty(29, dtype=np.float32)
    raw_unitree[np.asarray(isaaclab_to_unitree, dtype=np.int64)] = raw_action_isaaclab
    zeros = np.zeros(29, dtype=np.float32)
    return MotorCommand(
        q=default_q_unitree + raw_unitree * action_scale_unitree,
        dq=zeros.copy(),
        tau=zeros.copy(),
        kp=np.asarray(kp_unitree, dtype=np.float32).copy(),
        kd=np.asarray(kd_unitree, dtype=np.float32).copy(),
    )
