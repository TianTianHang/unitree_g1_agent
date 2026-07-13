from __future__ import annotations

import json
import math
import time
from typing import Any, Callable

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


def _age_ms(now_sec: float, last_sec: float | None) -> int | None:
    if last_sec is None:
        return None
    return int(round(max(0.0, now_sec - last_sec) * 1000))


def build_health_status(
    *,
    now_sec: float,
    last_lowstate_sec: float | None,
    state_timeout_sec: float,
    pending_api_count: int,
    last_api_result: dict[str, Any] | None,
    last_sport_response_sec: float | None,
    last_successful_mode_query_sec: float | None,
    mode_freshness_timeout_sec: float,
    consecutive_api_timeouts: int,
    api_unhealthy_timeout_count: int,
    last_command_ack: dict[str, Any] | None,
    last_safety_heartbeat_sec: float | None,
    safety_heartbeat_timeout_sec: float,
) -> dict[str, Any]:
    lowstate_age_ms = _age_ms(now_sec, last_lowstate_sec)
    sport_response_age_ms = _age_ms(now_sec, last_sport_response_sec)
    mode_age_ms = _age_ms(now_sec, last_successful_mode_query_sec)
    safety_age_ms = _age_ms(now_sec, last_safety_heartbeat_sec)

    lowstate_fresh = last_lowstate_sec is not None and now_sec - last_lowstate_sec <= state_timeout_sec
    mode_fresh = (
        last_successful_mode_query_sec is not None
        and now_sec - last_successful_mode_query_sec <= mode_freshness_timeout_sec
    )
    safety_fresh = (
        last_safety_heartbeat_sec is not None
        and now_sec - last_safety_heartbeat_sec <= safety_heartbeat_timeout_sec
    )

    public_command_ack = None
    command_ack_unhealthy = False
    if last_command_ack is not None:
        public_command_ack = {
            key: value for key, value in last_command_ack.items() if key != "updated_monotonic_sec"
        }
        public_command_ack["age_ms"] = _age_ms(now_sec, last_command_ack.get("updated_monotonic_sec"))
        command_ack_unhealthy = public_command_ack.get("state") in {"pending", "rejected", "timed_out"}

    api_result_failed = bool(
        last_api_result is not None
        and last_api_result.get("matched") is True
        and int(last_api_result.get("code", -1)) != 0
    )

    if not lowstate_fresh or consecutive_api_timeouts >= api_unhealthy_timeout_count:
        state = "unhealthy"
    elif (
        not mode_fresh
        or not safety_fresh
        or consecutive_api_timeouts > 0
        or command_ack_unhealthy
        or api_result_failed
    ):
        state = "degraded"
    else:
        state = "ok"

    if not lowstate_fresh:
        dds_connection_state = "disconnected"
    elif state != "ok":
        dds_connection_state = "degraded"
    else:
        dds_connection_state = "connected"

    return {
        "state": state,
        "lowstate_age_ms": lowstate_age_ms,
        "last_sport_response_age_ms": sport_response_age_ms,
        "last_successful_mode_query_age_ms": mode_age_ms,
        "consecutive_api_timeouts": consecutive_api_timeouts,
        "last_command_ack": public_command_ack,
        "mode_fresh": mode_fresh,
        "safety_control_age_ms": safety_age_ms,
        "safety_control_fresh": safety_fresh,
        "dds_connection_state": dds_connection_state,
        "pending_api_count": pending_api_count,
        "last_api_result": last_api_result,
    }


def diagnostic_level_for_state(state: str) -> bytes:
    if state == "ok":
        return b"\x00"
    if state == "unhealthy":
        return b"\x02"
    return b"\x01"


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

    event_text = payload.get("text")
    if not isinstance(event_text, str):
        return None
    event_text = event_text.strip()
    if not event_text:
        return None

    return text


