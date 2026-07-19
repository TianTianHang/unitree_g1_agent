from __future__ import annotations

import json
import math
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol, TypeGuard

from voice_bridge.agent import AgentClient, build_agent_client
from voice_bridge.config import VoiceBridgeConfig
from voice_bridge.intent import VoiceSession, new_session_id
from voice_bridge.internal_types import AgentCommand, AgentRequest, AgentResult, SessionDecision
from voice_bridge.ros_converters import action_intent, asr_event, loco_intent


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def diagnostic_level_to_int(level: Any) -> int | None:
    if level is None:
        return None
    if isinstance(level, bytes | bytearray | memoryview):
        raw = bytes(level)
        return raw[0] if raw else None
    return int(level)


class CloseableAgent(Protocol):
    def abort(self) -> None:
        ...

    def close(self) -> None:
        ...


def _supports_closeable(agent: object) -> TypeGuard[CloseableAgent]:
    return hasattr(agent, "abort") and hasattr(agent, "close")


COMMAND_SCHEMA_VERSION = "voice_command.v1"
DEBUG_EVENT_SCHEMA_VERSION = "voice_debug_event.v1"


def build_debug_event(
    event: str,
    session_id: str | None,
    data: dict[str, Any],
    *,
    timestamp: float,
) -> dict[str, Any]:
    return {
        "schema_version": DEBUG_EVENT_SCHEMA_VERSION,
        "timestamp": float(timestamp),
        "session_id": session_id,
        "event": event,
        "data": data,
    }


def build_loco_payload(
    command: AgentCommand,
    session_id: str,
    command_id: str,
    text: str,
    *,
    created_at: float,
) -> dict[str, Any]:
    params = command.params
    required = ["vx", "vy", "vyaw", "duration_sec"]
    missing = [field for field in required if field not in params]
    if missing:
        raise ValueError(f"missing loco field: {', '.join(missing)}")
    return {
        "schema_version": COMMAND_SCHEMA_VERSION,
        "source": "voice_bridge",
        "session_id": session_id,
        "command_id": command_id,
        "created_at": float(created_at),
        "text": text,
        "vx": float(params["vx"]),
        "vy": float(params["vy"]),
        "vyaw": float(params["vyaw"]),
        "duration_sec": float(params["duration_sec"]),
    }


def build_action_payload(
    action: str,
    session_id: str,
    command_id: str,
    text: str,
    *,
    created_at: float,
    priority: str = "normal",
) -> dict[str, Any]:
    return {
        "schema_version": COMMAND_SCHEMA_VERSION,
        "source": "voice_bridge",
        "session_id": session_id,
        "command_id": command_id,
        "created_at": float(created_at),
        "action": action,
        "priority": priority,
        "text": text,
    }


def _time_to_sec(value) -> float:
    return float(value.sec) + float(value.nanosec) / 1_000_000_000.0


def _duration_to_sec(value) -> float:
    return float(value.sec) + float(value.nanosec) / 1_000_000_000.0


def _loco_intent_debug_payload(msg) -> dict[str, Any]:
    return {
        "schema_version": COMMAND_SCHEMA_VERSION,
        "source": msg.source,
        "session_id": msg.session_id,
        "command_id": msg.command_id,
        "created_at": _time_to_sec(msg.created_at),
        "text": msg.text,
        "vx": msg.vx,
        "vy": msg.vy,
        "vyaw": msg.vyaw,
        "duration_sec": _duration_to_sec(msg.duration),
    }


def _action_intent_debug_payload(msg) -> dict[str, Any]:
    return {
        "schema_version": COMMAND_SCHEMA_VERSION,
        "source": msg.source,
        "session_id": msg.session_id,
        "command_id": msg.command_id,
        "created_at": _time_to_sec(msg.created_at),
        "action": msg.action,
        "priority": msg.priority,
        "text": msg.text,
    }


def build_tts_payload(text: str, session_id: str | None, *, interrupt: bool = True) -> dict[str, Any]:
    return {
        "source": "voice_bridge",
        "session_id": session_id,
        "text": text,
        "speaker_id": 0,
        "interrupt": interrupt,
    }


def build_led_payload(led: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "voice_bridge",
        "r": int(led.get("r", 0)),
        "g": int(led.get("g", 0)),
        "b": int(led.get("b", 0)),
        "ttl_sec": float(led.get("ttl_sec", 1.0)),
    }


