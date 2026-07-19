from __future__ import annotations

import json
import math
import os
import queue
import re
import signal
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from copy import deepcopy
from enum import Enum
from pathlib import Path
from typing import Any

from voice_bridge.config import VoiceBridgeConfig
from voice_bridge.internal_types import AgentCommand, AgentRequest, AgentResult
from voice_bridge.pi_config import (
    DEFAULT_PI_CONFIG,
    build_pi_command,
    resolve_repo_root,
    resolve_workspace,
    scrubbed_env,
)
from voice_bridge.pi_types import CUSTOM_TOOLS, DEFAULT_PI_TIMEOUTS


class PiTransportError(RuntimeError):
    pass


class PiRpcTransport:
    class _State(Enum):
        IDLE = "idle"
        RUNNING = "running"
        CLOSING = "closing"
        CLOSED = "closed"

    def __init__(self, popen_factory: Callable[..., subprocess.Popen] | None = None):
        self._popen_factory = popen_factory or subprocess.Popen
        self._state = self._State.IDLE
        self._state_lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[str, queue.Queue] = {}
        self._events: queue.Queue[tuple[int, dict[str, Any]]] = queue.Queue()
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._generation = 0

    def _get_generation(self) -> int:
        with self._state_lock:
            return self._generation

    def current_generation(self) -> int:
        return self._get_generation()

    def _bump_generation(self) -> int:
        with self._state_lock:
            self._generation += 1
            return self._generation

    def start(self, command: list[str], cwd: Path, env: dict[str, str]) -> None:
        with self._state_lock:
            if self._state != self._State.IDLE:
                raise PiTransportError(f"cannot start from state {self._state.name}")
        proc = self._popen_factory(
            command,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        self._proc = proc
        self._reader_thread = threading.Thread(target=self._reader, daemon=True)
        self._stderr_thread = threading.Thread(target=self._stderr_reader, daemon=True)
        with self._state_lock:
            self._state = self._State.RUNNING
        self._reader_thread.start()
        self._stderr_thread.start()

    def wake_events(self, reason: str) -> None:
        self._events.put((self._get_generation(), {"type": "_transport_wakeup", "reason": reason}))

    @staticmethod
    def _is_terminal_wakeup(event: dict[str, Any]) -> bool:
        return event.get("type") == "_transport_wakeup" and event.get("reason") in {"closed", "closing"}

    def _route_message(self, msg: dict[str, Any]) -> None:
        msg_id = msg.get("id")
        if msg.get("type") == "response" and msg_id:
            with self._pending_lock:
                response_q = self._pending.pop(str(msg_id), None)
            if response_q is not None:
                response_q.put(msg)
                return
        self._events.put((self._get_generation(), msg))

    def _reader(self) -> None:
        try:
            proc = self._proc
            stdout = getattr(proc, "stdout", None)
            if stdout is None:
                return
            for raw_line in stdout:
                line = raw_line.rstrip("\n")
                if line.endswith("\r"):
                    line = line[:-1]
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(msg, dict):
                    self._route_message(msg)
        finally:
            self._mark_closed("closed")

    def _stderr_reader(self) -> None:
        proc = self._proc
        stderr = getattr(proc, "stderr", None)
        if stderr is None:
            return
        for _line in stderr:
            pass

    def _mark_closed(self, reason: str) -> None:
        with self._state_lock:
            if self._state == self._State.RUNNING:
                self._state = self._State.CLOSED
                self._generation += 1
            generation = self._generation
        with self._pending_lock:
            queues = list(self._pending.values())
            self._pending.clear()
        for response_q in queues:
            try:
                response_q.put({"type": "response", "success": False, "error": "transport closed"})
            except queue.Full:
                pass
        self._events.put((generation, {"type": "_transport_wakeup", "reason": reason}))

    def send(self, command: dict[str, Any], timeout: float = 5.0) -> dict[str, Any]:
        with self._state_lock:
            if self._state != self._State.RUNNING:
                raise PiTransportError(f"transport not running (state={self._state.name})")
        request_id = uuid.uuid4().hex[:8]
        payload = {**command, "id": request_id}
        response_q: queue.Queue = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._pending[request_id] = response_q
        try:
            with self._write_lock:
                proc = self._proc
                if proc is None or proc.stdin is None:
                    raise PiTransportError("transport process not available")
                proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                proc.stdin.flush()
            result = response_q.get(timeout=timeout)
            if result.get("success") is False:
                raise PiTransportError(str(result.get("error", "rpc command failed")))
            return result
        except BrokenPipeError as exc:
            raise PiTransportError("broken pipe") from exc
        except queue.Empty as exc:
            raise PiTransportError("command timeout") from exc
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def get_event(self, expected_generation: int, timeout: float = 5.0) -> tuple[int, dict[str, Any]] | None:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                generation, event = self._events.get(timeout=remaining)
            except queue.Empty:
                return None
            if generation == expected_generation or self._is_terminal_wakeup(event):
                return generation, event

    def close(self) -> None:
        with self._state_lock:
            if self._state not in {self._State.RUNNING, self._State.IDLE}:
                return
            self._state = self._State.CLOSING
            proc = self._proc
            self._proc = None
        with self._pending_lock:
            queues = list(self._pending.values())
            self._pending.clear()
        for response_q in queues:
            try:
                response_q.put({"type": "response", "success": False, "error": "transport closing"})
            except queue.Full:
                pass
        self.wake_events("closing")
        if proc is not None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=2)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        if self._reader_thread and self._reader_thread is not threading.current_thread():
            self._reader_thread.join(timeout=2)
        if self._stderr_thread and self._stderr_thread is not threading.current_thread():
            self._stderr_thread.join(timeout=2)
        with self._state_lock:
            self._state = self._State.CLOSED


