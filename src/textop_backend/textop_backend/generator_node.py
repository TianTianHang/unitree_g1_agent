# rclpy Parameter.value is typed as optional/unknown in Humble although declared
# parameters below always have concrete defaults.
# pyright: reportArgumentType=false

from __future__ import annotations

import math
import threading
import time
import uuid
from dataclasses import dataclass

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
from .prompt_stream import CommandState, PromptCommand, PromptStreamCoordinator
from .readiness import ReadinessGate
from .robotmdar_runtime import RobotMDARRuntime
from .runtime_preflight import preflight_generator_runtime
from .stop_gate import validated_stop_action


def _duration_seconds(value) -> float:
    return float(value.sec) + float(value.nanosec) * 1e-9


@dataclass
class _GoalRecord:
    goal_handle: object
    done: threading.Event


class TextOpGeneratorNode(Node):
    def __init__(self) -> None:
        super().__init__("textop_generator_node")
        parameters = (
            ("manifest_path", ""),
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
        if not manifest_path:
            raise RuntimeError("manifest_path is required")
        device = str(self.get_parameter("device").value)
        report = preflight_generator_runtime(device=device)
        self.get_logger().info(
            f"TextOp generator preflight passed: python={report.python_version} "
            f"torch={report.torch_version} device=cuda:{report.device_index} "
            "local_inference=true"
        )
        self.manifest = load_manifest(manifest_path)
        runtime = RobotMDARRuntime(
            self.manifest.generator.checkpoint.path,
            vae=self.manifest.generator.vae.path,
            normalization=self.manifest.generator.normalization.path,
            clip_weights=self.manifest.generator.clip.path,
            device=device,
            guidance_scale=float(self.get_parameter("guidance_scale").value),
            compile_backend=str(self.get_parameter("compile_backend").value),
        )
        self.engine = GeneratorEngine(runtime)
        self.session = GeneratorSession(future_len=runtime.future_len, dt=runtime.dt)
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._stream = PromptStreamCoordinator()
        self._goal_records: dict[str, _GoalRecord] = {}
        self._accepted_request_ids: set[str] = set()
        self._stream_shutdown = False
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
        self._stream_thread = threading.Thread(
            target=self._stream_loop,
            name="textop_prompt_stream",
            daemon=True,
        )
        self._stream_thread.start()

    def _goal(self, request: ExecuteMotion.Goal) -> GoalResponse:
        duration = _duration_seconds(request.duration)
        with self._lock:
            ready, readiness_reason = self._readiness.can_accept(
                now_sec=time.monotonic(), timeout=float(self.get_parameter("readiness_timeout").value)
            )
            stream_is_loading = (
                (self._stream.active is not None or self._stream.pending is not None)
                and not self._lease_active
            )
            admission_ready = ready or stream_is_loading
            valid = (
                bool(request.request_id) and request.request_id not in self._accepted_request_ids
                and bool(request.prompt.strip())
                and request.backend_id in ("", "textop") and math.isfinite(duration) and duration > 0.0
                and admission_ready
            )
            if valid:
                self._accepted_request_ids.add(request.request_id)
            elif not admission_ready:
                self.get_logger().warning(f"rejecting TextOp goal: {readiness_reason}")
        return GoalResponse.ACCEPT if valid else GoalResponse.REJECT

    def _cancel(self, goal_handle) -> CancelResponse:
        request_id = goal_handle.request.request_id
        with self._lock:
            active = self._stream.active
            pending = self._stream.pending
            owns_stream = (
                active is not None and active.request_id == request_id
            ) or (
                pending is not None and pending.request_id == request_id
            )
        if owns_stream:
            self._cancel_stream("action_cancel")
        return CancelResponse.ACCEPT

    def _safe_stop(self, message: ValidatedActionCommand) -> None:
        try:
            action = validated_stop_action(message)
        except ValueError as exc:
            self.get_logger().warning(f"rejecting safe stop: {exc}")
            return
        with self._lock:
            has_commands = self._stream.active is not None or self._stream.pending is not None
        if not has_commands:
            self.get_logger().info(f"ignoring {action}: no active TextOp request")
            return
        self._cancel_stream(f"safe_{action}")

    def _tracker_status(self, message: TextOpTrackerStatus) -> None:
        with self._lock:
            self._readiness.update(
                ready=bool(message.ready), reason=str(message.readiness_reason), at_sec=time.monotonic()
            )
            active = self._stream.active
            if message.active and active is not None and message.request_id == active.request_id:
                self.session.update_executed(message.request_id, int(message.executed_frames))
                self._last_tracker_status = time.monotonic()
                self._condition.notify_all()

    def _execute(self, goal_handle) -> ExecuteMotion.Result:
        goal = goal_handle.request
        request_id = goal.request_id
        try:
            command = PromptCommand(
                request_id=request_id,
                prompt=goal.prompt,
                duration_sec=_duration_seconds(goal.duration),
            )
            record = _GoalRecord(goal_handle=goal_handle, done=threading.Event())
            with self._condition:
                previous_pending = self._stream.pending
                self._goal_records[request_id] = record
                self._stream.submit(command)
                if previous_pending is not None:
                    self._signal_goal(previous_pending.request_id)
                self._condition.notify_all()
            while not record.done.wait(timeout=0.05):
                if goal_handle.is_cancel_requested:
                    self._cancel_stream("action_cancel")
                self._feedback_for_request(goal_handle, request_id)
            with self._lock:
                outcome = self._stream.outcome(request_id)
            if outcome is None:
                goal_handle.abort()
                return ExecuteMotion.Result(success=False, reason="command outcome unavailable")
            if outcome.state is CommandState.COMPLETED:
                goal_handle.succeed()
                return ExecuteMotion.Result(success=True, reason=outcome.reason)
            if outcome.state is CommandState.CANCELED:
                goal_handle.canceled()
            else:
                goal_handle.abort()
            return ExecuteMotion.Result(success=False, reason=outcome.reason)
        except ValueError as exc:
            goal_handle.abort()
            return ExecuteMotion.Result(success=False, reason=str(exc))
        finally:
            with self._lock:
                self._goal_records.pop(request_id, None)
                self._accepted_request_ids.discard(request_id)
                self._stream.forget(request_id)

    def _stream_loop(self) -> None:
        token = None
        while True:
            with self._condition:
                while (
                    not self._stream_shutdown
                    and self._stream.active is None
                    and self._stream.pending is None
                ):
                    self._condition.wait()
                if self._stream_shutdown:
                    return
                transition = self._stream.activate_pending()
            if transition is not None:
                try:
                    if transition.previous is None:
                        token = self.engine.begin(
                            transition.current.request_id,
                            transition.current.prompt,
                        )
                        self.session.begin(
                            transition.current.request_id,
                            duration_seconds=transition.current.duration_sec,
                        )
                    else:
                        token = self.engine.replace(
                            transition.current.request_id,
                            transition.current.prompt,
                        )
                        self.session.replace(
                            transition.current.request_id,
                            duration_seconds=transition.current.duration_sec,
                        )
                    with self._lock:
                        current = self._stream.active
                        still_active = (
                            current is not None
                            and current.request_id == transition.current.request_id
                        )
                    if not still_active:
                        self.engine.cancel(transition.current.request_id)
                        self.session.cancel(transition.current.request_id)
                        continue
                except StaleGeneration:
                    continue
                except Exception as exc:
                    self._fail_stream(str(exc))
                    continue
                finally:
                    if transition.previous is not None:
                        self._signal_goal(transition.previous.request_id)

            with self._lock:
                active = self._stream.active
                if active is None or token is None:
                    continue
                needs_generation = self.session.generated_frames < self.session.total_frames

            if needs_generation:
                try:
                    end = self.session.generated_frames + self.session.future_len >= self.session.total_frames
                    segment = self.engine.generate_next(token, end_of_motion=end)
                    with self._condition:
                        current = self._stream.active
                        if current is None or current.request_id != active.request_id:
                            continue
                        first = self.session.generated_frames == 0
                        if first:
                            if self._lease_active:
                                self._switch_lease(active.request_id)
                            else:
                                self._activate_lease(active.request_id)
                        self.reference_publisher.publish(self._segment_message(segment))
                        self.session.mark_generated(active.request_id)
                except StaleGeneration:
                    continue
                except Exception as exc:
                    self._fail_stream(str(exc))
                continue

            with self._condition:
                if self._stream.pending is not None:
                    continue
                if self.session.execution_complete:
                    try:
                        self._complete_active(token)
                    except Exception as exc:
                        self._fail_stream(str(exc))
                    token = None
                    continue
                timeout = float(self.get_parameter("tracker_timeout").value)
                status_base = self._last_tracker_status or self._lease_activated_at
                if self._lease_active and time.monotonic() - status_base > timeout:
                    self._fail_stream("tracker status timed out")
                    token = None
                    continue
                self._condition.wait(timeout=0.02)

    def _complete_active(self, token) -> None:
        active = self._stream.active
        if active is None:
            return
        request_id = active.request_id
        self._deactivate_lease(request_id)
        self.engine.machine.drained(token)
        self.session.finish(request_id)
        self._stream.complete_active()
        self._signal_goal(request_id)

    def _cancel_stream(self, reason: str) -> None:
        with self._condition:
            active = self._stream.active
            canceled = self._stream.cancel_all(reason)
            if active is not None:
                self.engine.cancel(active.request_id)
                self.session.cancel(active.request_id)
                self._deactivate_lease(active.request_id)
            for command in canceled:
                self._signal_goal(command.request_id)
            self._condition.notify_all()

    def _fail_stream(self, reason: str) -> None:
        with self._condition:
            active = self._stream.active
            if active is not None:
                request_id = active.request_id
                self.engine.cancel(request_id)
                self.session.cancel(request_id)
                self._deactivate_lease(request_id)
                self._stream.fail_active(reason)
                self._signal_goal(request_id)
            pending = self._stream.cancel_all(f"stream_failed:{reason}")
            for command in pending:
                self._signal_goal(command.request_id)
            self.get_logger().error(f"TextOp stream failed: {reason}")
            self._condition.notify_all()

    def _signal_goal(self, request_id: str) -> None:
        record = self._goal_records.get(request_id)
        if record is not None:
            record.done.set()

    def _feedback_for_request(self, goal_handle, request_id: str) -> None:
        with self._lock:
            outcome = self._stream.outcome(request_id)
            active = self._stream.active
            generated = self.session.generated_frames if active and active.request_id == request_id else 0
            executed = self.session.executed_frames if active and active.request_id == request_id else 0
        state = outcome.state.value if outcome is not None else "pending"
        goal_handle.publish_feedback(
            ExecuteMotion.Feedback(state=state, generated_frames=generated, executed_frames=executed)
        )

    def _activate_lease(self, request_id: str) -> None:
        with self._lock:
            self._lease_id = str(uuid.uuid4())
            self._lease_active = True
            self._lease_activated_at = time.monotonic()
            self._last_tracker_status = 0.0
            self._publish_lease(request_id, True)

    def _renew_lease(self) -> None:
        with self._lock:
            active = self._stream.active
            if self._lease_active and active is not None:
                self._publish_lease(active.request_id, True)

    def _switch_lease(self, request_id: str) -> None:
        with self._lock:
            if not self._lease_active:
                return
            self._lease_activated_at = time.monotonic()
            self._last_tracker_status = 0.0
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
        self._cancel_stream("node_shutdown")
        with self._condition:
            self._stream_shutdown = True
            self._condition.notify_all()
        self._stream_thread.join(timeout=2.0)
        self._action_server.destroy()
        return super().destroy_node()


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
