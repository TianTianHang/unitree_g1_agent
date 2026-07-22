from __future__ import annotations

import math
import queue
from collections.abc import Callable
from typing import Any

from voice_bridge_debug.config import DebugPanelConfig
from voice_bridge_debug.ros_converters import (
    action_intent_to_dict,
    loco_intent_to_dict,
    robot_state_to_dict,
    safety_decision_to_dict,
    safety_status_to_dict,
    validated_action_to_dict,
    validated_loco_to_dict,
)
from voice_bridge_debug.state import PanelState, normalize_health, parse_json_topic


def _load_ros_messages():
    from diagnostic_msgs.msg import DiagnosticArray
    from std_msgs.msg import String

    from g1_agent_msgs.msg import (
        ActionIntent,
        LocoIntent,
        RobotStateSummary,
        SafetyDecision,
        SafetyStatus,
        ValidatedActionCommand,
        ValidatedLocoCommand,
        VoiceEvent,
    )

    return {
        "ActionIntent": ActionIntent,
        "DiagnosticArray": DiagnosticArray,
        "LocoIntent": LocoIntent,
        "RobotStateSummary": RobotStateSummary,
        "SafetyDecision": SafetyDecision,
        "SafetyStatus": SafetyStatus,
        "String": String,
        "ValidatedActionCommand": ValidatedActionCommand,
        "ValidatedLocoCommand": ValidatedLocoCommand,
        "VoiceEvent": VoiceEvent,
    }


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
        self.asr_pub = node.create_publisher(self.msg["VoiceEvent"], topics["asr"], 10)
        node.create_subscription(self.msg["String"], topics["voice_state"], self.on_voice_state, 10)
        node.create_subscription(self.msg["String"], topics["voice_debug_events"], self.on_voice_debug_event, 10)
        node.create_subscription(
            self.msg["RobotStateSummary"],
            topics["robot_mode"],
            self.on_robot_mode,
            10,
        )
        node.create_subscription(
            self.msg["SafetyStatus"],
            topics["safety_state"],
            self.on_safety_state,
            10,
        )
        node.create_subscription(self.msg["DiagnosticArray"], topics["health"], self.on_health, 10)
        node.create_subscription(
            self.msg["LocoIntent"],
            topics["voice_cmd_loco"],
            lambda msg: self.on_typed_event(
                "cmd_loco",
                "command_published",
                loco_intent_to_dict(msg),
            ),
            10,
        )
        node.create_subscription(
            self.msg["ActionIntent"],
            topics["voice_cmd_action"],
            lambda msg: self.on_typed_event(
                "cmd_action",
                "command_published",
                action_intent_to_dict(msg),
            ),
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
            self.msg["ValidatedLocoCommand"],
            topics["safe_cmd_loco"],
            lambda msg: self.on_typed_event(
                "safe_cmd_loco",
                "safe_command_published",
                validated_loco_to_dict(msg),
            ),
            10,
        )
        node.create_subscription(
            self.msg["ValidatedActionCommand"],
            topics["safe_cmd_stop"],
            lambda msg: self.on_typed_event(
                "safe_cmd_stop",
                "safe_stop_published",
                validated_action_to_dict(msg),
            ),
            10,
        )
        node.create_subscription(
            self.msg["SafetyDecision"],
            topics["safety_decisions"],
            lambda msg: self.on_typed_event(
                "safety_decision",
                "safety_decision",
                safety_decision_to_dict(msg),
            ),
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
            msg = self.msg["VoiceEvent"](
                stamp=self.node.get_clock().now().to_msg(),
                source=str(request.get("source", self.config.defaults["asr_source"])),
                event_type=str(getattr(self.msg["VoiceEvent"], "EVENT_ASR")),
                text=str(request.get("text", "")),
                is_final=bool(request.get("is_final", self.config.defaults["asr_is_final"])),
                language=str(request.get("language", "")),
            )
            confidence = request.get("confidence")
            if (
                not isinstance(confidence, bool)
                and isinstance(confidence, (int, float))
                and math.isfinite(float(confidence))
                and 0.0 <= float(confidence) <= 1.0
            ):
                msg.has_confidence = True
                msg.confidence = float(confidence)
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
        raw_event_data = data.get("data")
        event_data: dict[str, Any] = raw_event_data if isinstance(raw_event_data, dict) else {}
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
        self.state.set_robot_state(robot_mode=robot_state_to_dict(msg))

    def on_safety_state(self, msg) -> None:
        self.state.set_robot_state(safety_state=safety_status_to_dict(msg))

    def on_health(self, msg) -> None:
        stale_after = self.config.timeline["state_timeout_ms"] / 1000.0
        self.state.set_robot_state(health=normalize_health(msg, self._now_sec(), stale_after, self.state.health))

    def on_string_event(self, source: str, kind: str, msg) -> None:
        self.state.push_event(source, kind, parse_json_topic(msg.data), timestamp=self._now_sec())

    def on_typed_event(self, source: str, kind: str, data: dict[str, Any]) -> None:
        self.state.push_event(source, kind, data, timestamp=self._now_sec())
