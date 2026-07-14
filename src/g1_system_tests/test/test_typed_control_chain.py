import json
import time
import unittest

import launch
import launch_ros.actions
import launch_testing.actions
import launch_testing.asserts
import rclpy
from ament_index_python.packages import get_package_share_directory
from diagnostic_msgs.msg import DiagnosticArray
from unitree_api.msg import Request

from g1_agent_msgs.msg import (
    ActionIntent,
    LocoIntent,
    SafetyStatus,
    ValidatedActionCommand,
    ValidatedLocoCommand,
    VoiceEvent,
)


def generate_test_description():
    config = get_package_share_directory("g1_system_tests") + "/config/voice_bridge_test.yaml"
    g1_sim = launch_ros.actions.Node(package="g1_sim", executable="g1_sim_node", output="screen")
    g1_interface = launch_ros.actions.Node(
        package="g1_interface",
        executable="g1_interface_node",
        output="screen",
    )
    safety_control = launch_ros.actions.Node(
        package="safety_control",
        executable="safety_control_node",
        output="screen",
    )
    voice_bridge = launch_ros.actions.Node(
        package="voice_bridge",
        executable="voice_bridge_node",
        output="screen",
        parameters=[{"config_path": config}],
    )
    nodes = [g1_sim, g1_interface, safety_control, voice_bridge]
    return launch.LaunchDescription(nodes + [launch_testing.actions.ReadyToTest()]), {
        "g1_interface": g1_interface,
    }


def _velocity(request):
    if request.header.identity.api_id != 7105:
        return None
    payload = json.loads(request.parameter)
    value = payload.get("velocity")
    return value if isinstance(value, list) and len(value) == 3 else None


class TestTypedControlChain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rclpy.init()
        cls.node = rclpy.create_node("typed_control_chain_test")
        cls.asr_pub = cls.node.create_publisher(VoiceEvent, "/g1/audio/asr", 10)
        cls.loco = []
        cls.action = []
        cls.safe_loco = []
        cls.safe_stop = []
        cls.sport = []
        cls.health = []
        cls.safety = []
        cls.subscriptions = [
            cls.node.create_subscription(LocoIntent, "/voice/cmd/loco", cls.loco.append, 10),
            cls.node.create_subscription(ActionIntent, "/voice/cmd/action", cls.action.append, 10),
            cls.node.create_subscription(
                ValidatedLocoCommand,
                "/g1/safe_cmd/loco",
                cls.safe_loco.append,
                10,
            ),
            cls.node.create_subscription(
                ValidatedActionCommand,
                "/g1/safe_cmd/stop",
                cls.safe_stop.append,
                10,
            ),
            cls.node.create_subscription(Request, "/api/sport/request", cls.sport.append, 10),
            cls.node.create_subscription(DiagnosticArray, "/g1/state/health", cls.health.append, 10),
            cls.node.create_subscription(SafetyStatus, "/g1/state/safety", cls.safety.append, 10),
        ]

    @classmethod
    def tearDownClass(cls):
        cls.node.destroy_node()
        rclpy.shutdown()

    def wait_for(self, predicate, timeout=10.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rclpy.spin_once(self.node, timeout_sec=0.1)
            if predicate():
                return
        self.fail("timed out waiting for typed control-chain condition")

    def test_loco_then_stop(self):
        self.wait_for(
            lambda: self.safety
            and any(status.message == "ok" for msg in self.health for status in msg.status),
            timeout=20.0,
        )

        loco_event = VoiceEvent(
            stamp=self.node.get_clock().now().to_msg(),
            source="test",
            event_type=VoiceEvent.EVENT_ASR,
            text="小宇向前一秒",
            is_final=True,
        )
        self.asr_pub.publish(loco_event)
        self.wait_for(lambda: self.loco and self.safe_loco)
        self.wait_for(
            lambda: any(
                velocity is not None and velocity[0] > 0.0
                for velocity in (_velocity(request) for request in self.sport)
            )
        )

        sport_count_before_stop = len(self.sport)
        stop_event = VoiceEvent(
            stamp=self.node.get_clock().now().to_msg(),
            source="test",
            event_type=VoiceEvent.EVENT_ASR,
            text="停止",
            is_final=True,
        )
        self.asr_pub.publish(stop_event)
        self.wait_for(lambda: self.action and self.safe_stop)
        self.wait_for(
            lambda: any(
                _velocity(request) == [0.0, 0.0, 0.0]
                for request in self.sport[sport_count_before_stop:]
            )
        )


@launch_testing.post_shutdown_test()
class TestProcessesExitCleanly(unittest.TestCase):
    def test_g1_interface_exit_code(self, proc_info, g1_interface):
        launch_testing.asserts.assertExitCodes(proc_info, process=g1_interface)


if __name__ == "__main__":
    unittest.main()
