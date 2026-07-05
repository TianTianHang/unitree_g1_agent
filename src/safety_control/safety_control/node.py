from __future__ import annotations

import json
from typing import Any

from safety_control.config import SafetyControlConfig
from safety_control.internal_types import ActionIntent, LocoIntent, RobotStateSnapshot, SafetyDecision, ValidatedCommand
from safety_control.state import RobotStateTracker
from safety_control.validator import RateLimiter, SafetyValidator, parse_action_intent, parse_loco_intent


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _load_ros_messages():
    from diagnostic_msgs.msg import DiagnosticArray
    from std_msgs.msg import String

    return {
        "DiagnosticArray": DiagnosticArray,
        "String": String,
    }


class SafetyControlNode:
    def __init__(self, node, config: SafetyControlConfig):
        self.node = node
        self.config = config
        self.msg = _load_ros_messages()
        self.state = RobotStateTracker(state_timeout_ms=int(config.safety["state_timeout_ms"]))
        self.validator = SafetyValidator(config)
        self.rate_limiters = {
            kind: RateLimiter(
                max_per_second=limits["max_per_second"],
                burst=limits["burst"],
            )
            for kind, limits in config.rate_limits.items()
        }

        self.allow_count = 0
        self.reject_count = 0
        self.last_decision: dict[str, Any] | None = None
        self.last_rejection_reason: str | None = None

        input_topics = config.topics["input"]
        output_topics = config.topics["output"]

        self.safe_loco_pub = node.create_publisher(self.msg["String"], output_topics["safe_loco"], 10)
        self.safe_stop_pub = node.create_publisher(self.msg["String"], output_topics["safe_stop"], 10)
        self.decisions_pub = node.create_publisher(self.msg["String"], output_topics["decisions"], 50)
        self.safety_state_pub = node.create_publisher(self.msg["String"], output_topics["safety_state"], 10)

        node.create_subscription(self.msg["String"], input_topics["loco_intent"], self.on_loco_intent, 10)
        node.create_subscription(self.msg["String"], input_topics["action_intent"], self.on_action_intent, 10)
        node.create_subscription(self.msg["String"], input_topics["robot_mode"], self.on_robot_mode, 10)
        node.create_subscription(self.msg["String"], input_topics["lowstate"], self.on_lowstate, 10)
        node.create_subscription(self.msg["DiagnosticArray"], input_topics["health"], self.on_health, 10)
        node.create_timer(0.5, self.publish_safety_state)

    def _now_sec(self) -> float:
        return self.node.get_clock().now().nanoseconds / 1_000_000_000.0

    def _publish_string(self, publisher, payload: dict[str, Any]) -> None:
        msg = self.msg["String"]()
        msg.data = _json(payload)
        publisher.publish(msg)

    def on_robot_mode(self, msg) -> None:
        try:
            self.state.update_from_mode_text(msg.data)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self.node.get_logger().warning(f"ignoring invalid robot mode state: {exc}")

    def on_lowstate(self, msg) -> None:
        try:
            self.state.update_from_lowstate_text(msg.data, self._now_sec())
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self.node.get_logger().warning(f"ignoring invalid lowstate summary: {exc}")

    def on_health(self, msg) -> None:
        self.state.update_from_health(msg, self._now_sec())

    def on_loco_intent(self, msg) -> None:
        start_sec = self._now_sec()
        snapshot = self.state.get_snapshot(start_sec)
        try:
            intent = parse_loco_intent(msg.data, start_sec)
            decision = self.validator.validate_loco(intent, snapshot, start_sec)
            if decision.allowed and not self.rate_limiters["loco"].allow(start_sec):
                decision = SafetyDecision.reject("command rate exceeded", {"rate_limited": True})

            if decision.allowed:
                self._publish_safe_loco(intent, decision, snapshot, start_sec)
                self.state.record_loco_command(intent, start_sec)
            else:
                self.node.get_logger().warning(f"rejecting loco intent: {decision.reason}")

            self._record_and_publish_decision(
                command_id=intent.command_id,
                command_kind="loco",
                decision=decision,
                robot_state=snapshot,
                validation_start_sec=start_sec,
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            decision = SafetyDecision.reject(f"invalid loco intent: {exc}")
            self.node.get_logger().warning(decision.reason)
            self._record_and_publish_decision(
                command_id=None,
                command_kind="loco",
                decision=decision,
                robot_state=snapshot,
                validation_start_sec=start_sec,
            )

    def on_action_intent(self, msg) -> None:
        start_sec = self._now_sec()
        snapshot = self.state.get_snapshot(start_sec)
        try:
            intent = parse_action_intent(msg.data, start_sec)
            decision = self.validator.validate_action(intent, snapshot, start_sec)
            if intent.action not in {"stop", "cancel"} and decision.allowed:
                if not self.rate_limiters["action"].allow(start_sec):
                    decision = SafetyDecision.reject("command rate exceeded", {"rate_limited": True})

            if decision.allowed and intent.action in {"stop", "cancel"}:
                self._publish_safe_stop(intent, decision, snapshot, start_sec)
                self.state.record_stop(start_sec)
            elif not decision.allowed:
                self.node.get_logger().warning(f"rejecting action intent: {decision.reason}")

            self._record_and_publish_decision(
                command_id=intent.command_id,
                command_kind="action",
                decision=decision,
                robot_state=snapshot,
                validation_start_sec=start_sec,
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            decision = SafetyDecision.reject(f"invalid action intent: {exc}")
            self.node.get_logger().warning(decision.reason)
            self._record_and_publish_decision(
                command_id=None,
                command_kind="action",
                decision=decision,
                robot_state=snapshot,
                validation_start_sec=start_sec,
            )

    def _publish_safe_loco(
        self,
        intent: LocoIntent,
        decision: SafetyDecision,
        snapshot: RobotStateSnapshot,
        now_sec: float,
    ) -> None:
        command = dict(intent.raw_command)
        command.update(
            {
                "vx": intent.vx,
                "vy": intent.vy,
                "vyaw": intent.vyaw,
                "duration_sec": intent.duration_sec,
            }
        )
        safe = ValidatedCommand(
            original_command=command,
            validation_timestamp=now_sec,
            safety_decision=decision,
            robot_state_snapshot=snapshot,
        )
        msg = self.msg["String"]()
        msg.data = safe.to_json()
        self.safe_loco_pub.publish(msg)

    def _publish_safe_stop(
        self,
        intent: ActionIntent,
        decision: SafetyDecision,
        snapshot: RobotStateSnapshot,
        now_sec: float,
    ) -> None:
        safe = ValidatedCommand(
            original_command=dict(intent.raw_command),
            validation_timestamp=now_sec,
            safety_decision=decision,
            robot_state_snapshot=snapshot,
        )
        msg = self.msg["String"]()
        msg.data = safe.to_json()
        self.safe_stop_pub.publish(msg)

    def _record_and_publish_decision(
        self,
        *,
        command_id: str | None,
        command_kind: str,
        decision: SafetyDecision,
        robot_state: RobotStateSnapshot,
        validation_start_sec: float,
    ) -> None:
        now_sec = self._now_sec()
        if decision.allowed:
            self.allow_count += 1
        else:
            self.reject_count += 1
            self.last_rejection_reason = decision.reason

        payload = {
            "timestamp": now_sec,
            "command_id": command_id,
            "command_kind": command_kind,
            "decision": "allow" if decision.allowed else "reject",
            "reason": decision.reason,
            "validation_time_ms": (now_sec - validation_start_sec) * 1000.0,
            "robot_state": robot_state.to_dict(),
            "check_details": decision.check_details or {},
        }
        self.last_decision = payload

        audit = self.config.audit
        should_publish = bool(audit["log_all_decisions"])
        if audit["log_rejected_only"] and decision.allowed:
            should_publish = False
        if should_publish:
            self._publish_string(self.decisions_pub, payload)

        self.publish_safety_state()

    def publish_safety_state(self) -> None:
        now_sec = self._now_sec()
        snapshot = self.state.get_snapshot(now_sec)
        total = self.allow_count + self.reject_count
        payload = {
            "node": "safety_control",
            "timestamp": now_sec,
            "enabled": self.config.safety["enabled"],
            "strict_mode": self.config.safety["strict_mode"],
            "robot_state": snapshot.to_dict(),
            "allow_count": self.allow_count,
            "reject_count": self.reject_count,
            "rejection_rate": (self.reject_count / total) if total else 0.0,
            "last_rejection_reason": self.last_rejection_reason,
            "last_decision": self.last_decision,
        }
        self._publish_string(self.safety_state_pub, payload)


def main(args=None):
    import rclpy

    rclpy.init(args=args)
    node = rclpy.create_node("safety_control_node")
    node.declare_parameter("config_path", "")
    config_path = node.get_parameter("config_path").get_parameter_value().string_value
    config = SafetyControlConfig.from_yaml(config_path) if config_path else SafetyControlConfig.default()
    SafetyControlNode(node=node, config=config)
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
