from __future__ import annotations

from diagnostic_msgs.msg import DiagnosticArray

from g1_agent_msgs.msg import (
    ActionIntent,
    LocoIntent,
    RobotStateSummary,
    SafetyDecision,
    SafetyStatus,
    ValidatedActionCommand,
    ValidatedLocoCommand,
)
from safety_control.config import SafetyControlConfig
from safety_control.internal_types import RobotStateSnapshot, ValidationResult
from safety_control.ros_converters import (
    decision_msg,
    safety_status_msg,
    validated_action_msg,
    validated_loco_msg,
)
from safety_control.state import RobotStateTracker
from safety_control.validator import RateLimiter, SafetyValidator


class SafetyControlNode:
    def __init__(self, node, config: SafetyControlConfig):
        self.node = node
        self.config = config
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
        self.last_decision: SafetyDecision | None = None
        self.last_rejection_reason: str | None = None

        input_topics = config.topics["input"]
        output_topics = config.topics["output"]

        self.safe_loco_pub = node.create_publisher(
            ValidatedLocoCommand,
            output_topics["safe_loco"],
            10,
        )
        self.safe_stop_pub = node.create_publisher(
            ValidatedActionCommand,
            output_topics["safe_stop"],
            10,
        )
        self.decisions_pub = node.create_publisher(
            SafetyDecision,
            output_topics["decisions"],
            50,
        )
        self.safety_state_pub = node.create_publisher(
            SafetyStatus,
            output_topics["safety_state"],
            10,
        )

        node.create_subscription(
            LocoIntent,
            input_topics["loco_intent"],
            self.on_loco_intent,
            10,
        )
        node.create_subscription(
            ActionIntent,
            input_topics["action_intent"],
            self.on_action_intent,
            10,
        )
        node.create_subscription(
            RobotStateSummary,
            input_topics["robot_mode"],
            self.on_robot_mode,
            10,
        )
        node.create_subscription(
            RobotStateSummary,
            input_topics["lowstate"],
            self.on_lowstate,
            10,
        )
        node.create_subscription(
            DiagnosticArray,
            input_topics["health"],
            self.on_health,
            10,
        )
        node.create_timer(0.5, self.publish_safety_state)

    def _now_sec(self) -> float:
        return self.node.get_clock().now().nanoseconds / 1_000_000_000.0

    def on_robot_mode(self, msg: RobotStateSummary) -> None:
        try:
            self.state.update_from_summary(msg, self._now_sec())
        except (TypeError, ValueError) as exc:
            self.node.get_logger().warning(f"ignoring invalid robot mode state: {exc}")

    def on_lowstate(self, msg: RobotStateSummary) -> None:
        try:
            self.state.update_from_summary(msg, self._now_sec())
        except (TypeError, ValueError) as exc:
            self.node.get_logger().warning(f"ignoring invalid lowstate summary: {exc}")

    def on_health(self, msg: DiagnosticArray) -> None:
        self.state.update_from_health(msg, self._now_sec())

    def on_loco_intent(self, intent: LocoIntent) -> None:
        start_sec = self._now_sec()
        snapshot = self.state.get_snapshot(start_sec)
        try:
            result = self.validator.validate_loco(intent, snapshot, start_sec)
            if result.allowed and not self.rate_limiters["loco"].allow(start_sec):
                result = ValidationResult.reject(
                    "command rate exceeded",
                    {"rate_limited": True},
                )

            decision = self._record_and_publish_decision(
                command_id=intent.command_id,
                command_kind=SafetyDecision.KIND_LOCO,
                result=result,
                robot_state=snapshot,
                validation_start_sec=start_sec,
            )
            if result.allowed:
                self.safe_loco_pub.publish(validated_loco_msg(intent, decision))
                self.state.record_loco_command(intent, start_sec)
            else:
                self._log_rejection("loco", result)
        except (TypeError, ValueError) as exc:
            result = ValidationResult.reject(f"invalid loco intent: {exc}")
            self._log_rejection("loco", result)
            self._record_and_publish_decision(
                command_id=getattr(intent, "command_id", ""),
                command_kind=SafetyDecision.KIND_LOCO,
                result=result,
                robot_state=snapshot,
                validation_start_sec=start_sec,
            )

    def on_action_intent(self, intent: ActionIntent) -> None:
        start_sec = self._now_sec()
        snapshot = self.state.get_snapshot(start_sec)
        try:
            result = self.validator.validate_action(intent, snapshot, start_sec)
            if (
                intent.action
                not in {
                    ActionIntent.ACTION_STOP,
                    ActionIntent.ACTION_CANCEL,
                }
                and result.allowed
            ):
                if not self.rate_limiters["action"].allow(start_sec):
                    result = ValidationResult.reject(
                        "command rate exceeded",
                        {"rate_limited": True},
                    )

            decision = self._record_and_publish_decision(
                command_id=intent.command_id,
                command_kind=SafetyDecision.KIND_ACTION,
                result=result,
                robot_state=snapshot,
                validation_start_sec=start_sec,
            )
            if result.allowed and intent.action in {
                ActionIntent.ACTION_STOP,
                ActionIntent.ACTION_CANCEL,
            }:
                self.safe_stop_pub.publish(validated_action_msg(intent, decision))
                self.state.record_stop(start_sec)
            elif not result.allowed:
                self._log_rejection("action", result)
        except (TypeError, ValueError) as exc:
            result = ValidationResult.reject(f"invalid action intent: {exc}")
            self._log_rejection("action", result)
            self._record_and_publish_decision(
                command_id=getattr(intent, "command_id", ""),
                command_kind=SafetyDecision.KIND_ACTION,
                result=result,
                robot_state=snapshot,
                validation_start_sec=start_sec,
            )

    def _log_rejection(self, command_kind: str, result: ValidationResult) -> None:
        details = f"; checks={result.check_details}" if result.check_details else ""
        self.node.get_logger().warning(f"rejecting {command_kind} intent: {result.reason}{details}")

    def _record_and_publish_decision(
        self,
        *,
        command_id: str,
        command_kind: str,
        result: ValidationResult,
        robot_state: RobotStateSnapshot,
        validation_start_sec: float,
    ) -> SafetyDecision:
        now_sec = self._now_sec()
        if result.allowed:
            self.allow_count += 1
        else:
            self.reject_count += 1
            self.last_rejection_reason = result.reason

        decision = decision_msg(
            command_id=command_id,
            command_kind=command_kind,
            result=result,
            snapshot=robot_state,
            stamp_sec=now_sec,
            latency_sec=now_sec - validation_start_sec,
        )
        self.last_decision = decision

        audit = self.config.audit
        should_publish = bool(audit["log_all_decisions"])
        if audit["log_rejected_only"] and result.allowed:
            should_publish = False
        if should_publish:
            self.decisions_pub.publish(decision)

        self.publish_safety_state()
        return decision

    def publish_safety_state(self) -> None:
        now_sec = self._now_sec()
        snapshot = self.state.get_snapshot(now_sec)
        self.safety_state_pub.publish(
            safety_status_msg(
                enabled=bool(self.config.safety["enabled"]),
                strict_mode=bool(self.config.safety["strict_mode"]),
                snapshot=snapshot,
                allow_count=self.allow_count,
                reject_count=self.reject_count,
                last_rejection_reason=self.last_rejection_reason,
                last_decision=self.last_decision,
                stamp_sec=now_sec,
            )
        )


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
    except KeyboardInterrupt:
        pass
    except RuntimeError as exc:
        if "Unable to convert call argument to Python object" not in str(exc):
            raise
        node.get_logger().warning("ROS message conversion interrupted during shutdown")
    finally:
        try:
            node.destroy_node()
        except KeyboardInterrupt:
            pass
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