VALID_ACTIONS = {"stop", "cancel", "stand", "resume"}


def _build_prompt_text(request: AgentRequest) -> str:
    context_parts = [
        f"session_id: {request.session_id}",
        f"motion_backend: {request.motion_backend}",
    ]
    if request.robot_mode:
        context_parts.append(f"robot_mode: {request.robot_mode}")
    if request.safety_state:
        context_parts.append(f"safety_state: {request.safety_state}")
    if request.health_state:
        context_parts.append(f"health_state: {request.health_state}")
    return f"Robot context:\n{chr(10).join(context_parts)}\n\nUser said: {request.text}"


def _extract_reply_text(events: list[dict[str, Any]]) -> str | None:
    for event in reversed(events):
        if event.get("type") != "agent_end":
            continue
        for msg in reversed(event.get("messages", [])):
            if msg.get("role") == "assistant":
                parts = [
                    block.get("text", "")
                    for block in msg.get("content", [])
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                text = " ".join(part for part in parts if part).strip()
                return text or None
    return None


def _build_agent_result(pending_tools: dict[str, dict[str, Any]], reply_text: str | None) -> AgentResult:
    commands: list[AgentCommand] = []
    led_params: dict[str, Any] | None = None
    for item in sorted(pending_tools.values(), key=lambda value: int(value["order"])):
        if not item.get("confirmed"):
            continue
        tool_name = item["tool_name"]
        kind = item["kind"]
        if tool_name == "robot_stop":
            commands.append(AgentCommand(kind="action", params={"action": "stop"}))
        elif kind == "led":
            led_params = dict(item.get("params", {}))
        else:
            commands.append(AgentCommand(kind=kind, params=dict(item.get("params", {}))))
    return AgentResult(commands=commands, reply_text=reply_text, led=led_params)


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def _validate_and_clamp_loco(params: dict[str, Any], config: VoiceBridgeConfig) -> dict[str, float] | None:
    vx = _finite_float(params.get("vx", 0))
    vy = _finite_float(params.get("vy", 0))
    vyaw = _finite_float(params.get("vyaw", 0))
    duration_sec = _finite_float(params.get("duration_sec", 0))
    if vx is None or vy is None or vyaw is None or duration_sec is None:
        return None
    defaults = config.motion_defaults
    return {
        "vx": max(-float(defaults["default_vx"]), min(float(defaults["default_vx"]), vx)),
        "vy": max(-float(defaults["default_vy"]), min(float(defaults["default_vy"]), vy)),
        "vyaw": max(-float(defaults["default_vyaw"]), min(float(defaults["default_vyaw"]), vyaw)),
        "duration_sec": max(0.1, min(float(defaults["max_motion_duration_sec"]), duration_sec)),
    }


def _validate_action(params: dict[str, Any]) -> dict[str, str]:
    action = str(params.get("action", "stop"))
    return {"action": action if action in VALID_ACTIONS else "stop"}


def _validate_led(params: dict[str, Any]) -> dict[str, Any] | None:
    r = _finite_float(params.get("r", 0))
    g = _finite_float(params.get("g", 0))
    b = _finite_float(params.get("b", 0))
    ttl_sec = _finite_float(params.get("ttl_sec", 1.0))
    if r is None or g is None or b is None or ttl_sec is None:
        return None
    return {
        "r": max(0, min(255, int(r))),
        "g": max(0, min(255, int(g))),
        "b": max(0, min(255, int(b))),
        "ttl_sec": max(0.1, min(30.0, ttl_sec)),
    }


def _validate_textop(params: dict[str, Any], config: VoiceBridgeConfig) -> dict[str, Any] | None:
    prompt = params.get("prompt")
    duration_sec = _finite_float(params.get("duration_sec"))
    normalized_prompt = " ".join(prompt.strip().split()) if isinstance(prompt, str) else ""
    if (
        not normalized_prompt
        or len(normalized_prompt) > 100
        or re.fullmatch(r"[A-Za-z][A-Za-z -]*", normalized_prompt) is None
        or duration_sec is None
    ):
        return None
    max_duration = float(config.motion_defaults["max_textop_duration_sec"])
    return {
        "prompt": normalized_prompt,
        "duration_sec": max(0.16, min(max_duration, duration_sec)),
    }


def _sanitize_tts(text: object) -> str | None:
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    return stripped[:200] if stripped else None


def _safety_allows_motion(safety_state: str | None) -> bool:
    return (safety_state or "").lower() not in {"emergency", "estop", "fault", "unsafe"}


def _finalize_agent_result(result: AgentResult, request: AgentRequest, config: VoiceBridgeConfig) -> AgentResult:
    motion_candidates: list[AgentCommand] = []
    non_motion: list[AgentCommand] = []
    for command in result.commands:
        if command.kind == "loco":
            params = _validate_and_clamp_loco(command.params, config)
            if params is not None and request.motion_backend == "official_loco":
                motion_candidates.append(AgentCommand(kind="loco", params=params))
        elif command.kind == "textop":
            params = _validate_textop(command.params, config)
            if params is not None and request.motion_backend == "textop":
                motion_candidates.append(AgentCommand(kind="textop", params=params))
        elif command.kind == "action":
            motion_candidates.append(AgentCommand(kind="action", params=_validate_action(command.params)))
        elif command.kind == "say":
            text = _sanitize_tts(command.params.get("text"))
            if text is not None:
                non_motion.append(AgentCommand(kind="say", params={"text": text}))
    if _safety_allows_motion(request.safety_state):
        allowed_motion = motion_candidates
    else:
        allowed_motion = [
            command
            for command in motion_candidates
            if command.kind == "action" and command.params.get("action") in {"stop", "cancel"}
        ]
    commands = allowed_motion + non_motion
    led = _validate_led(result.led) if result.led else None
    reply_text = _sanitize_tts(result.reply_text) if result.reply_text else None
    return AgentResult(commands=commands, reply_text=reply_text, led=led)


class PiRpcAgentClient:
    def __init__(
        self,
        config: VoiceBridgeConfig,
        repo_root: Path | None = None,
        transport_factory: Callable[[], PiRpcTransport] = PiRpcTransport,
    ):
        self._config = config
        self._pi_config = deepcopy(DEFAULT_PI_CONFIG)
        self._pi_config.update(config.agent.get("pi", {}))
        self._timeouts = dict(DEFAULT_PI_TIMEOUTS)
        self._timeouts.update(self._pi_config.get("timeouts", {}))
        self._repo_root = repo_root or resolve_repo_root()
        self._workspace = resolve_workspace(self._pi_config, self._repo_root)
        self._transport_factory = transport_factory
        self._transport: PiRpcTransport | None = None
        self._startup_lock = threading.Lock()
        self._shutdown_lock = threading.Lock()
        self._aborted = threading.Event()
        self._pi_session_id: str | None = None
        self._last_activity = 0.0

    def _ensure_transport(self) -> PiRpcTransport:
        with self._startup_lock:
            if self._transport is not None:
                return self._transport
            transport = self._transport_factory()
            command = build_pi_command(self._pi_config, self._workspace, repo_root=self._repo_root)
            self._workspace.mkdir(parents=True, exist_ok=True)
            transport.start(command, self._workspace, scrubbed_env(self._pi_config))
            transport.send({"type": "get_state"}, timeout=float(self._timeouts["startup_health_sec"]))
            self._transport = transport
            return transport

    def _ensure_session(self, transport: PiRpcTransport) -> None:
        idle_timeout = float(self._config.voice["idle_timeout_sec"])
        now = time.monotonic()
        if self._pi_session_id is not None and now - self._last_activity <= idle_timeout:
            return
        if self._pi_session_id is not None:
            response = transport.send({"type": "new_session"}, timeout=float(self._timeouts["command_response_sec"]))
            if response.get("data", {}).get("cancelled"):
                self._pi_session_id = None
                return
        state = transport.send({"type": "get_state"}, timeout=float(self._timeouts["command_response_sec"]))
        self._pi_session_id = state.get("data", {}).get("sessionId")

    def abort(self) -> None:
        self._aborted.set()
        transport = self._transport
        if transport is None:
            return
        transport.wake_events("aborted")

        def _send_abort() -> None:
            try:
                transport.send({"type": "abort"}, timeout=1.0)
            except PiTransportError:
                pass

        threading.Thread(target=_send_abort, daemon=True).start()

    def close(self) -> None:
        with self._shutdown_lock:
            transport = self._transport
            self._transport = None
        if transport is not None:
            transport.close()

    def decide(self, request: AgentRequest) -> AgentResult:
        self._aborted.clear()
        pending_tools: dict[str, dict[str, Any]] = {}
        events: list[dict[str, Any]] = []
        normal_completion = False
        try:
            transport = self._ensure_transport()
            self._ensure_session(transport)
            generation = transport.current_generation()
            transport.send(
                {"type": "prompt", "message": _build_prompt_text(request)},
                timeout=float(self._timeouts["command_response_sec"]),
            )
            hard_deadline = time.monotonic() + float(self._timeouts["conversational_turn_sec"])
            while not self._aborted.is_set():
                if transport.current_generation() != generation:
                    break
                remaining = hard_deadline - time.monotonic()
                if remaining <= 0:
                    self.abort()
                    break
                event_item = transport.get_event(generation, timeout=min(1.0, remaining))
                if event_item is None:
                    continue
                _generation, event = event_item
                if event.get("type") == "_transport_wakeup":
                    break
                events.append(event)
                event_type = event.get("type")
                if event_type == "tool_execution_start":
                    tool_name = str(event.get("toolName", ""))
                    if tool_name in CUSTOM_TOOLS and isinstance(event.get("toolCallId"), str):
                        pending_tools[str(event["toolCallId"])] = {
                            "order": len(pending_tools),
                            "tool_name": tool_name,
                            "kind": CUSTOM_TOOLS[tool_name],
                            "params": event.get("args", {}) if isinstance(event.get("args"), dict) else {},
                            "confirmed": False,
                        }
                elif event_type == "tool_execution_end":
                    if event.get("isError", False):
                        continue
                    tool_call_id = str(event.get("toolCallId", ""))
                    if tool_call_id in pending_tools:
                        pending_tools[tool_call_id]["confirmed"] = True
                elif event_type == "agent_end":
                    if event.get("willRetry") is True:
                        continue
                    normal_completion = True
                    break
        except PiTransportError:
            self.close()
            return AgentResult()
        finally:
            self._aborted.clear()
        if not normal_completion:
            return AgentResult(reply_text=_sanitize_tts(_extract_reply_text(events)))
        result = _build_agent_result(pending_tools, _extract_reply_text(events))
        finalized = _finalize_agent_result(result, request, self._config)
        self._last_activity = time.monotonic()
        return finalized
