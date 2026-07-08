from __future__ import annotations

import json
import math
from typing import Any

from g1_interface.internal_types import SportCommand

SAFE_LOCO_LIMITS = {
    "vx": (-0.5, 0.5),
    "vy": (-0.3, 0.3),
    "vyaw": (-0.8, 0.8),
    "duration_sec": (0.01, 2.0),
}

STATE_SCHEMA_VERSION = "g1_state.v1"


def _bounded_float(payload: dict[str, Any], field: str) -> float:
    try:
        value = float(payload[field])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc

    if not math.isfinite(value):
        raise ValueError(f"{field} non-finite")

    low, high = SAFE_LOCO_LIMITS[field]
    if value < low or value > high:
        raise ValueError(f"{field} out of range")
    return value


def _require_validated_payload(payload: dict[str, Any], command_name: str) -> None:
    validation_result = payload.get("validation_result")
    if not isinstance(validation_result, dict):
        raise ValueError(f"{command_name} missing validation_result")
    if validation_result.get("allowed") is not True:
        raise ValueError(f"{command_name} not allowed by safety validation")


def parse_safe_loco_command(raw_json: str) -> SportCommand:
    payload = json.loads(raw_json)
    if not isinstance(payload, dict):
        raise ValueError("safe_loco payload must be a JSON object")
    _require_validated_payload(payload, "safe_loco")
    required = ["vx", "vy", "vyaw", "duration_sec"]
    missing = [field for field in required if field not in payload]
    if missing:
        raise ValueError(f"missing required loco field: {', '.join(missing)}")
    vx = _bounded_float(payload, "vx")
    vy = _bounded_float(payload, "vy")
    vyaw = _bounded_float(payload, "vyaw")
    duration_sec = _bounded_float(payload, "duration_sec")
    return SportCommand(
        action="set_velocity",
        params={
            "velocity": [vx, vy, vyaw],
            "duration": duration_sec,
        },
    )


def parse_stop_command(raw_json: str) -> SportCommand:
    payload = json.loads(raw_json)
    if not isinstance(payload, dict):
        raise ValueError("safe_stop payload must be a JSON object")
    _require_validated_payload(payload, "safe_stop")
    action = str(payload.get("action", "")).strip().lower()
    if action not in {"stop", "cancel"}:
        raise ValueError(f"safe_stop action must be stop or cancel: {action}")
    return SportCommand(action="set_velocity", params={"velocity": [0.0, 0.0, 0.0], "duration": 0.1})


def build_health_status(
    now_sec: float,
    last_lowstate_sec: float | None,
    state_timeout_sec: float,
    pending_api_count: int,
    last_api_result: dict[str, Any] | None,
) -> dict[str, Any]:
    if last_lowstate_sec is None:
        lowstate_age_ms = None
        state = "unhealthy"
    else:
        lowstate_age_ms = int(round((now_sec - last_lowstate_sec) * 1000))
        state = "ok" if now_sec - last_lowstate_sec <= state_timeout_sec else "degraded"

    return {
        "state": state,
        "lowstate_age_ms": lowstate_age_ms,
        "pending_api_count": pending_api_count,
        "last_api_result": last_api_result,
    }


def diagnostic_level_for_state(state: str) -> bytes:
    return b"\x00" if state == "ok" else b"\x01"


def normalize_audio_asr_message(raw_text: str) -> str | None:
    text = raw_text.strip()
    if not text:
        return None

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text

    if not isinstance(payload, dict):
        return None

    event_text = str(payload.get("text", "")).strip()
    if not event_text:
        return None

    return text


def build_low_state_payload(
    *,
    stamp_sec: float,
    source: str,
    mode: str | None,
    control_owner: str,
    mode_source: str,
    summary: Any,
    velocity: dict[str, float],
    sport_fsm_mode: int | None = None,
    sport_fsm_id: int | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "source": source,
        "stamp_sec": stamp_sec,
        "mode": mode,
        "control_owner": control_owner,
        "mode_source": mode_source,
        "sport_fsm_mode": sport_fsm_mode,
        "sport_fsm_id": sport_fsm_id,
        "rpy": summary.rpy,
        "quaternion": summary.quaternion,
        "gyroscope": summary.gyroscope,
        "accelerometer": summary.accelerometer,
        "motor_count": summary.motor_count,
        "max_temperature_c": summary.max_temperature_c,
        "battery_voltage": None,
        "velocity": {
            "vx": float(velocity.get("vx", 0.0)),
            "vy": float(velocity.get("vy", 0.0)),
            "vyaw": float(velocity.get("vyaw", 0.0)),
        },
        "velocity_source": "last_sport_command",
    }