def should_forward_native_asr(source_mode: str) -> bool:
    return source_mode in {"builtin", "both"}


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
    *,
    now_sec: float,
    last_lowstate_sec: float | None,
    state_timeout_sec: float,
    last_safety_heartbeat_sec: float | None,
    safety_heartbeat_timeout_sec: float,
    last_successful_mode_query_sec: float | None,
    mode_freshness_timeout_sec: float,
    command_ack_state: str | None,
    mode: str | None,
    control_owner: str,
) -> tuple[bool, str | None]:
    if last_lowstate_sec is None:
        return False, "lowstate unavailable"

    age_ms = _age_ms(now_sec, last_lowstate_sec)
    if now_sec - last_lowstate_sec > state_timeout_sec:
        return False, f"lowstate stale: age_ms={age_ms}"

    if last_safety_heartbeat_sec is None:
        return False, "safety_control heartbeat unavailable"

    safety_age_ms = _age_ms(now_sec, last_safety_heartbeat_sec)
    if now_sec - last_safety_heartbeat_sec > safety_heartbeat_timeout_sec:
        return False, f"safety_control heartbeat stale: age_ms={safety_age_ms}"

    if last_successful_mode_query_sec is None:
        return False, "sport mode unavailable"

    mode_age_ms = _age_ms(now_sec, last_successful_mode_query_sec)
    if now_sec - last_successful_mode_query_sec > mode_freshness_timeout_sec:
        return False, f"sport mode stale: age_ms={mode_age_ms}"

    if command_ack_state in {"pending", "rejected", "timed_out"}:
        return False, f"sport command acknowledgement unresolved: state={command_ack_state}"

    if mode != "sport_api_loco" or control_owner != "internal":
        return False, f"sport mode does not allow loco: mode={mode} owner={control_owner}"

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
    def __init__(self, node, config, monotonic_clock: Callable[[], float] | None = None):
        self.node = node
        self.config = config
        self.msg = _load_ros_messages()
        self._monotonic_clock = monotonic_clock or time.monotonic

        self.last_lowstate_monotonic_sec: float | None = None
        self.last_safety_heartbeat_monotonic_sec: float | None = None
        self.last_sport_response_monotonic_sec: float | None = None
        self.last_successful_mode_query_monotonic_sec: float | None = None
        self.last_api_result: dict[str, Any] | None = None
        self.last_command_ack: dict[str, Any] | None = None
        self.consecutive_api_timeouts = 0

        self.state_timeout_sec = config.timeouts["state_timeout_ms"] / 1000.0
        self.safety_heartbeat_timeout_sec = config.timeouts["safety_heartbeat_timeout_ms"] / 1000.0
        self.mode_freshness_timeout_sec = config.timeouts["mode_freshness_timeout_ms"] / 1000.0
        self.api_unhealthy_timeout_count = int(config.timeouts["api_unhealthy_timeout_count"])

        self.mode: str | None = None
        self.control_owner = "unknown"
        self.mode_source = "unavailable"
        self.sport_fsm_mode: int | None = None
        self.sport_fsm_id: int | None = None
        self.commanded_velocity = {"vx": 0.0, "vy": 0.0, "vyaw": 0.0}
        self.motion_deadline_monotonic_sec: float | None = None
        self.active_motion_sequence_id: int | None = None
        self._shutdown_stop_sent = False

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
        node.create_subscription(
            self.msg["String"],
            config.project_topics["safety_state"],
            self.on_safety_state,
            10,
        )
        node.create_subscription(self.msg["String"], "/g1/safe_cmd/loco", self.on_safe_loco, 10)
        node.create_subscription(self.msg["String"], "/g1/safe_cmd/stop", self.on_safe_stop, 10)

        period = config.timeouts["health_publish_period_ms"] / 1000.0
        node.create_timer(period, self.publish_health)
        mode_query_period = config.timeouts["mode_query_period_ms"] / 1000.0
        node.create_timer(mode_query_period, self.query_sport_mode)

        from rclpy.clock import Clock, ClockType

        self._steady_clock = Clock(clock_type=ClockType.STEADY_TIME)
        watchdog_period = config.timeouts["motion_watchdog_period_ms"] / 1000.0
        node.create_timer(watchdog_period, self.watchdog_tick, clock=self._steady_clock)

    def _now_sec(self) -> float:
        """Return ROS time for externally published timestamps only."""
        return self.node.get_clock().now().nanoseconds / 1_000_000_000.0

    def _monotonic_sec(self) -> float:
        return float(self._monotonic_clock())

    def on_lowstate(self, msg):
        stamp_sec = self._now_sec()
        self.last_lowstate_monotonic_sec = self._monotonic_sec()
        summary = self._lowstate_to_summary(msg, source=self.config.native_topics["low_state"])
        text = self.msg["String"]()
        text.data = json.dumps(
            build_low_state_payload(
                stamp_sec=stamp_sec,
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
        stamp_sec = self._now_sec()
        summary = self._lowstate_to_summary(msg, source=self.config.native_topics["low_state_low_freq"])
        mode_text = self.msg["String"]()
        mode_text.data = json.dumps(
            build_mode_payload(
                stamp_sec=stamp_sec,
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
        now_sec = self._monotonic_sec()
        try:
            result = self._sport_api.record_response(msg, now_sec=now_sec)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            self.node.get_logger().warning(f"ignoring invalid sport API response: {exc}")
            return

        self.last_api_result = result
        self.last_sport_response_monotonic_sec = now_sec
        if result.get("matched") is True:
            self.consecutive_api_timeouts = 0
        self._update_command_ack_from_response(result, now_sec)
        self._update_sport_state_from_response(result, now_sec)

    def on_safety_state(self, msg) -> None:
        try:
            payload = json.loads(getattr(msg, "data", ""))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            self.node.get_logger().warning(f"ignoring invalid safety_control heartbeat: {exc}")
            return
        if not isinstance(payload, dict) or payload.get("node") != "safety_control":
            return
        self.last_safety_heartbeat_monotonic_sec = self._monotonic_sec()

    def on_audio_msg(self, msg) -> None:
        raw = getattr(msg, "data", "").strip()
        if not raw:
            return

        normalized = normalize_audio_asr_message(raw)
        if normalized is not None:
            if should_forward_native_asr(str(self.config.asr["source_mode"])):
                text = self.msg["String"]()
                text.data = normalized
                self.asr_pub.publish(text)
            return

        text = self.msg["String"]()
        text.data = raw
        self.audio_event_pub.publish(text)

    def on_safe_loco(self, msg):
        now_sec = self._monotonic_sec()
        allowed, reason = check_sport_command_allowed(
            now_sec=now_sec,
            last_lowstate_sec=self.last_lowstate_monotonic_sec,
            state_timeout_sec=self.state_timeout_sec,
            last_safety_heartbeat_sec=self.last_safety_heartbeat_monotonic_sec,
            safety_heartbeat_timeout_sec=self.safety_heartbeat_timeout_sec,
            last_successful_mode_query_sec=self.last_successful_mode_query_monotonic_sec,
            mode_freshness_timeout_sec=self.mode_freshness_timeout_sec,
            command_ack_state=self._command_ack_state(),
            mode=self.mode,
            control_owner=self.control_owner,
        )
        if not allowed:
            self.node.get_logger().warning(f"rejecting safe_loco: {reason}")
            return

        try:
            command = parse_safe_loco_command(msg.data)
            self._publish_velocity_command(command, now_sec=now_sec, stop_reason=None)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            self.node.get_logger().warning(f"rejecting safe_loco: {exc}")

    def on_safe_stop(self, msg):
        now_sec = self._monotonic_sec()
        try:
            command = parse_stop_command(msg.data)
            self._publish_velocity_command(command, now_sec=now_sec, stop_reason="safe_stop")
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            self.node.get_logger().warning(f"rejecting safe_stop: {exc}")

    def _publish_velocity_command(
        self,
        command: SportCommand,
        *,
        now_sec: float,
        stop_reason: str | None,
    ) -> int:
        request = self._sport_api.build_request(command, now_sec=now_sec)
        self.sport_request_pub.publish(request)

        velocity = command.params.get("velocity", [0.0, 0.0, 0.0])
        velocity_values = [float(velocity[0]), float(velocity[1]), float(velocity[2])]
        nonzero = any(value != 0.0 for value in velocity_values)
        sequence_id = int(request.header.identity.id)
        command_kind = "motion" if nonzero else "stop"
        self.last_command_ack = {
            "sequence_id": sequence_id,
            "state": "pending",
            "code": None,
            "command_kind": command_kind,
            "stop_reason": stop_reason,
            "updated_monotonic_sec": now_sec,
        }

        self.commanded_velocity = {
            "vx": velocity_values[0],
            "vy": velocity_values[1],
            "vyaw": velocity_values[2],
        }
        if nonzero:
            duration = max(0.0, float(command.params.get("duration", 0.1)))
            self.motion_deadline_monotonic_sec = now_sec + duration
            self.active_motion_sequence_id = sequence_id
        else:
            self.motion_deadline_monotonic_sec = None
            self.active_motion_sequence_id = None
        return sequence_id

    def _publish_stop_request(self, reason: str, now_sec: float, *, force: bool = False) -> bool:
        if not force and self._stop_request_pending():
            return False
        command = SportCommand(
            action="set_velocity",
            params={"velocity": [0.0, 0.0, 0.0], "duration": 0.1},
        )
        try:
            self._publish_velocity_command(command, now_sec=now_sec, stop_reason=reason)
        except (TypeError, ValueError) as exc:
            self.node.get_logger().warning(f"cannot publish watchdog stop ({reason}): {exc}")
            return False
        self.node.get_logger().warning(f"published zero velocity: reason={reason}")
        return True

    def _command_ack_state(self) -> str | None:
        if self.last_command_ack is None:
            return None
        return str(self.last_command_ack.get("state"))

    def _stop_request_pending(self) -> bool:
        return bool(
            self.last_command_ack
            and self.last_command_ack.get("state") == "pending"
            and self.last_command_ack.get("command_kind") == "stop"
        )

    def _motion_active(self) -> bool:
        return self.active_motion_sequence_id is not None and self.motion_deadline_monotonic_sec is not None

    def query_sport_mode(self) -> None:
        now_sec = self._monotonic_sec()
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

    def _update_command_ack_from_response(self, result: dict[str, Any], now_sec: float) -> None:
        if result.get("matched") is not True or self.last_command_ack is None:
            return
        if int(result.get("sequence_id", -1)) != int(self.last_command_ack.get("sequence_id", -2)):
            return

        code = int(result.get("code", -1))
        command_kind = self.last_command_ack.get("command_kind")
        self.last_command_ack = {
            **self.last_command_ack,
            "state": "acknowledged" if code == 0 else "rejected",
            "code": code,
            "updated_monotonic_sec": now_sec,
        }
        if code != 0 and command_kind == "motion":
            self._publish_stop_request("command_rejected", now_sec)

    def _update_sport_state_from_response(self, result: dict[str, Any], now_sec: float) -> None:
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
            self.last_successful_mode_query_monotonic_sec = now_sec
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

    def _expire_api_requests(self, now_sec: float) -> None:
        for expired in self._sport_api.expired_requests(now_sec):
            self.consecutive_api_timeouts += 1
            self.node.get_logger().warning(
                f"sport API request timed out: sequence_id={expired.sequence_id} action={expired.action}"
            )
            if (
                self.last_command_ack is not None
                and int(self.last_command_ack.get("sequence_id", -1)) == expired.sequence_id
                and self.last_command_ack.get("state") == "pending"
            ):
                command_kind = self.last_command_ack.get("command_kind")
                self.last_command_ack = {
                    **self.last_command_ack,
                    "state": "timed_out",
                    "updated_monotonic_sec": now_sec,
                }
                if command_kind == "motion" and self.active_motion_sequence_id == expired.sequence_id:
                    self._publish_stop_request("command_unacknowledged", now_sec)

    def watchdog_tick(self) -> None:
        now_sec = self._monotonic_sec()
        self._expire_api_requests(now_sec)
        if not self._motion_active():
            return

        if (
            self.last_lowstate_monotonic_sec is None
            or now_sec - self.last_lowstate_monotonic_sec > self.state_timeout_sec
        ):
            self._publish_stop_request("lowstate_lost", now_sec)
            return
        if (
            self.last_safety_heartbeat_monotonic_sec is None
            or now_sec - self.last_safety_heartbeat_monotonic_sec > self.safety_heartbeat_timeout_sec
        ):
            self._publish_stop_request("safety_heartbeat_lost", now_sec)
            return
        if now_sec >= float(self.motion_deadline_monotonic_sec):
            self._publish_stop_request("command_deadline", now_sec)

    def publish_health(self):
        now_sec = self._monotonic_sec()
        self._expire_api_requests(now_sec)
        status_payload = build_health_status(
            now_sec=now_sec,
            last_lowstate_sec=self.last_lowstate_monotonic_sec,
            state_timeout_sec=self.state_timeout_sec,
            pending_api_count=self._sport_api.pending_count,
            last_api_result=self.last_api_result,
            last_sport_response_sec=self.last_sport_response_monotonic_sec,
            last_successful_mode_query_sec=self.last_successful_mode_query_monotonic_sec,
            mode_freshness_timeout_sec=self.mode_freshness_timeout_sec,
            consecutive_api_timeouts=self.consecutive_api_timeouts,
            api_unhealthy_timeout_count=self.api_unhealthy_timeout_count,
            last_command_ack=self.last_command_ack,
            last_safety_heartbeat_sec=self.last_safety_heartbeat_monotonic_sec,
            safety_heartbeat_timeout_sec=self.safety_heartbeat_timeout_sec,
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

    def shutdown(self) -> None:
        if self._shutdown_stop_sent:
            return
        self._shutdown_stop_sent = True
        self._publish_stop_request("shutdown", self._monotonic_sec(), force=True)


def main(args=None):
    import rclpy

    from g1_interface.config import G1InterfaceConfig

    rclpy.init(args=args)
    node = rclpy.create_node("g1_interface_node")
    node.declare_parameter("config_path", "")
    config_path = node.get_parameter("config_path").get_parameter_value().string_value
    node.declare_parameter("asr_source_mode", "")
    asr_source_mode = node.get_parameter("asr_source_mode").get_parameter_value().string_value
    config = G1InterfaceConfig.from_yaml(config_path) if config_path else G1InterfaceConfig.default()
    if asr_source_mode:
        config = config.with_asr_source_mode(asr_source_mode)
    bridge = G1InterfaceNode(node=node, config=config)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        bridge.shutdown()
        try:
            node.destroy_node()
        except KeyboardInterrupt:
            pass
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
