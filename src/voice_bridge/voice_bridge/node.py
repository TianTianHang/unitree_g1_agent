from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from voice_bridge.agent import AgentClient, build_agent_client
from voice_bridge.config import VoiceBridgeConfig
from voice_bridge.intent import VoiceSession, new_session_id, parse_asr_event
from voice_bridge.internal_types import AgentCommand, AgentRequest, AgentResult, SessionDecision


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def diagnostic_level_to_int(level: Any) -> int | None:
    if level is None:
        return None
    if isinstance(level, (bytes, bytearray, memoryview)):
        raw = bytes(level)
        return raw[0] if raw else None
    return int(level)


COMMAND_SCHEMA_VERSION = "voice_command.v1"


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

    return {
        "DiagnosticArray": DiagnosticArray,
        "String": String,
    }


class VoiceBridgeNode:
    def __init__(self, node, config: VoiceBridgeConfig, agent: AgentClient | None = None):
        self.node = node
        self.config = config
        self.agent = agent or build_agent_client(config)
        self.session = VoiceSession()
        self.msg = _load_ros_messages()
        self.command_counter = 0
        self._lock = threading.RLock()
        self._agent_requests = AgentRequestState()
        self._agent_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="voice_bridge_agent")

        self.robot_mode: str | None = None
        self.safety_state: str | None = None
        self.health_state: str | None = None
        self.last_asr_text: str | None = None
        self.last_decision: dict[str, Any] | None = None
        self.last_error: str | None = None

        topics = config.topics
        self.loco_pub = node.create_publisher(self.msg["String"], topics["voice_loco"], 10)
        self.action_pub = node.create_publisher(self.msg["String"], topics["voice_action"], 10)
        self.tts_pub = node.create_publisher(self.msg["String"], topics["tts"], 10)
        self.led_pub = node.create_publisher(self.msg["String"], topics["led"], 10)
        self.state_pub = node.create_publisher(self.msg["String"], topics["voice_state"], 10)

        node.create_subscription(self.msg["String"], topics["asr"], self.on_asr, 10)
        node.create_subscription(self.msg["String"], topics["robot_mode"], self.on_robot_mode, 10)
        node.create_subscription(self.msg["String"], topics["safety_state"], self.on_safety_state, 10)
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

    def on_robot_mode(self, msg) -> None:
        self.robot_mode = msg.data

    def on_safety_state(self, msg) -> None:
        self.safety_state = msg.data

    def on_health(self, msg) -> None:
        self.health_state = diagnostic_summary(msg)

    def on_asr(self, msg) -> None:
        now_sec = self._now_sec()
        try:
            event = parse_asr_event(msg.data)
            decision = self.session.handle_asr(event, self.config, now_sec)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self.last_error = str(exc)
            self.publish_state()
            self.node.get_logger().warning(f"rejecting ASR event: {exc}")
            return

        self.last_asr_text = event.text
        self.last_decision = decision.to_dict()

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
        payload = build_action_payload(
            action=action,
            session_id=session_id,
            command_id=self._new_command_id(now_sec, action),
            text=decision.text or "",
            created_at=now_sec,
            priority="emergency" if action == "stop" else "normal",
        )
        self._publish_string(self.action_pub, payload)

    def _call_agent(self, event_confidence: float | None, decision: SessionDecision, now_sec: float) -> None:
        session_id = decision.session_id or new_session_id(now_sec)
        request = AgentRequest(
            session_id=session_id,
            text=decision.text or "",
            asr_confidence=event_confidence,
            robot_mode=self.robot_mode,
            safety_state=self.safety_state,
            health_state=self.health_state,
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
                self._publish_string(self.tts_pub, build_tts_payload("语音服务暂时不可用", request.session_id))
            self.node.get_logger().warning(f"agent request failed: {exc}")
            self.publish_state()

    def _publish_agent_result(self, result: AgentResult, request: AgentRequest, now_sec: float) -> None:
        for command in result.commands:
            publish_sec = self._now_sec()
            if command.kind == "loco":
                payload = build_loco_payload(
                    command,
                    session_id=request.session_id,
                    command_id=self._new_command_id(publish_sec, "loco"),
                    text=request.text,
                    created_at=publish_sec,
                )
                self._publish_string(self.loco_pub, payload)
            elif command.kind == "action":
                action = str(command.params.get("action", "stop"))
                payload = build_action_payload(
                    action=action,
                    session_id=request.session_id,
                    command_id=self._new_command_id(publish_sec, action),
                    text=request.text,
                    created_at=publish_sec,
                    priority="emergency" if action == "stop" else "normal",
                )
                self._publish_string(self.action_pub, payload)
            elif command.kind == "say":
                text = str(command.params.get("text", ""))
                if text:
                    self._publish_string(self.tts_pub, build_tts_payload(text, request.session_id))
            elif command.kind == "led":
                self._publish_string(self.led_pub, build_led_payload(command.params))

        if result.reply_text:
            self._publish_string(self.tts_pub, build_tts_payload(result.reply_text, request.session_id))
        if result.led:
            self._publish_string(self.led_pub, build_led_payload(result.led))

    def publish_state(self) -> None:
        with self._lock:
            payload = {
                "node": "voice_bridge",
                "session": self.session.snapshot(),
                "last_asr_text": self.last_asr_text,
                "last_decision": self.last_decision,
                "last_error": self.last_error,
                "agent_backend": self.config.agent["backend"],
            }
        self._publish_string(self.state_pub, payload)

    def shutdown(self) -> None:
        self._agent_requests.invalidate()
        self._agent_executor.shutdown(wait=False, cancel_futures=True)


def main(args=None):
    import rclpy

    rclpy.init(args=args)
    node = rclpy.create_node("voice_bridge_node")
    node.declare_parameter("config_path", "")
    config_path = node.get_parameter("config_path").get_parameter_value().string_value
    config = VoiceBridgeConfig.from_yaml(config_path) if config_path else VoiceBridgeConfig.default()
    voice_bridge = VoiceBridgeNode(node=node, config=config)
    try:
        rclpy.spin(node)
    finally:
        voice_bridge.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
