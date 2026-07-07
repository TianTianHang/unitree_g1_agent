import io
import json
import queue
import threading
import time
from pathlib import Path

import pytest

from voice_bridge.pi_agent import PiRpcTransport, PiTransportError


class FakeStdin(io.StringIO):
    def __init__(self):
        super().__init__()
        self.lines: list[dict] = []

    def write(self, value: str) -> int:
        self.lines.append(json.loads(value))
        return len(value)

    def flush(self) -> None:
        return None


class FakeProc:
    def __init__(self, stdout_lines: list[bytes]):
        self.stdin = FakeStdin()
        self.stdout = iter(stdout_lines)
        self.stderr = iter([])
        self.pid = 4242
        self.returncode = None
        self.wait_called = False

    def wait(self, timeout=None):
        self.wait_called = True
        self.returncode = 0
        return 0


def make_transport(proc: FakeProc) -> PiRpcTransport:
    transport = PiRpcTransport(popen_factory=lambda *args, **kwargs: proc)
    transport.start(["pi", "--mode", "rpc"], Path("."), {})
    return transport


def test_send_correlates_response_by_id(monkeypatch):
    proc = FakeProc([])
    transport = make_transport(proc)

    def responder():
        deadline = time.monotonic() + 1
        while not proc.stdin.lines and time.monotonic() < deadline:
            time.sleep(0.01)
        request_id = proc.stdin.lines[0]["id"]
        transport._route_message({"type": "response", "id": request_id, "success": True, "data": {"ok": True}})

    thread = threading.Thread(target=responder)
    thread.start()
    response = transport.send({"type": "get_state"}, timeout=1.0)
    thread.join(timeout=1)

    assert response["data"] == {"ok": True}
    assert proc.stdin.lines[0]["type"] == "get_state"


def test_route_message_puts_events_in_generation_queue():
    transport = PiRpcTransport()
    generation = transport.current_generation()

    transport._route_message({"type": "tool_execution_start", "toolCallId": "t1"})

    assert transport.get_event(generation, timeout=0.1) == (
        generation,
        {"type": "tool_execution_start", "toolCallId": "t1"},
    )


def test_get_event_discards_old_generation_events():
    transport = PiRpcTransport()
    old_generation = transport.current_generation()
    transport._route_message({"type": "agent_end"})
    new_generation = transport._bump_generation()
    transport.wake_events("restart")

    assert transport.get_event(new_generation, timeout=0.1) == (
        new_generation,
        {"type": "_transport_wakeup", "reason": "restart"},
    )
    assert transport.get_event(old_generation, timeout=0.01) is None


def test_reader_finally_wakes_pending_and_event_waiters():
    proc = FakeProc([])
    transport = make_transport(proc)
    generation = transport.current_generation()

    response_q: queue.Queue = queue.Queue(maxsize=1)
    with transport._pending_lock:
        transport._pending["abc"] = response_q
    transport._reader()

    assert response_q.get(timeout=0.1)["success"] is False
    event = transport.get_event(generation + 1, timeout=0.1)
    assert event == (generation + 1, {"type": "_transport_wakeup", "reason": "closed"})


def test_send_rejects_closed_transport():
    transport = PiRpcTransport()

    with pytest.raises(PiTransportError, match="transport not running"):
        transport.send({"type": "get_state"}, timeout=0.01)
