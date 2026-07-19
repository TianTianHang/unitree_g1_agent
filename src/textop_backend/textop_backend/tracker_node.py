# rclpy's Humble stubs do not narrow declared parameter values or callback-owned
# optional message state after the readiness checks used by this node.
# pyright: reportArgumentType=false, reportOptionalMemberAccess=false, reportIndexIssue=false

from __future__ import annotations

import time

import numpy as np
import rclpy
from builtin_interfaces.msg import Duration
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.parameter import Parameter
from unitree_hg.msg import LowState

from g1_agent_msgs.msg import (
    JointMotorCommand,
    LowLevelCommandCandidate,
    LowLevelControlLease,
    MotionReferenceSegment,
    TextOpTrackerStatus,
)

from .manifest import load_manifest
from .onnx_policy import load_onnx_policy
from .readiness import validate_odometry
from .reference import MotionReferenceSegment as Segment
from .runtime_preflight import preflight_tracker_runtime
from .tracker import RobotState, body_vector_to_world
from .tracker_engine import ReferencePending, TrackerEngine


class TextOpTrackerNode(Node):
    def __init__(self) -> None:
        super().__init__("textop_tracker_node")
        for name, default in (
            ("manifest_path", ""), ("onnx_providers", ["CPUExecutionProvider"]),
            ("cuda_device_id", 3),
            ("reference_topic", "/g1/textop/reference"), ("lease_topic", "/g1/low_level/lease"),
            ("candidate_topic", "/g1/low_level/candidate"), ("lowstate_topic", "/lowstate"),
            ("odometry_topic", "/odom"), ("lowstate_timeout", 0.1), ("odometry_timeout", 0.1),
            ("odometry_frame", "odom"), ("odometry_child_frame", "pelvis"),
            ("candidate_valid_for", 0.04), ("tracker_status_topic", "/g1/textop/tracker_status"),
        ):
            self.declare_parameter(name, default)
        self.declare_parameter("cuda_library_dirs", Parameter.Type.STRING_ARRAY)
        manifest_path = self.get_parameter("manifest_path").value
        if not manifest_path:
            raise RuntimeError("manifest_path is required")
        report = preflight_tracker_runtime()
        self.get_logger().info(
            f"TextOp tracker preflight passed: python={report.python_version} "
            f"onnxruntime={report.onnxruntime_version} providers={report.onnx_providers}"
        )
        self.manifest = load_manifest(manifest_path)
        policy = load_onnx_policy(
            str(self.manifest.policy.path), input_name=self.manifest.policy.input_name,
            output_name=self.manifest.policy.output_name, providers=list(self.get_parameter("onnx_providers").value),
            cuda_library_dirs=list(self.get_parameter("cuda_library_dirs").value),
            cuda_device_id=int(self.get_parameter("cuda_device_id").value),
        )
        self.engine = TrackerEngine(self.manifest, policy)
        self.lease: LowLevelControlLease | None = None
        self.lowstate: LowState | None = None
        self.odometry: Odometry | None = None
        self.lowstate_at = 0.0
        self.odometry_at = 0.0
        self.odometry_error = "odometry unavailable"
        self.sequence = 0
        self.publisher = self.create_publisher(
            LowLevelCommandCandidate, self.get_parameter("candidate_topic").value, 10
        )
        self.status_publisher = self.create_publisher(
            TextOpTrackerStatus, self.get_parameter("tracker_status_topic").value, 10
        )
        self.create_subscription(
            MotionReferenceSegment,
            self.get_parameter("reference_topic").value,
            self._reference,
            10,
        )
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
                ready=self._ready()[0], readiness_reason=self._ready()[1],
            ))

    def _lowstate(self, message: LowState) -> None:
        self.lowstate, self.lowstate_at = message, time.monotonic()

    def _odometry(self, message: Odometry) -> None:
        try:
            validate_odometry(
                message,
                now_sec=self.get_clock().now().nanoseconds * 1e-9,
                timeout=float(self.get_parameter("odometry_timeout").value),
                expected_frame=str(self.get_parameter("odometry_frame").value),
                expected_child_frame=str(self.get_parameter("odometry_child_frame").value),
            )
        except ValueError as exc:
            self.odometry = None
            self.odometry_error = str(exc)
            self.get_logger().warning(f"rejecting odometry: {exc}")
            return
        self.odometry, self.odometry_at = message, time.monotonic()
        self.odometry_error = ""

    def _ready(self) -> tuple[bool, str]:
        now = time.monotonic()
        if self.lowstate is None:
            return False, "lowstate unavailable"
        if now - self.lowstate_at > float(self.get_parameter("lowstate_timeout").value):
            return False, "lowstate stale"
        motors = self.lowstate.motor_state
        if len(motors) < 29:
            return False, f"lowstate has fewer than 29 motors: {len(motors)}"
        if not np.isfinite(np.array([(item.q, item.dq) for item in motors[:29]], np.float32)).all():
            return False, "lowstate motor state contains non-finite values"
        if self.odometry is None:
            return False, self.odometry_error
        if now - self.odometry_at > float(self.get_parameter("odometry_timeout").value):
            return False, "odometry stale"
        try:
            validate_odometry(
                self.odometry,
                now_sec=self.get_clock().now().nanoseconds * 1e-9,
                timeout=float(self.get_parameter("odometry_timeout").value),
                expected_frame=str(self.get_parameter("odometry_frame").value),
                expected_child_frame=str(self.get_parameter("odometry_child_frame").value),
            )
        except ValueError as exc:
            return False, str(exc)
        return True, ""

    def _publish_readiness(self, *, ready: bool, reason: str) -> None:
        self.status_publisher.publish(TextOpTrackerStatus(
            stamp=self.get_clock().now().to_msg(), request_id="", executed_frames=0,
            active=False, reference_exhausted=False, ready=ready, readiness_reason=reason,
        ))

    def _tick(self) -> None:
        ready, reason = self._ready()
        if not ready:
            self._publish_readiness(ready=False, reason=reason)
            return
        lease = self.lease
        if lease is None:
            self._publish_readiness(ready=True, reason="")
            return
        if lease.request_id != self.engine.references.request_id:
            return
        pose = self.odometry.pose.pose
        twist = self.odometry.twist.twist
        orientation_wxyz = np.array(
            [pose.orientation.w, pose.orientation.x, pose.orientation.y, pose.orientation.z], np.float32
        )
        linear_velocity_body = np.array([twist.linear.x, twist.linear.y, twist.linear.z], np.float32)
        state = RobotState(
            anchor_position_w=np.array([pose.position.x, pose.position.y, pose.position.z], np.float32),
            anchor_orientation_wxyz=orientation_wxyz,
            linear_velocity_w=body_vector_to_world(orientation_wxyz, linear_velocity_body),
            angular_velocity_b=np.array([twist.angular.x, twist.angular.y, twist.angular.z], np.float32),
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
            ready=True, readiness_reason="",
        ))


def main(args=None) -> None:
    rclpy.init(args=args)
    node = TextOpTrackerNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