def build_mode_payload(
    *,
    stamp_sec: float,
    source: str,
    mode: str | None,
    control_owner: str,
    mode_source: str,
    motor_count: int,
    sport_fsm_mode: int | None = None,
    sport_fsm_id: int | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "source": source,
        "stamp_sec": stamp_sec,
        "mode": mode,
        "control_owner": control_owner,
        "mode_source": mode_source,
        "sport_fsm_mode": sport_fsm_mode,
        "sport_fsm_id": sport_fsm_id,
        "motor_count": motor_count,
    }


def check_sport_command_allowed(
    now_sec: float,
    last_lowstate_sec: float | None,
    state_timeout_sec: float,
) -> tuple[bool, str | None]:
    if last_lowstate_sec is None:
        return False, "lowstate unavailable"

    age_ms = int(round((now_sec - last_lowstate_sec) * 1000))
    if now_sec - last_lowstate_sec > state_timeout_sec:
        return False, f"lowstate stale: age_ms={age_ms}"

    return True, None


def _load_ros_messages():
    from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
    from sensor_msgs.msg import Imu
    from std_msgs.msg import String
    from unitree_api.msg import Request, Response
    from unitree_hg.msg import IMUState, LowState

    return {
        "DiagnosticArray": DiagnosticArray,
        "DiagnosticStatus": DiagnosticStatus,
        "KeyValue": KeyValue,
        "Imu": Imu,
        "String": String,
        "Request": Request,
        "Response": Response,
        "IMUState": IMUState,
        "LowState": LowState,
    }


