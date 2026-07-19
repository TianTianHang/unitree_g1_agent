from __future__ import annotations

import concurrent.futures
import math
import threading
import time
import uuid

import rclpy
from builtin_interfaces.msg import Duration
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from g1_agent_msgs.action import ExecuteMotion
from g1_agent_msgs.msg import (
    LowLevelControlLease,
    MotionReferenceSegment,
    TextOpTrackerStatus,
    ValidatedActionCommand,
)

from .generator import StaleGeneration
from .generator_engine import GeneratorEngine
from .generator_session import GeneratorSession
from .manifest import load_manifest
from .readiness import ReadinessGate
from .robotmdar_runtime import RobotMDARRuntime
from .runtime_preflight import preflight_generator_runtime
from .runtime_lock import load_robotmdar_lock
from .stop_gate import StopGate, StopToken, validated_stop_action


def _duration_seconds(value) -> float:
    return float(value.sec) + float(value.nanosec) * 1e-9


class TextOpGeneratorNode(Node):
    def __init__(self) -> None:
        super().__init__("textop_generator_node")
        parameters = (
            ("manifest_path", ""), ("skeleton_asset_root", ""),
            ("robotmdar_lock_path", ""),
            ("device", "cuda:3"), ("guidance_scale", 2.5), ("compile_backend", ""),
            ("action_name", "/g1/textop/execute_motion"),
            ("reference_topic", "/g1/textop/reference"),
            ("lease_topic", "/g1/low_level/lease"),
            ("tracker_status_topic", "/g1/textop/tracker_status"),
            ("safe_stop_topic", "/g1/safe_cmd/stop"),
            ("lease_ttl", 0.5), ("tracker_timeout", 2.0),
            ("readiness_timeout", 0.25),
        )
        for name, default in parameters:
            self.declare_parameter(name, default)
        manifest_path = str(self.get_parameter("manifest_path").value)
        skeleton_root = str(self.get_parameter("skeleton_asset_root").value)
        if not manifest_path or not skeleton_root:
            raise RuntimeError("manifest_path and skeleton_asset_root are required")
        device = str(self.get_parameter("device").value)
        lock_path = str(self.get_parameter("robotmdar_lock_path").value)
        lock = load_robotmdar_lock(lock_path) if lock_path else (None, None)
        report = preflight_generator_runtime(
            device=device, expected_robotmdar_version=lock[0], expected_robotmdar_digest=lock[1]
        )
        self.get_logger().info(
            f"TextOp generator preflight passed: python={report.python_version} "
            f"torch={report.torch_version} device=cuda:{report.device_index} "
            f"robotmdar={report.robotmdar_version}"
        )
        self.manifest = load_manifest(manifest_path)
        runtime = RobotMDARRuntime(
            self.manifest.generator.checkpoint.path,
            vae=self.manifest.generator.vae.path,
            statistics=self.manifest.generator.statistics.path,
            normalization=self.manifest.generator.normalization.path,
            skeleton_asset_root=skeleton_root,
            device=device,
            guidance_scale=float(self.get_parameter("guidance_scale").value),
            compile_backend=str(self.get_parameter("compile_backend").value),
        )
        self.engine = GeneratorEngine(runtime)
        self.session = GeneratorSession(future_len=runtime.future_len, dt=runtime.dt)
        self._worker = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="robotmdar")
        self._lock = threading.RLock()
        self._active_request_id: str | None = None
        self._stop_gate = StopGate()
        self._stop_token: StopToken | None = None
        self._lease_id = ""
        self._lease_active = False
        self._lease_activated_at = 0.0
        self._last_tracker_status = 0.0
        self._readiness = ReadinessGate()
        group = ReentrantCallbackGroup()
        self.reference_publisher = self.create_publisher(
            MotionReferenceSegment, str(self.get_parameter("reference_topic").value), 10
        )
        self.lease_publisher = self.create_publisher(
            LowLevelControlLease, str(self.get_parameter("lease_topic").value), 10
        )
        self.create_subscription(
            TextOpTrackerStatus, str(self.get_parameter("tracker_status_topic").value),
            self._tracker_status, 10, callback_group=group,
        )
        self.create_subscription(
            ValidatedActionCommand,
            str(self.get_parameter("safe_stop_topic").value),
            self._safe_stop,
            10,
            callback_group=group,
        )
        ttl = float(self.get_parameter("lease_ttl").value)
        if ttl <= 0.0:
            raise ValueError("lease_ttl must be positive")
        self.create_timer(max(0.02, ttl / 2.0), self._renew_lease, callback_group=group)
        self._action_server = ActionServer(
            self, ExecuteMotion, str(self.get_parameter("action_name").value),
            execute_callback=self._execute, goal_callback=self._goal,
            cancel_callback=self._cancel, callback_group=group,
        )

    def _goal(self, request: ExecuteMotion.Goal) -> GoalResponse:
        duration = _duration_seconds(request.duration)
        with self._lock:
            ready, readiness_reason = self._readiness.can_accept(
                now_sec=time.monotonic(), timeout=float(self.get_parameter("readiness_timeout").value)
            )
            valid = (
                self._active_request_id is None and bool(request.request_id) and bool(request.prompt.strip())
                and request.backend_id in ("", "textop") and math.isfinite(duration) and duration > 0.0
                and ready
            )
            if valid:
                self._active_request_id = request.request_id
                self._stop_token = self._stop_gate.begin(request.request_id)
            elif not ready:
                self.get_logger().warning(f"rejecting TextOp goal: {readiness_reason}")
        return GoalResponse.ACCEPT if valid else GoalResponse.REJECT

    def _cancel(self, goal_handle) -> CancelResponse:
        self._request_stop(goal_handle.request.request_id, reason="action_cancel")
        return CancelResponse.ACCEPT

    def _safe_stop(self, message: ValidatedActionCommand) -> None:
        try:
            action = validated_stop_action(message)
        except ValueError as exc:
            self.get_logger().warning(f"rejecting safe stop: {exc}")
            return
        with self._lock:
            request_id = self._active_request_id
        if request_id is None:
            self.get_logger().info(f"ignoring {action}: no active TextOp request")
            return
        self._request_stop(request_id, reason=f"safe_{action}")

    def _tracker_status(self, message: TextOpTrackerStatus) -> None:
        with self._lock:
            self._readiness.update(
                ready=bool(message.ready), reason=str(message.readiness_reason), at_sec=time.monotonic()
            )
            if message.active and message.request_id == self._active_request_id:
                self.session.update_executed(message.request_id, int(message.executed_frames))
                self._last_tracker_status = time.monotonic()

    def _execute(self, goal_handle) -> ExecuteMotion.Result:
        goal = goal_handle.request
        request_id = goal.request_id
        with self._lock:
            stop_token = self._stop_token
        if stop_token is None or stop_token.request_id != request_id:
            goal_handle.abort()
            return ExecuteMotion.Result(success=False, reason="request stop token unavailable")
        token = None
        try:
            self.session.begin(request_id, duration_seconds=_duration_seconds(goal.duration))
            self._raise_if_cancelled(goal_handle, request_id, stop_token)
            token = self._await_future(goal_handle, self._worker.submit(self.engine.begin, request_id, goal.prompt), "loading")
            self._raise_if_cancelled(goal_handle, request_id, stop_token)
            for primitive_index in range(self.session.required_primitives):
                end = primitive_index == self.session.required_primitives - 1
                segment = self._await_future(
                    goal_handle, self._worker.submit(self.engine.generate_next, token, end_of_motion=end), "generating"
                )
                self._raise_if_cancelled(goal_handle, request_id, stop_token)
                self.reference_publisher.publish(self._segment_message(segment))
                self.session.mark_generated(request_id)
                if primitive_index == 0:
                    self._activate_lease(request_id)
                self._feedback(goal_handle, "generating")
            while not self.session.execution_complete:
                self._raise_if_cancelled(goal_handle, request_id, stop_token)
                with self._lock:
                    last_status = self._last_tracker_status
                timeout = float(self.get_parameter("tracker_timeout").value)
                status_base = last_status or self._lease_activated_at
                if time.monotonic() - status_base > timeout:
                    raise RuntimeError("tracker status timed out")
                self._feedback(goal_handle, "executing")
                time.sleep(0.02)
            self._feedback(goal_handle, "stopping")
            self._deactivate_lease(request_id)
            self.engine.machine.drained(token)
            self.session.finish(request_id)
            goal_handle.succeed()
            return ExecuteMotion.Result(success=True, reason="motion completed")
        except _GoalCancelled as exc:
            self._stop_request(request_id)
            goal_handle.canceled()
            return ExecuteMotion.Result(success=False, reason=str(exc))
        except (Exception, StaleGeneration) as exc:
            self.get_logger().error(f"TextOp request {request_id} failed: {exc}")
            self._stop_request(request_id)
            goal_handle.abort()
            return ExecuteMotion.Result(success=False, reason=str(exc))
        finally:
            with self._lock:
                if self._active_request_id == request_id:
                    self._active_request_id = None
                self._stop_gate.finish(stop_token)
                if self._stop_token == stop_token:
                    self._stop_token = None

    def _await_future(self, goal_handle, future, state: str):
        while True:
            with self._lock:
                stop_token = self._stop_token
            if stop_token is None:
                raise _GoalCancelled("motion canceled")
            self._raise_if_cancelled(goal_handle, goal_handle.request.request_id, stop_token)
            try:
                return future.result(timeout=0.05)
            except concurrent.futures.TimeoutError:
                self._feedback(goal_handle, state)

    def _raise_if_cancelled(self, goal_handle, request_id: str, stop_token: StopToken) -> None:
        with self._lock:
            stopped = self._stop_gate.is_stopped(stop_token)
            reason = self._stop_gate.stop_reason(stop_token)
        if goal_handle.is_cancel_requested or stopped:
            self.engine.cancel(request_id)
            self.session.cancel(request_id)
            self._deactivate_lease(request_id)
            raise _GoalCancelled(reason or "action_cancel")

    def _request_stop(self, request_id: str, *, reason: str) -> bool:
        with self._lock:
            changed = self._stop_gate.request_stop(request_id, reason=reason)
            if changed:
                self._deactivate_lease(request_id)
        return changed

    def _feedback(self, goal_handle, state: str) -> None:
        goal_handle.publish_feedback(ExecuteMotion.Feedback(
            state=state, generated_frames=self.session.generated_frames,
            executed_frames=self.session.executed_frames,
        ))

    def _activate_lease(self, request_id: str) -> None:
        with self._lock:
            self._lease_id = str(uuid.uuid4())
            self._lease_active = True
            self._lease_activated_at = time.monotonic()
            self._last_tracker_status = 0.0
            self._publish_lease(request_id, True)

    def _renew_lease(self) -> None:
        with self._lock:
            request_id = self._active_request_id
            if self._lease_active and request_id:
                self._publish_lease(request_id, True)

    def _deactivate_lease(self, request_id: str) -> None:
        with self._lock:
            was_active = self._lease_active
            self._lease_active = False
            if was_active:
                self._publish_lease(request_id, False)

    def _publish_lease(self, request_id: str, active: bool) -> None:
        ttl = float(self.get_parameter("lease_ttl").value)
        seconds = int(ttl)
        self.lease_publisher.publish(LowLevelControlLease(
            stamp=self.get_clock().now().to_msg(), lease_id=self._lease_id, request_id=request_id,
            owner="textop", robot_profile=self.manifest.robot_profile,
            control_profile=self.manifest.control_profile,
            ttl=Duration(sec=seconds, nanosec=int((ttl - seconds) * 1e9)), active=active,
        ))

    def _stop_request(self, request_id: str) -> None:
        self.engine.cancel(request_id)
        self.session.cancel(request_id)
        self._deactivate_lease(request_id)

    @staticmethod
    def _segment_message(segment) -> MotionReferenceSegment:
        frames = int(segment.joint_position.shape[0])
        return MotionReferenceSegment(
            request_id=segment.request_id, segment_index=segment.segment_index,
            start_frame=segment.start_frame, dt=segment.dt, reset=segment.reset,
            end_of_motion=segment.end_of_motion, frame_count=frames,
            joint_position=segment.joint_position.reshape(-1).tolist(),
            joint_velocity=segment.joint_velocity.reshape(-1).tolist(),
            anchor_position=segment.anchor_position.reshape(-1).tolist(),
            anchor_orientation_wxyz=segment.anchor_orientation_wxyz.reshape(-1).tolist(),
        )

    def destroy_node(self):
        self._worker.shutdown(wait=False, cancel_futures=True)
        self._action_server.destroy()
        return super().destroy_node()


class _GoalCancelled(Exception):
    pass


def main(args=None) -> None:
    rclpy.init(args=args)
    node = TextOpGeneratorNode()
    executor = MultiThreadedExecutor(num_threads=3)
    executor.add_node(node)
    try:
        executor.spin()
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()