def diagnostic_summary(msg) -> str:
    statuses = []
    for status in getattr(msg, "status", []):
        statuses.append(
            {
                "name": getattr(status, "name", ""),
                "level": diagnostic_level_to_int(getattr(status, "level", None)),
                "message": getattr(status, "message", ""),
            }
        )
    return _json({"status": statuses})


class AgentRequestState:
    def __init__(self):
        self._generation = 0
        self._session_id: str | None = None
        self._lock = threading.Lock()

    def start(self, session_id: str) -> int:
        with self._lock:
            self._generation += 1
            self._session_id = session_id
            return self._generation

    def invalidate(self) -> None:
        with self._lock:
            self._generation += 1
            self._session_id = None

    def is_current(self, generation: int, session_id: str) -> bool:
        with self._lock:
            return self._generation == generation and self._session_id == session_id


def _load_ros_messages():
    from diagnostic_msgs.msg import DiagnosticArray
    from std_msgs.msg import String

    from g1_agent_msgs.action import ExecuteMotion
    from g1_agent_msgs.msg import ActionIntent, LocoIntent, RobotStateSummary, SafetyStatus, VoiceEvent

    return {
        "ActionIntent": ActionIntent,
        "DiagnosticArray": DiagnosticArray,
        "ExecuteMotion": ExecuteMotion,
        "LocoIntent": LocoIntent,
        "RobotStateSummary": RobotStateSummary,
        "SafetyStatus": SafetyStatus,
        "String": String,
        "VoiceEvent": VoiceEvent,
    }


