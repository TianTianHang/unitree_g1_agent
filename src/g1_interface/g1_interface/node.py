from __future__ import annotations

import json
from typing import Any

from g1_interface.internal_types import SportCommand


def parse_safe_loco_command(raw_json: str) -> SportCommand:
    payload = json.loads(raw_json)
    required = ["vx", "vy", "vyaw", "duration_sec"]
    missing = [field for field in required if field not in payload]
    if missing:
        raise ValueError(f"missing required loco field: {', '.join(missing)}")
    return SportCommand(
        action="set_velocity",
        params={
            "velocity": [float(payload["vx"]), float(payload["vy"]), float(payload["vyaw"])],
            "duration": float(payload["duration_sec"]),
        },
    )


def parse_stop_command(raw_json: str) -> SportCommand:
    if raw_json.strip():
        json.loads(raw_json)
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
        node.create_subscription(self.msg["String"], "/g1/safe_cmd/loco", self.on_safe_loco, 10)
        node.create_subscription(self.msg["String"], "/g1/safe_cmd/stop", self.on_safe_stop, 10)

        period = config.timeouts["health_publish_period_ms"] / 1000.0
        node.create_timer(period, self.publish_health)

    def _now_sec(self):
        return self.node.get_clock().now().nanoseconds / 1_000_000_000.0

    def on_lowstate(self, msg):
        self.last_lowstate_sec = self._now_sec()
        summary = self._lowstate_to_summary(msg, source=self.config.native_topics["low_state"])
        text = self.msg["String"]()
        text.data = summary.to_json()
        self.low_pub.publish(text)

        motor_text = self.msg["String"]()
        motor_text.data = json.dumps(
            {"motor_count": summary.motor_count, "motors": summary.motors},
            ensure_ascii=False,
            sort_keys=True,
        )
        self.motor_pub.publish(motor_text)

    def on_lowstate_low_freq(self, msg):
        summary = self._lowstate_to_summary(msg, source=self.config.native_topics["low_state_low_freq"])
        mode_text = self.msg["String"]()
        mode_text.data = json.dumps(
            {"source": summary.source, "rpy": summary.rpy, "motor_count": summary.motor_count},
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
        self.last_api_result = self._sport_api.record_response(msg, now_sec=self._now_sec())

    def on_safe_loco(self, msg):
        command = parse_safe_loco_command(msg.data)
        request = self._sport_api.build_request(command, now_sec=self._now_sec())
        self.sport_request_pub.publish(request)

    def on_safe_stop(self, msg):
        command = parse_stop_command(msg.data)
        request = self._sport_api.build_request(command, now_sec=self._now_sec())
        self.sport_request_pub.publish(request)

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
        status.level = 0 if status_payload["state"] == "ok" else 1
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
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