class G1InterfaceNode:
    def __init__(self, node, config):
        self.node = node
        self.config = config
        self.msg = _load_ros_messages()
        self.last_lowstate_sec = None
        self.last_api_result = None
        self.state_timeout_sec = config.timeouts["state_timeout_ms"] / 1000.0
        self.mode: str | None = None
        self.control_owner = "unknown"
        self.mode_source = "unavailable"
        self.sport_fsm_mode: int | None = None
        self.sport_fsm_id: int | None = None
        self.commanded_velocity = {"vx": 0.0, "vy": 0.0, "vyaw": 0.0}
        self.command_until_sec = 0.0

        from g1_interface.converters import imu_to_payload, lowstate_to_summary
        from g1_interface.sport_api import SportApiClient

        self._imu_to_payload = imu_to_payload
        self._lowstate_to_summary = lowstate_to_summary
        self._sport_api = SportApiClient(
            request_cls=self.msg["Request"],
            api_ids=config.sport_api["api_ids"],
            response_timeout_sec=config.timeouts["api_response_timeout_ms"] / 1000.0,
        )

        self.low_pub = node.create_publisher(self.msg["String"], "/g1/state/low", 10)
        self.motor_pub = node.create_publisher(self.msg["String"], "/g1/state/motors", 10)
        self.mode_pub = node.create_publisher(self.msg["String"], "/g1/state/mode", 10)
        self.health_pub = node.create_publisher(self.msg["DiagnosticArray"], "/g1/state/health", 10)
        self.imu_pub = node.create_publisher(self.msg["Imu"], "/g1/state/imu", 10)
        self.asr_pub = node.create_publisher(self.msg["String"], config.project_topics["asr"], 10)
        self.audio_event_pub = node.create_publisher(self.msg["String"], config.project_topics["audio_event"], 10)
        self.sport_request_pub = node.create_publisher(
            self.msg["Request"],
            config.native_topics["sport_request"],
            10,
        )

        node.create_subscription(
            self.msg["LowState"],
            config.native_topics["low_state"],
            self.on_lowstate,
            10,
        )
        node.create_subscription(
            self.msg["LowState"],
            config.native_topics["low_state_low_freq"],
            self.on_lowstate_low_freq,
            10,
        )
        node.create_subscription(
            self.msg["IMUState"],
            config.native_topics["secondary_imu"],
            self.on_secondary_imu,
            10,
        )
        node.create_subscription(
            self.msg["Response"],
            config.native_topics["sport_response"],
            self.on_sport_response,
            10,
        )
        node.create_subscription(
            self.msg["String"],
            config.native_topics["audio_msg"],
            self.on_audio_msg,
            10,
        )
        node.create_subscription(self.msg["String"], "/g1/safe_cmd/loco", self.on_safe_loco, 10)
        node.create_subscription(self.msg["String"], "/g1/safe_cmd/stop", self.on_safe_stop, 10)

        period = config.timeouts["health_publish_period_ms"] / 1000.0
        node.create_timer(period, self.publish_health)
        mode_query_period = config.timeouts["mode_query_period_ms"] / 1000.0
        node.create_timer(mode_query_period, self.query_sport_mode)

    def _now_sec(self):
        return self.node.get_clock().now().nanoseconds / 1_000_000_000.0

    def on_lowstate(self, msg):
        now_sec = self._now_sec()
        self.last_lowstate_sec = now_sec
        self._expire_commanded_velocity(now_sec)
        summary = self._lowstate_to_summary(msg, source=self.config.native_topics["low_state"])
        text = self.msg["String"]()
        text.data = json.dumps(
            build_low_state_payload(
                stamp_sec=now_sec,
                source=summary.source,
                mode=self.mode,
                control_owner=self.control_owner,
                mode_source=self.mode_source,
                summary=summary,
                velocity=self.commanded_velocity,
                sport_fsm_mode=self.sport_fsm_mode,
                sport_fsm_id=self.sport_fsm_id,
            ),
            ensure_ascii=False,
            sort_keys=True,
        )
        self.low_pub.publish(text)

        motor_text = self.msg["String"]()
        motor_text.data = json.dumps(
            {"motor_count": summary.motor_count, "motors": summary.motors},
            ensure_ascii=False,
            sort_keys=True,
        )
        self.motor_pub.publish(motor_text)

    def on_lowstate_low_freq(self, msg):
        now_sec = self._now_sec()
        self._expire_commanded_velocity(now_sec)
        summary = self._lowstate_to_summary(msg, source=self.config.native_topics["low_state_low_freq"])
        mode_text = self.msg["String"]()
        mode_text.data = json.dumps(
            build_mode_payload(
                stamp_sec=now_sec,
                source=summary.source,
                mode=self.mode,
                control_owner=self.control_owner,
                mode_source=self.mode_source,
                motor_count=summary.motor_count,
                sport_fsm_mode=self.sport_fsm_mode,
                sport_fsm_id=self.sport_fsm_id,
            ),
            ensure_ascii=False,
            sort_keys=True,
        )
        self.mode_pub.publish(mode_text)

    def on_secondary_imu(self, msg):
        payload = self._imu_to_payload(msg, frame_id="g1_torso")
        imu = self.msg["Imu"]()
        imu.header.frame_id = payload.frame_id
        imu.orientation.x = payload.orientation_xyzw[0]
        imu.orientation.y = payload.orientation_xyzw[1]
        imu.orientation.z = payload.orientation_xyzw[2]
        imu.orientation.w = payload.orientation_xyzw[3]
        imu.angular_velocity.x = payload.angular_velocity[0]
        imu.angular_velocity.y = payload.angular_velocity[1]
        imu.angular_velocity.z = payload.angular_velocity[2]
        imu.linear_acceleration.x = payload.linear_acceleration[0]
        imu.linear_acceleration.y = payload.linear_acceleration[1]
        imu.linear_acceleration.z = payload.linear_acceleration[2]
        self.imu_pub.publish(imu)

    def on_sport_response(self, msg):
        try:
            self.last_api_result = self._sport_api.record_response(msg, now_sec=self._now_sec())
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            self.node.get_logger().warning(f"ignoring invalid sport API response: {exc}")
            return
        self._update_sport_state_from_response(self.last_api_result)

    def on_audio_msg(self, msg) -> None:
        raw = getattr(msg, "data", "").strip()
        if not raw:
            return

        normalized = normalize_audio_asr_message(raw)
        if normalized is not None:
            text = self.msg["String"]()
            text.data = normalized
            self.asr_pub.publish(text)
        else:
            text = self.msg["String"]()
            text.data = raw
            self.audio_event_pub.publish(text)

    def on_safe_loco(self, msg):
        self._publish_sport_command(msg.data, parse_safe_loco_command, "safe_loco")

    def on_safe_stop(self, msg):
        self._publish_sport_command(msg.data, parse_stop_command, "safe_stop")

    def _publish_sport_command(self, raw_json, parser, command_name: str) -> bool:
        now_sec = self._now_sec()
        allowed, reason = check_sport_command_allowed(
            now_sec=now_sec,
            last_lowstate_sec=self.last_lowstate_sec,
            state_timeout_sec=self.state_timeout_sec,
        )
        if not allowed:
            self.node.get_logger().warning(f"rejecting {command_name}: {reason}")
            return False

        try:
            command = parser(raw_json)
            request = self._sport_api.build_request(command, now_sec=now_sec)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            self.node.get_logger().warning(f"rejecting {command_name}: {exc}")
            return False

        self.sport_request_pub.publish(request)
        self._record_commanded_velocity(command, now_sec)
        return True

    def query_sport_mode(self) -> None:
        now_sec = self._now_sec()
        if self._sport_api.pending_count >= 8:
            return
        for action in ["get_fsm_mode", "get_fsm_id"]:
            if action not in self.config.sport_api["api_ids"]:
                continue
            try:
                request = self._sport_api.build_request(SportCommand(action=action, params={}), now_sec=now_sec)
            except ValueError as exc:
                self.node.get_logger().warning(f"cannot build sport state query {action}: {exc}")
                continue
            self.sport_request_pub.publish(request)

    def _record_commanded_velocity(self, command: SportCommand, now_sec: float) -> None:
        velocity = command.params.get("velocity", [0.0, 0.0, 0.0])
        duration = float(command.params.get("duration", 0.1))
        self.commanded_velocity = {
            "vx": float(velocity[0]),
            "vy": float(velocity[1]),
            "vyaw": float(velocity[2]),
        }
        self.command_until_sec = now_sec + max(0.0, duration)

    def _expire_commanded_velocity(self, now_sec: float) -> None:
        if now_sec >= self.command_until_sec:
            self.commanded_velocity = {"vx": 0.0, "vy": 0.0, "vyaw": 0.0}

    def _update_sport_state_from_response(self, result: dict[str, Any]) -> None:
        if result.get("matched") is not True or int(result.get("code", -1)) != 0:
            return

        action = result.get("action")
        payload = result.get("payload")
        if not isinstance(payload, dict):
            payload = {}

        if action == "get_fsm_mode":
            data = payload.get("data")
            if data is None:
                return
            self.sport_fsm_mode = int(data)
            self.mode = "sport_api_loco"
            self.control_owner = "internal"
            self.mode_source = "sport_api.get_fsm_mode"
        elif action == "get_fsm_id":
            data = payload.get("data")
            if data is not None:
                self.sport_fsm_id = int(data)
        elif action == "switch_to_user_ctrl":
            self.mode = "user_ctrl"
            self.control_owner = "user"
            self.mode_source = "sport_api.switch_to_user_ctrl"
        elif action == "switch_to_internal_ctrl":
            self.mode = "sport_api_loco"
            self.control_owner = "internal"
            self.mode_source = "sport_api.switch_to_internal_ctrl"
            data = payload.get("data")
            if data is not None:
                self.sport_fsm_mode = int(data)

    def publish_health(self):
        now_sec = self._now_sec()
        for expired in self._sport_api.expired_requests(now_sec):
            self.node.get_logger().warning(
                f"sport API request timed out: sequence_id={expired.sequence_id} action={expired.action}"
            )

        status_payload = build_health_status(
            now_sec=now_sec,
            last_lowstate_sec=self.last_lowstate_sec,
            state_timeout_sec=self.state_timeout_sec,
            pending_api_count=self._sport_api.pending_count,
            last_api_result=self.last_api_result,
        )

        status = self.msg["DiagnosticStatus"]()
        status.name = "g1_interface"
        status.level = diagnostic_level_for_state(status_payload["state"])
        status.message = status_payload["state"]
        for key, value in status_payload.items():
            pair = self.msg["KeyValue"]()
            pair.key = str(key)
            pair.value = json.dumps(value, ensure_ascii=False, sort_keys=True)
            status.values.append(pair)

        array = self.msg["DiagnosticArray"]()
        array.status.append(status)
        self.health_pub.publish(array)


def main(args=None):
    import rclpy

    from g1_interface.config import G1InterfaceConfig

    rclpy.init(args=args)
    node = rclpy.create_node("g1_interface_node")
    node.declare_parameter("config_path", "")
    config_path = node.get_parameter("config_path").get_parameter_value().string_value
    config = G1InterfaceConfig.from_yaml(config_path) if config_path else G1InterfaceConfig.default()
    G1InterfaceNode(node=node, config=config)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            node.destroy_node()
        except KeyboardInterrupt:
            pass
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
