from __future__ import annotations

import time

import numpy as np
import rclpy
from builtin_interfaces.msg import Duration
from g1_agent_msgs.msg import (
    JointMotorCommand,
    LowLevelCommandCandidate,
    LowLevelControlLease,
    MotionReferenceSegment,
    TextOpTrackerStatus,
)
from nav_msgs.msg import Odometry
from rclpy.node import Node
from unitree_hg.msg import LowState

from .manifest import load_manifest
from .onnx_policy import load_onnx_policy
from .reference import MotionReferenceSegment as Segment
from .tracker import RobotState
from .tracker_engine import ReferencePending, TrackerEngine


class TextOpTrackerNode(Node):
    def __init__(self) -> None:
        super().__init__("textop_tracker_node")
        for name, default in (
            ("manifest_path", ""), ("onnx_providers", ["CPUExecutionProvider"]),
            ("reference_topic", "/g1/textop/reference"), ("lease_topic", "/g1/low_level/lease"),
            ("candidate_topic", "/g1/low_level/candidate"), ("lowstate_topic", "/lowstate"),
            ("odometry_topic", "/odom"), ("lowstate_timeout", 0.1), ("odometry_timeout", 0.1),
            ("candidate_valid_for", 0.04), ("tracker_status_topic", "/g1/textop/tracker_status"),
        ):
            self.declare_parameter(name, default)
        manifest_path = self.get_parameter("manifest_path").value
        if not manifest_path:
            raise RuntimeError("manifest_path is required")
        self.manifest = load_manifest(manifest_path)
        policy = load_onnx_policy(
            str(self.manifest.policy.path), input_name=self.manifest.policy.input_name,
            output_name=self.manifest.policy.output_name, providers=list(self.get_parameter("onnx_providers").value),
        )
        self.engine = TrackerEngine(self.manifest, policy)
        self.lease: LowLevelControlLease | None = None
        self.lowstate: LowState | None = None
        self.odometry: Odometry | None = None
        self.lowstate_at = 0.0
        self.odometry_at = 0.0
        self.sequence = 0
        self.publisher = self.create_publisher(
            LowLevelCommandCandidate, self.get_parameter("candidate_topic").value, 10
        )
        self.status_publisher = self.create_publisher(
            TextOpTrackerStatus, self.get_parameter("tracker_status_topic").value, 10
        )
        self.create_subscription(MotionReferenceSegment, self.get_parameter("reference_topic").value, self._reference, 10)
        self.create_subscription(LowLevelControlLease, self.get_parameter("lease_topic").value, self._lease, 10)
        self.create_subscription(LowState, self.get_parameter("lowstate_topic").value, self._lowstate, 10)
        self.create_subscription(Odometry, self.get_parameter("odometry_topic").value, self._odometry, 10)
        self.create_timer(self.manifest.control_period, self._tick)

    def _reference(self, message: MotionReferenceSegment) -> None:
        try:
            frames = int(message.frame_count)
            segment = Segment(
                request_id=message.request_id, segment_index=message.segment_index, start_frame=message.start_frame,
                dt=message.dt, reset=message.reset, end_of_motion=message.end_of_motion,
                joint_position=np.asarray(message.joint_position, np.float32).reshape(frames, 29),
                joint_velocity=np.asarray(message.joint_velocity, np.float32).reshape(frames, 29),
                anchor_position=np.asarray(message.anchor_position, np.float32).reshape(frames, 3),
                anchor_orientation_wxyz=np.asarray(message.anchor_orientation_wxyz, np.float32).reshape(frames, 4),
            )
            self.engine.append_reference(segment)
        except (ValueError, RuntimeError) as exc:
            self.get_logger().error(f"rejected reference segment: {exc}")

    def _lease(self, message: LowLevelControlLease) -> None:
        compatible = (
            message.active and message.owner == "textop"
            and message.robot_profile == self.manifest.robot_profile
            and message.control_profile == self.manifest.control_profile
        )
        self.lease = message if compatible else None
        if not compatible:
            self.engine.reset()
            self.status_publisher.publish(TextOpTrackerStatus(
                stamp=self.get_clock().now().to_msg(), request_id=message.request_id,
                executed_frames=0, active=False, reference_exhausted=False,
            ))

    def _lowstate(self, message: LowState) -> None:
        self.lowstate, self.lowstate_at = message, time.monotonic()

    def _odometry(self, message: Odometry) -> None:
        self.odometry, self.odometry_at = message, time.monotonic()

    def _tick(self) -> None:
        now = time.monotonic()
        lease = self.lease
        if lease is None or self.lowstate is None or self.odometry is None:
            return
        if lease.request_id != self.engine.references.request_id:
            return
        if now - self.lowstate_at > float(self.get_parameter("lowstate_timeout").value):
            return
        if now - self.odometry_at > float(self.get_parameter("odometry_timeout").value):
            return
        imu = self.lowstate.imu_state
        pose = self.odometry.pose.pose
        twist = self.odometry.twist.twist
        state = RobotState(
            anchor_position_w=np.array([pose.position.x, pose.position.y, pose.position.z], np.float32),
            anchor_orientation_wxyz=np.asarray(imu.quaternion, np.float32),
            linear_velocity_w=np.array([twist.linear.x, twist.linear.y, twist.linear.z], np.float32),
            angular_velocity_b=np.asarray(imu.gyroscope, np.float32),
            joint_position_unitree=np.array([item.q for item in self.lowstate.motor_state[:29]], np.float32),
            joint_velocity_unitree=np.array([item.dq for item in self.lowstate.motor_state[:29]], np.float32),
        )
        try:
            step = self.engine.step(lease.request_id, state)
        except ReferencePending:
            return
        except (ValueError, RuntimeError) as exc:
            self.get_logger().error(f"tracker step failed: {exc}")
            return
        self.sequence += 1
        valid = float(self.get_parameter("candidate_valid_for").value)
        seconds = int(valid)
        motors = [
            JointMotorCommand(q=float(step.command.q[i]), dq=float(step.command.dq[i]), tau=float(step.command.tau[i]),
                              kp=float(step.command.kp[i]), kd=float(step.command.kd[i]))
            for i in range(29)
        ]
        self.publisher.publish(LowLevelCommandCandidate(
            stamp=self.get_clock().now().to_msg(), backend_id="textop", model_id=self.manifest.model_id,
            request_id=lease.request_id, lease_id=lease.lease_id, sequence_id=self.sequence,
            valid_for=Duration(sec=seconds, nanosec=int((valid - seconds) * 1e9)),
            robot_profile=self.manifest.robot_profile, control_profile=self.manifest.control_profile, motors=motors,
        ))
        self.status_publisher.publish(TextOpTrackerStatus(
            stamp=self.get_clock().now().to_msg(), request_id=lease.request_id,
            executed_frames=step.frame + 1, active=True, reference_exhausted=step.motion_complete,
        ))


def main(args=None) -> None:
    rclpy.init(args=args)
    node = TextOpTrackerNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