class VoiceBridgeNode:
    def __init__(self, node, config: VoiceBridgeConfig, agent: AgentClient | None = None, textop_action_client=None):
        self.node = node
        self.config = config
        self.agent = agent or build_agent_client(config)
        self._closeable_agent = self.agent if _supports_closeable(self.agent) else None
        self.session = VoiceSession()
        self.msg = _load_ros_messages()
        self.command_counter = 0
        self._lock = threading.RLock()
        self._agent_requests = AgentRequestState()
        self._agent_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="voice_bridge_agent")
        self.textop_action_client = None
        if config.motion["backend"] == "textop":
            if textop_action_client is not None:
                self.textop_action_client = textop_action_client
            else:
                from rclpy.action import ActionClient

                self.textop_action_client = ActionClient(
                    node,
                    self.msg["ExecuteMotion"],
                    config.topics["textop_action"],
                )

        self.robot_mode: str | None = None
        self.safety_state: str | None = None
        self.health_state: str | None = None
        self.last_asr_text: str | None = None
        self.last_decision: dict[str, Any] | None = None
        self.last_error: str | None = None

        topics = config.topics
        self.loco_pub = node.create_publisher(self.msg["LocoIntent"], topics["voice_loco"], 10)
        self.action_pub = node.create_publisher(self.msg["ActionIntent"], topics["voice_action"], 10)
        self.tts_pub = node.create_publisher(self.msg["String"], topics["tts"], 10)
        self.led_pub = node.create_publisher(self.msg["String"], topics["led"], 10)
        self.state_pub = node.create_publisher(self.msg["String"], topics["voice_state"], 10)
        self.debug_pub = node.create_publisher(self.msg["String"], topics["debug_events"], 10)

        node.create_subscription(self.msg["VoiceEvent"], topics["asr"], self.on_asr, 10)
        node.create_subscription(self.msg["RobotStateSummary"], topics["robot_mode"], self.on_robot_mode, 10)
        node.create_subscription(self.msg["SafetyStatus"], topics["safety_state"], self.on_safety_state, 10)
        node.create_subscription(self.msg["DiagnosticArray"], topics["health"], self.on_health, 10)
        node.create_timer(1.0, self.publish_state)

    def _now_sec(self) -> float:
        return self.node.get_clock().now().nanoseconds / 1_000_000_000.0

    def _new_command_id(self, now_sec: float, suffix: str = "") -> str:
        with self._lock:
            self.command_counter += 1
            counter = self.command_counter
        base = f"{new_session_id(now_sec)}-{counter}"
        return f"{base}-{suffix}" if suffix else base

    def _publish_string(self, publisher, payload: dict[str, Any]) -> None:
        msg = self.msg["String"]()
        msg.data = _json(payload)
        publisher.publish(msg)

    def _publish_debug_event(self, event: str, session_id: str | None, data: dict[str, Any], now_sec: float) -> None:
        try:
            self._publish_string(self.debug_pub, build_debug_event(event, session_id, data, timestamp=now_sec))
        except Exception as exc:  # Debug telemetry must never affect command behavior.
            self.node.get_logger().warning(f"failed to publish voice debug event: {exc}")

    def _agent_result_to_debug_data(self, result: AgentResult) -> dict[str, Any]:
        return {
            "commands": [{"kind": command.kind, "params": dict(command.params)} for command in result.commands],
            "reply_text": result.reply_text,
            "led": result.led,
            "requires_confirmation": result.requires_confirmation,
        }

    def _publish_command_debug_event(
        self,
        topic: str,
        session_id: str | None,
        payload: dict[str, Any],
        now_sec: float,
    ) -> None:
        self._publish_debug_event("command_published", session_id, {"topic": topic, "payload": payload}, now_sec)

    def on_robot_mode(self, msg) -> None:
        self.robot_mode = msg.mode

    def on_safety_state(self, msg) -> None:
        self.safety_state = msg.robot_state.health_state

    def on_health(self, msg) -> None:
        self.health_state = diagnostic_summary(msg)

    def on_asr(self, msg) -> None:
        now_sec = self._now_sec()
        try:
            event = asr_event(msg)
            self._publish_debug_event(
                "asr_received",
                None,
                {
                    "text": event.text,
                    "confidence": event.confidence,
                    "is_final": event.is_final,
                    "source": event.source,
                    "stamp": event.stamp,
                },
                now_sec,
            )
            decision = self.session.handle_asr(event, self.config, now_sec)
        except (TypeError, ValueError) as exc:
            self.last_error = str(exc)
            self.publish_state()
            self.node.get_logger().warning(f"rejecting ASR event: {exc}")
            return

        self.last_asr_text = event.text
        self.last_decision = decision.to_dict()
        self._publish_debug_event("session_decision", decision.session_id, decision.to_dict(), now_sec)

        if decision.kind == "action":
            self._publish_action_decision(decision, now_sec)
        elif decision.kind == "agent":
            self._call_agent(event_confidence=event.confidence, decision=decision, now_sec=now_sec)

        self.publish_state()

    def _publish_action_decision(self, decision: SessionDecision, now_sec: float) -> None:
        session_id = decision.session_id or new_session_id(now_sec)
        action = decision.action or "stop"
        if action in {"stop", "cancel"}:
            self._agent_requests.invalidate()
        intent = action_intent(
            session_id=session_id,
            command_id=self._new_command_id(now_sec, action),
            text=decision.text or "",
            created_at=now_sec,
            action=action,
            priority="emergency" if action == "stop" else "normal",
        )
        self.action_pub.publish(intent)
        self._publish_command_debug_event(
            self.config.topics["voice_action"],
            session_id,
            _action_intent_debug_payload(intent),
            self._now_sec(),
        )
        if action in {"stop", "cancel"} and self._closeable_agent is not None:
            self._closeable_agent.abort()

    def _call_agent(self, event_confidence: float | None, decision: SessionDecision, now_sec: float) -> None:
        session_id = decision.session_id or new_session_id(now_sec)
        request = AgentRequest(
            session_id=session_id,
            text=decision.text or "",
            asr_confidence=event_confidence,
            robot_mode=self.robot_mode,
            safety_state=self.safety_state,
            health_state=self.health_state,
            motion_backend=str(self.config.motion["backend"]),
        )
        self._publish_debug_event(
            "agent_started",
            session_id,
            {
                "text": request.text,
                "backend": self.config.agent["backend"],
                "motion_backend": request.motion_backend,
                "robot_mode": self.robot_mode,
                "safety_state": self.safety_state,
            },
            now_sec,
        )
        generation = self._agent_requests.start(session_id)
        self._agent_executor.submit(self._run_agent_request, request, generation, now_sec)

    def _run_agent_request(self, request: AgentRequest, generation: int, request_sec: float) -> None:
        if not self._agent_requests.is_current(generation, request.session_id):
            return
        try:
            result = self.agent.decide(request)
            if not self._agent_requests.is_current(generation, request.session_id):
                return
            with self._lock:
                if not self._agent_requests.is_current(generation, request.session_id):
                    return
                self._publish_agent_result(result, request, request_sec)
                self.session.mark_agent_done(request_sec)
                self.last_error = None
            self.publish_state()
        except Exception as exc:  # P0: agent failures must not publish motion.
            if not self._agent_requests.is_current(generation, request.session_id):
                return
            with self._lock:
                if not self._agent_requests.is_current(generation, request.session_id):
                    return
                self.last_error = str(exc)
                self.session.mark_agent_failed(request_sec)
                self._publish_debug_event(
                    "agent_error",
                    request.session_id,
                    {"error": str(exc), "fallback_reply_text": "语音服务暂时不可用"},
                    request_sec,
                )
                self._publish_string(self.tts_pub, build_tts_payload("语音服务暂时不可用", request.session_id))
            self.node.get_logger().warning(f"agent request failed: {exc}")
            self.publish_state()

    def _publish_agent_result(self, result: AgentResult, request: AgentRequest, now_sec: float) -> None:
        self._publish_debug_event("agent_result", request.session_id, self._agent_result_to_debug_data(result), now_sec)
        for command in result.commands:
            publish_sec = self._now_sec()
            if command.kind == "loco":
                if self.config.motion["backend"] != "official_loco":
                    continue
                payload = build_loco_payload(
                    command,
                    session_id=request.session_id,
                    command_id=self._new_command_id(publish_sec, "loco"),
                    text=request.text,
                    created_at=publish_sec,
                )
                intent = loco_intent(
                    session_id=payload["session_id"],
                    command_id=payload["command_id"],
                    text=payload["text"],
                    created_at=payload["created_at"],
                    vx=payload["vx"],
                    vy=payload["vy"],
                    vyaw=payload["vyaw"],
                    duration_sec=payload["duration_sec"],
                )
                self.loco_pub.publish(intent)
                self._publish_command_debug_event(
                    self.config.topics["voice_loco"],
                    request.session_id,
                    _loco_intent_debug_payload(intent),
                    publish_sec,
                )
            elif command.kind == "textop":
                self._send_textop_goal(command, request, publish_sec)
            elif command.kind == "action":
                action = str(command.params.get("action", "stop"))
                intent = action_intent(
                    session_id=request.session_id,
                    command_id=self._new_command_id(publish_sec, action),
                    text=request.text,
                    created_at=publish_sec,
                    action=action,
                    priority="emergency" if action == "stop" else "normal",
                )
                self.action_pub.publish(intent)
                self._publish_command_debug_event(
                    self.config.topics["voice_action"],
                    request.session_id,
                    _action_intent_debug_payload(intent),
                    publish_sec,
                )
            elif command.kind == "say":
                text = str(command.params.get("text", ""))
                if text:
                    payload = build_tts_payload(text, request.session_id)
                    self._publish_string(self.tts_pub, payload)
                    self._publish_command_debug_event(
                        self.config.topics["tts"],
                        request.session_id,
                        payload,
                        publish_sec,
                    )
            elif command.kind == "led":
                payload = build_led_payload(command.params)
                self._publish_string(self.led_pub, payload)
                self._publish_command_debug_event(self.config.topics["led"], request.session_id, payload, publish_sec)

        if result.reply_text:
            payload = build_tts_payload(result.reply_text, request.session_id)
            self._publish_string(self.tts_pub, payload)
            self._publish_command_debug_event(self.config.topics["tts"], request.session_id, payload, self._now_sec())
        if result.led:
            payload = build_led_payload(result.led)
            self._publish_string(self.led_pub, payload)
            self._publish_command_debug_event(self.config.topics["led"], request.session_id, payload, self._now_sec())

    def _send_textop_goal(self, command: AgentCommand, request: AgentRequest, now_sec: float) -> None:
        if self.config.motion["backend"] != "textop" or self.textop_action_client is None:
            return
        prompt = command.params.get("prompt")
        raw_duration = command.params.get("duration_sec")
        try:
            duration_sec = float(raw_duration) if raw_duration is not None else math.nan
        except (TypeError, ValueError):
            duration_sec = math.nan
        normalized_prompt = " ".join(prompt.strip().split()) if isinstance(prompt, str) else ""
        if (
            not normalized_prompt
            or len(normalized_prompt) > 100
            or re.fullmatch(r"[A-Za-z][A-Za-z -]*", normalized_prompt) is None
            or not math.isfinite(duration_sec)
            or duration_sec <= 0
        ):
            self._publish_debug_event(
                "textop_goal_rejected", request.session_id, {"reason": "invalid_command"}, now_sec
            )
            return
        timeout = float(self.config.motion["textop_server_timeout_sec"])
        if not self.textop_action_client.wait_for_server(timeout_sec=timeout):
            self._publish_debug_event(
                "textop_goal_rejected", request.session_id, {"reason": "server_unavailable"}, now_sec
            )
            return
        goal = self.msg["ExecuteMotion"].Goal()
        goal.request_id = self._new_command_id(now_sec, "textop")
        goal.backend_id = "textop"
        goal.prompt = normalized_prompt
        goal.duration.sec = int(duration_sec)
        goal.duration.nanosec = int(round((duration_sec - int(duration_sec)) * 1_000_000_000))
        if goal.duration.nanosec == 1_000_000_000:
            goal.duration.sec += 1
            goal.duration.nanosec = 0
        future = self.textop_action_client.send_goal_async(goal)
        future.add_done_callback(lambda done: self._on_textop_goal_response(done, request.session_id, goal.request_id))
        self._publish_debug_event(
            "textop_goal_sent",
            request.session_id,
            {"request_id": goal.request_id, "prompt": goal.prompt, "duration_sec": duration_sec},
            now_sec,
        )

    def _on_textop_goal_response(self, future, session_id: str, request_id: str) -> None:
        now_sec = self._now_sec()
        try:
            goal_handle = future.result()
            if goal_handle is None or not goal_handle.accepted:
                self._publish_debug_event("textop_goal_rejected", session_id, {"request_id": request_id}, now_sec)
                return
            self._publish_debug_event("textop_goal_accepted", session_id, {"request_id": request_id}, now_sec)
            goal_handle.get_result_async().add_done_callback(
                lambda done: self._on_textop_result(done, session_id, request_id)
            )
        except Exception as exc:
            self._publish_debug_event(
                "textop_goal_failed", session_id, {"request_id": request_id, "reason": str(exc)}, now_sec
            )

    def _on_textop_result(self, future, session_id: str, request_id: str) -> None:
        now_sec = self._now_sec()
        try:
            response = future.result()
            result = response.result
            self._publish_debug_event(
                "textop_goal_completed" if result.success else "textop_goal_failed",
                session_id,
                {"request_id": request_id, "reason": result.reason, "status": response.status},
                now_sec,
            )
        except Exception as exc:
            self._publish_debug_event(
                "textop_goal_failed", session_id, {"request_id": request_id, "reason": str(exc)}, now_sec
            )

    def publish_state(self) -> None:
        with self._lock:
            payload = {
                "node": "voice_bridge",
                "session": self.session.snapshot(),
                "last_asr_text": self.last_asr_text,
                "last_decision": self.last_decision,
                "last_error": self.last_error,
                "agent_backend": self.config.agent["backend"],
                "motion_backend": self.config.motion["backend"],
            }
        self._publish_string(self.state_pub, payload)

    def shutdown(self) -> None:
        self._agent_requests.invalidate()
        if self._closeable_agent is not None:
            self._closeable_agent.close()
        self._agent_executor.shutdown(wait=False, cancel_futures=True)


def main(args=None):
    import rclpy

    rclpy.init(args=args)
    node = rclpy.create_node("voice_bridge_node")
    node.declare_parameter("config_path", "")
    node.declare_parameter("motion_backend", "")
    config_path = node.get_parameter("config_path").get_parameter_value().string_value
    config = VoiceBridgeConfig.from_yaml(config_path) if config_path else VoiceBridgeConfig.default()
    motion_backend = node.get_parameter("motion_backend").get_parameter_value().string_value
    if motion_backend:
        config = config.with_motion_backend(motion_backend)
    voice_bridge = VoiceBridgeNode(node=node, config=config)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            voice_bridge.shutdown()
            node.destroy_node()
        except KeyboardInterrupt:
            pass
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
