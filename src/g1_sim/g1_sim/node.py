from __future__ import annotations

import json
import math
from collections.abc import Callable
from typing import Any

from g1_sim.config import G1SimConfig
from g1_sim.model import (
    SimulatedRobotState,
    decode_request_parameter,
    dumps,
    handle_agv_api,
    handle_arm_api,
    handle_motion_switcher_api,
    handle_sport_api,
    handle_voice_api,
    request_identity,
)


def _load_ros_messages():
    from nav_msgs.msg import Odometry
    from std_msgs.msg import String
    from unitree_api.msg import Request, Response
    from unitree_hg.msg import HandCmd, HandState, IMUState, LowCmd, LowState

    return {
        "String": String,
        "Odometry": Odometry,
        "Request": Request,
        "Response": Response,
        "HandCmd": HandCmd,
        "HandState": HandState,
        "IMUState": IMUState,
        "LowCmd": LowCmd,
        "LowState": LowState,
    }


def _period_from_hz(hz: float) -> float:
    return 1.0 / max(0.001, float(hz))


class G1SimNode:
    def __init__(self, node, config: G1SimConfig):
        self.node = node
        self.config = config
        self.msg = _load_ros_messages()
        self.state = SimulatedRobotState(
            motor_count=int(config.sim["motor_count"]),
            hand_motor_count=int(config.sim["hand_motor_count"]),
        )

        topics = config.topics
        self.low_state_pubs = [
            node.create_publisher(self.msg["LowState"], topics["low_state"], 10),
        ]
        self.low_state_low_freq_pub = node.create_publisher(self.msg["LowState"], topics["low_state_low_freq"], 10)
        self.imu_pubs = [
            node.create_publisher(self.msg["IMUState"], topics["secondary_imu"], 10),
        ]
        self.odometry_pub = node.create_publisher(self.msg["Odometry"], topics["odometry"], 10)
        self.dex3_left_state_pubs = [
            node.create_publisher(self.msg["HandState"], topics["dex3_left_state"], 10),
            node.create_publisher(self.msg["HandState"], topics["dex3_left_state_legacy"], 10),
        ]
        self.dex3_right_state_pubs = [
            node.create_publisher(self.msg["HandState"], topics["dex3_right_state"], 10),
            node.create_publisher(self.msg["HandState"], topics["dex3_right_state_legacy"], 10),
        ]
        self.audio_msg_pub = node.create_publisher(self.msg["String"], topics["audio_msg"], 10)
        self.sport_response_pub = node.create_publisher(self.msg["Response"], topics["sport_response"], 10)
        self.arm_response_pub = node.create_publisher(self.msg["Response"], topics["arm_response"], 10)
        self.voice_response_pub = node.create_publisher(self.msg["Response"], topics["voice_response"], 10)
        self.agv_response_pub = node.create_publisher(self.msg["Response"], topics["agv_response"], 10)
        self.motion_switcher_response_pub = node.create_publisher(
            self.msg["Response"],
            topics["motion_switcher_response"],
            10,
        )

        node.create_subscription(self.msg["String"], topics["asr_input"], self._on_asr_input_callback, 10)
        node.create_subscription(self.msg["LowCmd"], topics["low_cmd_root"], self.on_lowcmd, 10)
        node.create_subscription(self.msg["LowCmd"], topics["low_cmd_relative"], self.on_lowcmd, 10)
        node.create_subscription(self.msg["LowCmd"], topics["arm_sdk"], self.on_arm_sdk, 10)
        node.create_subscription(self.msg["LowCmd"], topics["user_lowcmd"], self.on_lowcmd, 10)
        node.create_subscription(self.msg["HandCmd"], topics["dex3_left_cmd"], self.on_dex3_left_cmd, 10)
        node.create_subscription(self.msg["HandCmd"], topics["dex3_right_cmd"], self.on_dex3_right_cmd, 10)
        node.create_subscription(self.msg["Request"], topics["sport_request"], self.on_sport_request, 10)
        node.create_subscription(self.msg["Request"], topics["arm_request"], self.on_arm_request, 10)
        node.create_subscription(self.msg["Request"], topics["voice_request"], self.on_voice_request, 10)
        node.create_subscription(self.msg["Request"], topics["agv_request"], self.on_agv_request, 10)
        node.create_subscription(
            self.msg["Request"],
            topics["motion_switcher_request"],
            self.on_motion_switcher_request,
            10,
        )

        node.create_timer(_period_from_hz(config.sim["low_state_hz"]), self.publish_lowstate)
        node.create_timer(_period_from_hz(config.sim["low_state_low_freq_hz"]), self.publish_lowstate_low_freq)
        node.create_timer(_period_from_hz(config.sim["imu_hz"]), self.publish_imu)
        node.create_timer(_period_from_hz(config.sim["odometry_hz"]), self.publish_odometry)
        node.create_timer(_period_from_hz(config.sim["hand_state_hz"]), self.publish_hand_state)

    def _now_sec(self) -> float:
        return self.node.get_clock().now().nanoseconds / 1_000_000_000.0

    def on_lowcmd(self, msg) -> None:
        self.state.record_lowcmd(self._now_sec())

    def on_arm_sdk(self, msg) -> None:
        self.state.record_arm_sdk(self._now_sec())

    def on_dex3_left_cmd(self, msg) -> None:
        self.state.record_dex3_cmd("left", self._now_sec())

    def on_dex3_right_cmd(self, msg) -> None:
        self.state.record_dex3_cmd("right", self._now_sec())

    def on_sport_request(self, msg) -> None:
        self._handle_api_request(
            msg,
            service="sport",
            response_pub=self.sport_response_pub,
            handler=lambda api_id, params, now_sec: handle_sport_api(
                self.state,
                api_id,
                params,
                self.config.sim["sport_api_ids"],
                now_sec,
            ),
        )

    def on_arm_request(self, msg) -> None:
        self._handle_api_request(
            msg,
            service="arm",
            response_pub=self.arm_response_pub,
            handler=lambda api_id, params, now_sec: handle_arm_api(
                self.state,
                api_id,
                params,
                self.config.sim["arm_api_ids"],
            ),
        )

    def on_voice_request(self, msg) -> None:
        sequence_id, api_id = request_identity(msg)
        try:
            params = decode_request_parameter(msg)
            code, payload = handle_voice_api(
                self.state,
                api_id,
                params,
                self.config.sim["voice_api_ids"],
                str(self.config.sim["default_asr_text"]),
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            code = 1
            payload = {"accepted": False, "service": "voice", "error": str(exc)}
            self.node.get_logger().warning(
                f"rejecting voice request sequence_id={sequence_id} api_id={api_id}: {exc}"
            )

        payload.setdefault("service", "voice")
        self.voice_response_pub.publish(self._build_response(msg, code=code, payload=payload))

        if code != 0:
            return

        action = payload.get("action")
        if action == "asr":
            self.publish_asr_message(str(payload.get("text", "")))
        elif action == "start_play":
            self.publish_play_state(is_playing=True)
        elif action == "stop_play" and payload.get("stopped_streams"):
            self.publish_play_state(is_playing=False)

    def on_agv_request(self, msg) -> None:
        self._handle_api_request(
            msg,
            service="agv",
            response_pub=self.agv_response_pub,
            handler=lambda api_id, params, now_sec: handle_agv_api(
                self.state,
                api_id,
                params,
                self.config.sim["agv_api_ids"],
                now_sec,
            ),
        )

    def on_motion_switcher_request(self, msg) -> None:
        self._handle_api_request(
            msg,
            service="motion_switcher",
            response_pub=self.motion_switcher_response_pub,
            handler=lambda api_id, params, now_sec: handle_motion_switcher_api(
                self.state,
                api_id,
                params,
                self.config.sim["motion_switcher_api_ids"],
            ),
        )

    def _handle_api_request(
        self,
        msg,
        *,
        service: str,
        response_pub,
        handler: Callable[[int, dict[str, Any], float], tuple[int, dict[str, Any]]],
    ) -> None:
        sequence_id, api_id = request_identity(msg)
        try:
            params = decode_request_parameter(msg)
            code, payload = handler(api_id, params, self._now_sec())
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            code = 1
            payload = {"accepted": False, "service": service, "error": str(exc)}
            self.node.get_logger().warning(
                f"rejecting {service} request sequence_id={sequence_id} api_id={api_id}: {exc}"
            )

        payload.setdefault("service", service)
        response_pub.publish(self._build_response(msg, code=code, payload=payload))

    def _build_response(self, request_msg, *, code: int, payload: dict[str, Any]):
        response = self.msg["Response"]()
        req_identity = getattr(getattr(request_msg, "header", None), "identity", None)
        res_header = getattr(response, "header", None)
        res_identity = getattr(res_header, "identity", None)
        if res_identity is not None and req_identity is not None:
            if hasattr(res_identity, "id"):
                res_identity.id = int(getattr(req_identity, "id", 0))
            if hasattr(res_identity, "api_id"):
                res_identity.api_id = int(getattr(req_identity, "api_id", 0))

        status = getattr(res_header, "status", None)
        if status is not None and hasattr(status, "code"):
            status.code = int(code)

        encoded = dumps(payload)
        if hasattr(response, "parameter"):
            response.parameter = encoded
        if hasattr(response, "data"):
            response.data = encoded
        return response

    def publish_lowstate(self) -> None:
        msg = self._make_lowstate()
        for publisher in self.low_state_pubs:
            publisher.publish(msg)

    def publish_lowstate_low_freq(self) -> None:
        self.low_state_low_freq_pub.publish(self._make_lowstate())

    def publish_imu(self) -> None:
        now_sec = self._now_sec()
        self.state.integrate(now_sec)
        msg = self.msg["IMUState"]()
        self._fill_imu_fields(msg)
        for publisher in self.imu_pubs:
            publisher.publish(msg)

    def publish_odometry(self) -> None:
        now = self.node.get_clock().now()
        now_sec = now.nanoseconds / 1_000_000_000.0
        self.state.integrate(now_sec)
        msg = self.msg["Odometry"]()
        msg.header.stamp = now.to_msg()
        msg.header.frame_id = "odom"
        msg.child_frame_id = "pelvis"
        msg.pose.pose.position.x = self.state.x
        msg.pose.pose.position.y = self.state.y
        msg.pose.pose.position.z = float(self.config.sim["pelvis_height"])
        msg.pose.pose.orientation.z = math.sin(self.state.yaw / 2.0)
        msg.pose.pose.orientation.w = math.cos(self.state.yaw / 2.0)
        msg.twist.twist.linear.x = self.state.vx
        msg.twist.twist.linear.y = self.state.vy
        msg.twist.twist.angular.z = self.state.vyaw
        self.odometry_pub.publish(msg)

    def publish_hand_state(self) -> None:
        left = self._make_hand_state("left")
        right = self._make_hand_state("right")
        for publisher in self.dex3_left_state_pubs:
            publisher.publish(left)
        for publisher in self.dex3_right_state_pubs:
            publisher.publish(right)

    def publish_asr_message(self, text: str) -> None:
        self.state.asr_index += 1
        asr_json = {
            "index": self.state.asr_index,
            "timestamp": self.node.get_clock().now().nanoseconds,
            "text": text,
            "angle": 90,
            "speaker_id": 0,
            "sense": "unknown",
            "confidence": 0.95,
            "language": "zh-CN",
            "is_final": True,
        }
        msg = self.msg["String"]()
        msg.data = json.dumps(asr_json, ensure_ascii=False)
        self.audio_msg_pub.publish(msg)

    def publish_play_state(self, is_playing: bool) -> None:
        msg = self.msg["String"]()
        msg.data = json.dumps({"play_state": 1 if is_playing else 0})
        self.audio_msg_pub.publish(msg)

    def _on_asr_input_callback(self, msg) -> None:
        text = getattr(msg, "data", "").strip()
        if text:
            self.publish_asr_message(text)

    def _make_lowstate(self):
        now_sec = self._now_sec()
        self.state.integrate(now_sec)
        msg = self.msg["LowState"]()
        self._fill_imu_fields(msg)
        _assign_attr(msg, "mode_pr", 0)
        _assign_attr(msg, "mode_machine", int(self.state.fsm_id))
        _assign_attr(msg, "tick", int(now_sec * 1000) & 0xFFFFFFFF)
        motors = list(getattr(msg, "motor_state", []))[: self.state.motor_count]
        for index, motor in enumerate(motors):
            phase = now_sec + index * 0.17
            _assign_attr(motor, "q", 0.02 * math.sin(phase))
            _assign_attr(motor, "dq", 0.02 * math.cos(phase))
            _assign_attr(motor, "ddq", 0.0)
            _assign_attr(motor, "tau_est", 0.0)
            self._assign_sequence(motor, "temperature", [38 + int(index % 5), 38 + int(index % 5)])
        return msg

    def _make_hand_state(self, side: str):
        now_sec = self._now_sec()
        msg = self.msg["HandState"]()
        # TODO(g1_sim): allocate unbounded HandState arrays before filling Dex3 state.
        motors = list(getattr(msg, "motor_state", []))[: self.state.hand_motor_count]
        offset = 0.0 if side == "left" else 0.3
        for index, motor in enumerate(motors):
            phase = now_sec + offset + index * 0.2
            _assign_attr(motor, "q", 0.1 * math.sin(phase))
            _assign_attr(motor, "dq", 0.1 * math.cos(phase))
            _assign_attr(motor, "tau_est", 0.0)
            self._assign_sequence(motor, "temperature", [35 + int(index % 3), 35 + int(index % 3)])
        sensors = list(getattr(msg, "press_sensor_state", []))
        for sensor in sensors:
            self._assign_sequence(sensor, "pressure", [0.0] * 12)
            self._assign_sequence(sensor, "temperature", [30.0] * 12)
            _assign_attr(sensor, "lost", 0)
        _assign_attr(msg, "power_v", 24.0)
        _assign_attr(msg, "power_a", 0.0)
        _assign_attr(msg, "system_v", 24.0)
        _assign_attr(msg, "device_v", 24.0)
        return msg

    def _fill_imu_fields(self, msg) -> None:
        target = getattr(msg, "imu_state", msg)
        yaw = self.state.yaw
        quaternion = [math.cos(yaw / 2.0), 0.0, 0.0, math.sin(yaw / 2.0)]
        self._assign_sequence(target, "quaternion", quaternion)
        self._assign_sequence(target, "rpy", [0.0, 0.0, yaw])
        self._assign_sequence(target, "gyroscope", [0.0, 0.0, self.state.vyaw])
        self._assign_sequence(target, "accelerometer", [0.0, 0.0, 9.81])
        _assign_attr(target, "temperature", 35)

    @staticmethod
    def _assign_sequence(msg, attr: str, values: list[float]) -> None:
        if not hasattr(msg, attr):
            return
        target = getattr(msg, attr)
        try:
            for index, value in enumerate(values):
                try:
                    target[index] = value
                except TypeError:
                    try:
                        target[index] = float(value)
                    except TypeError:
                        target[index] = int(value)
            return
        except (TypeError, IndexError, AttributeError):
            pass
        try:
            setattr(msg, attr, list(values))
        except (TypeError, AttributeError):
            return


def _assign_attr(msg, attr: str, value: Any) -> None:
    if hasattr(msg, attr):
        try:
            setattr(msg, attr, value)
        except (TypeError, AttributeError):
            return


def main(args=None):
    import rclpy

    rclpy.init(args=args)
    node = rclpy.create_node("g1_sim_node")
    node.declare_parameter("config_path", "")
    config_path = node.get_parameter("config_path").get_parameter_value().string_value
    config = G1SimConfig.from_yaml(config_path) if config_path else G1SimConfig.default()
    G1SimNode(node=node, config=config)
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
