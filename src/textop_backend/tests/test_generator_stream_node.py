import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("g1_agent_msgs")

from textop_backend.generator_engine import GeneratorEngine, PrimitiveResult
from textop_backend.generator_node import TextOpGeneratorNode
from textop_backend.generator_session import GeneratorSession
from textop_backend.prompt_stream import PromptCommand, PromptStreamCoordinator
from textop_backend.readiness import ReadinessGate


class FakeRuntime:
    history_len = 2
    future_len = 8
    dt = 0.02

    def __init__(self):
        self.calls = []
        self.encode_started = threading.Event()
        self.encode_release = threading.Event()
        self.encode_release.set()

    def initial_state(self):
        return "history-0", "pose-0"

    def encode_text(self, prompt):
        self.encode_started.set()
        self.encode_release.wait(timeout=1.0)
        return f"embedding:{prompt}"

    def generate(self, embedding, history, absolute_pose):
        self.calls.append((embedding, history, absolute_pose))
        index = len(self.calls)
        values = np.zeros((10, 23), dtype=np.float32)
        return PrimitiveResult(
            future_motion=f"history-{index}",
            absolute_pose=f"pose-{index}",
            dof_position=values,
            dof_velocity=values,
            anchor_position=np.zeros((10, 3), dtype=np.float32),
            anchor_orientation_xyzw=np.tile([0, 0, 0, 1], (10, 1)).astype(np.float32),
        )


class FakeGoalHandle:
    def __init__(self, request_id, prompt, duration=0.32):
        seconds = int(duration)
        self.request = SimpleNamespace(
            request_id=request_id,
            prompt=prompt,
            duration=SimpleNamespace(sec=seconds, nanosec=int((duration - seconds) * 1e9)),
        )
        self.is_cancel_requested = False
        self.feedback = []
        self.terminal = None

    def publish_feedback(self, feedback):
        self.feedback.append(feedback)

    def succeed(self):
        self.terminal = "succeeded"

    def abort(self):
        self.terminal = "aborted"

    def canceled(self):
        self.terminal = "canceled"


class FakePublisher:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not reached before timeout")


def _node():
    node = object.__new__(TextOpGeneratorNode)
    node._lock = threading.RLock()
    node._condition = threading.Condition(node._lock)
    node._stream = PromptStreamCoordinator()
    node._goal_records = {}
    node._accepted_request_ids = set()
    node._readiness = ReadinessGate()
    node._stream_shutdown = False
    node._lease_active = False
    node._lease_id = ""
    node._lease_activated_at = time.monotonic()
    node._last_tracker_status = time.monotonic()
    runtime = FakeRuntime()
    node.engine = GeneratorEngine(runtime)
    node.session = GeneratorSession(future_len=8, dt=0.02)
    node.reference_publisher = FakePublisher()
    node.get_parameter = lambda name: SimpleNamespace(value=10.0)
    node.get_logger = lambda: SimpleNamespace(error=lambda _message: None)

    def activate(request_id):
        node._lease_active = True
        node._lease_activated_at = time.monotonic()

    def deactivate(_request_id):
        node._lease_active = False

    node._activate_lease = activate
    node._switch_lease = activate
    node._deactivate_lease = deactivate
    node._stream_thread = threading.Thread(target=node._stream_loop, daemon=True)
    node._stream_thread.start()
    return node, runtime


def _shutdown(node):
    node._cancel_stream("test_shutdown")
    with node._condition:
        node._stream_shutdown = True
        node._condition.notify_all()
    node._stream_thread.join(timeout=1.0)


def test_execute_goal_is_superseded_at_boundary_without_resetting_generator_history():
    node, runtime = _node()
    first = FakeGoalHandle("r1", "wave")
    second = FakeGoalHandle("r2", "turn")
    results = {}

    first_thread = threading.Thread(target=lambda: results.setdefault("r1", node._execute(first)))
    first_thread.start()
    _wait_until(lambda: node.session.generated_frames == node.session.total_frames)

    second_thread = threading.Thread(target=lambda: results.setdefault("r2", node._execute(second)))
    second_thread.start()
    _wait_until(lambda: first.terminal == "aborted")
    _wait_until(lambda: node._stream.active is not None and node._stream.active.request_id == "r2")
    node._cancel(first)
    assert node._stream.active.request_id == "r2"
    _wait_until(lambda: node.session.generated_frames == node.session.total_frames)

    with node._condition:
        node.session.update_executed("r2", node.session.total_frames)
        node._last_tracker_status = time.monotonic()
        node._condition.notify_all()

    first_thread.join(timeout=1.0)
    second_thread.join(timeout=1.0)
    _shutdown(node)

    assert first.terminal == "aborted"
    assert results["r1"].reason == "superseded_by:r2"
    assert second.terminal == "succeeded"
    assert results["r2"].success is True
    replacement_calls = [call for call in runtime.calls if call[0] == "embedding:turn"]
    assert replacement_calls
    assert replacement_calls[0][1] != "history-0"
    assert replacement_calls[0][2] != "pose-0"


def test_stop_during_active_stream_cancels_goal_and_deactivates_lease():
    node, _runtime = _node()
    goal = FakeGoalHandle("r1", "wave", duration=2.0)
    result = {}
    thread = threading.Thread(target=lambda: result.setdefault("value", node._execute(goal)))
    thread.start()
    _wait_until(lambda: node._lease_active)

    node._cancel_stream("safe_stop")

    thread.join(timeout=1.0)
    _shutdown(node)
    assert goal.terminal == "canceled"
    assert result["value"].reason == "safe_stop"
    assert node._lease_active is False


def test_stop_during_initial_text_encoding_does_not_publish_orphan_stream():
    node, runtime = _node()
    runtime.encode_started.clear()
    runtime.encode_release.clear()
    goal = FakeGoalHandle("r1", "wave", duration=1.0)
    result = {}
    thread = threading.Thread(target=lambda: result.setdefault("value", node._execute(goal)))
    thread.start()
    assert runtime.encode_started.wait(timeout=1.0)

    node._cancel_stream("safe_stop")
    runtime.encode_release.set()

    thread.join(timeout=1.0)
    _wait_until(lambda: node.engine.machine.request_id is None)
    _shutdown(node)
    assert goal.terminal == "canceled"
    assert result["value"].reason == "safe_stop"
    assert node.reference_publisher.messages == []


def test_prompt_update_is_admitted_while_initial_stream_is_still_loading():
    node, _runtime = _node()
    node._stream.submit(PromptCommand("r1", "wave", 1.0))
    node._stream.activate_pending()
    request = SimpleNamespace(
        request_id="r2",
        prompt="turn",
        backend_id="textop",
        duration=SimpleNamespace(sec=1, nanosec=0),
    )

    response = node._goal(request)

    _shutdown(node)
    assert response.name == "ACCEPT"
