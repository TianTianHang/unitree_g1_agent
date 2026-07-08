from __future__ import annotations

import json
import queue
from datetime import datetime, timezone
from typing import Any, Callable

from voice_bridge_debug.config import DebugPanelConfig
from voice_bridge_debug.state import PanelState, normalize_health, parse_json_topic


def _load_ros_messages():
    from diagnostic_msgs.msg import DiagnosticArray
    from std_msgs.msg import String

    return {"DiagnosticArray": DiagnosticArray, "String": String}


class DebugBridgeNode:
    def __init__(
        self,
        node,
        config: DebugPanelConfig,
        state: PanelState,
        asr_publish_queue: queue.Queue,
        notify_web: Callable[[dict[str, Any]], None],
    ):
        self.node = node
        self.config = config
        self.state = state
        self.asr_publish_queue = asr_publish_queue
        self.notify_web = notify_web
        self.msg = _load_ros_messages()
        topics = config.topics
        self.asr_pub = node.create_publisher(self.msg["String"], topics["asr"], 10)
        node.create_subscription(self.msg["String"], topics["voice_state"], self.on_voice_state, 10)
        node.create_subscription(self.msg["String"], topics["voice_debug_events"], self.on_voice_debug_event, 10)
        node.create_subscription(self.msg["String"], topics["robot_mode"], self.on_robot_mode, 10)
        node.create_subscription(self.msg["String"], topics["safety_state"], self.on_safety_state, 10)
        node.create_subscription(self.msg["DiagnosticArray"], topics["health"], self.on_health, 10)
        node.create_subscription(
            self.msg["String"],
            topics["voice_cmd_loco"],
            lambda msg: self.on_string_event("cmd_loco", "command_published", msg),
            10,
        )
        node.create_subscription(
            self.msg["String"],
            topics["voice_cmd_action"],
            lambda msg: self.on_string_event("cmd_action", "command_published", msg),
            10,
        )
        node.create_subscription(
            self.msg["String"],
            topics["tts"],
            lambda msg: self.on_string_event("tts", "tts_published", msg),
            10,
        )
        node.create_subscription(
            self.msg["String"],
            topics["led"],
            lambda msg: self.on_string_event("led", "led_published", msg),
            10,
        )
        node.create_subscription(
            self.msg["String"],
            topics["safe_cmd_loco"],
            lambda msg: self.on_string_event("safe_cmd_loco", "safe_command_published", msg),
            10,
        )
        node.create_subscription(
            self.msg["String"],
            topics["safe_cmd_stop"],
            lambda msg: self.on_string_event("safe_cmd_stop", "safe_stop_published", msg),
            10,
        )
        node.create_subscription(
            self.msg["String"],
            topics["safety_decisions"],
            lambda msg: self.on_string_event("safety_decision", "safety_decision", msg),
            10,
        )
        node.create_timer(0.05, self.drain_asr_queue)

    def _now_sec(self) -> float:
        return self.node.get_clock().now().nanoseconds / 1_000_000_000.0

    def drain_asr_queue(self) -> None:
        while True:
            try:
                request = self.asr_publish_queue.get_nowait()
            except queue.Empty:
                return
            payload = dict(request)
            payload["stamp"] = datetime.now(timezone.utc).isoformat()
            msg = self.msg["String"]()
            msg.data = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            self.asr_pub.publish(msg)

    def on_voice_state(self, msg) -> None:
        parsed = parse_json_topic(msg.data)
        data = parsed.get("data")
        if isinstance(data, dict):
            session = data.get("session")
            self.state.set_robot_state(
                voice_session=session if isinstance(session, dict) else None,
                last_asr_text=data.get("last_asr_text"),
                last_decision=data.get("last_decision"),
                last_error=data.get("last_error"),
                agent_backend=data.get("agent_backend"),
            )
        else:
            self.state.push_event("voice_state", "parse_error", parsed, timestamp=self._now_sec())

    def on_voice_debug_event(self, msg) -> None:
        parsed = parse_json_topic(msg.data)
        data = parsed.get("data")
        if not isinstance(data, dict):
            self.state.push_event("voice_debug", "parse_error", parsed, timestamp=self._now_sec())
            return
        event = str(data.get("event", "unknown"))
        session_id = data.get("session_id") if isinstance(data.get("session_id"), str) else None
        event_data = data.get("data") if isinstance(data.get("data"), dict) else {}
        timestamp = float(data.get("timestamp", self._now_sec()))
        self.state.push_event("voice_debug", event, event_data, session_id=session_id, timestamp=timestamp)
        if event == "agent_started":
            self.state.set_agent_result(
                {
                    "status": "pending",
                    "session_id": session_id,
                    "request_text": event_data.get("text"),
                    "backend": event_data.get("backend"),
                    "started_at": timestamp,
                    "commands": [],
                    "reply_text": None,
                    "led": None,
                    "requires_confirmation": False,
                }
            )
        elif event == "agent_result":
            result = {
                "status": "complete",
                "session_id": session_id,
                "completed_at": timestamp,
                "commands": event_data.get("commands", []),
                "reply_text": event_data.get("reply_text"),
                "led": event_data.get("led"),
                "requires_confirmation": bool(event_data.get("requires_confirmation", False)),
            }
            self.state.set_agent_result(result)
        elif event == "agent_error":
            self.state.set_agent_result(
                {
                    "status": "error",
                    "session_id": session_id,
                    "completed_at": timestamp,
                    "commands": [],
                    "reply_text": event_data.get("fallback_reply_text"),
                    "led": None,
                    "requires_confirmation": False,
                    "error": event_data.get("error"),
                }
            )

    def on_robot_mode(self, msg) -> None:
        self.state.set_robot_state(robot_mode=parse_json_topic(msg.data))

    def on_safety_state(self, msg) -> None:
        self.state.set_robot_state(safety_state=parse_json_topic(msg.data))

    def on_health(self, msg) -> None:
        stale_after = self.config.timeline["state_timeout_ms"] / 1000.0
        self.state.set_robot_state(health=normalize_health(msg, self._now_sec(), stale_after, self.state.health))

    def on_string_event(self, source: str, kind: str, msg) -> None:
        self.state.push_event(source, kind, parse_json_topic(msg.data), timestamp=self._now_sec())
