import time
import unittest

import launch
import launch_ros.actions
import launch_testing.actions
import launch_testing.asserts
import rclpy
from ament_index_python.packages import get_package_share_directory
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from rclpy.action import ActionClient
from unitree_api.msg import Request
from unitree_hg.msg import LowCmd

from g1_agent_msgs.action import ExecuteMotion
from g1_agent_msgs.msg import (
    ActionIntent,
    LowLevelCommandCandidate,
    LowLevelControlLease,
    MotionReferenceSegment,
    TextOpTrackerStatus,
    ValidatedActionCommand,
    VoiceEvent,
)


def generate_test_description():
    share = get_package_share_directory("g1_system_tests")
    voice_config = share + "/config/textop_voice_bridge_test.yaml"
    system_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            get_package_share_directory("g1_bringup") + "/launch/g1_system.launch.py"
        ),
        launch_arguments={
            "motion_backend": "textop",
            "start_sim": "true",
            "start_textop_runtime": "false",
            "voice_config_path": voice_config,
        }.items(),
    )
    generator = launch_ros.actions.Node(
        package="g1_system_tests",
        executable="textop_generator_test_node",
        output="screen",
        parameters=[{
            "manifest_path": "system-test",
            "readiness_timeout": 0.5,
            "tracker_timeout": 1.0,
        }],
    )
    tracker = launch_ros.actions.Node(
        package="g1_system_tests",
        executable="textop_tracker_test_node",
        output="screen",
        parameters=[{
            "manifest_path": "system-test",
            "cuda_library_dirs": ["/tmp"],
            "lowstate_timeout": 0.5,
            "odometry_timeout": 0.5,
        }],
    )
    return launch.LaunchDescription([
        system_launch,
        generator,
        tracker,
        launch_testing.actions.ReadyToTest(),
    ])


class TestTextOpControlChain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rclpy.init()
        cls.node = rclpy.create_node("textop_control_chain_test")
        cls.asr_pub = cls.node.create_publisher(VoiceEvent, "/g1/audio/asr", 10)
        cls.action_client = ActionClient(cls.node, ExecuteMotion, "/g1/textop/execute_motion")
        cls.references = []
        cls.leases = []
        cls.candidates = []
        cls.lowcmd = []
        cls.tracker_status = []
        cls.actions = []
        cls.safe_stop = []
        cls.sport = []
        cls.subscriptions = [
            cls.node.create_subscription(
                MotionReferenceSegment, "/g1/textop/reference", cls.references.append, 10
            ),
            cls.node.create_subscription(
                LowLevelControlLease, "/g1/low_level/lease", cls.leases.append, 10
            ),
            cls.node.create_subscription(
                LowLevelCommandCandidate, "/g1/low_level/candidate", cls.candidates.append, 10
            ),
            cls.node.create_subscription(LowCmd, "/lowcmd", cls.lowcmd.append, 10),
            cls.node.create_subscription(
                TextOpTrackerStatus, "/g1/textop/tracker_status", cls.tracker_status.append, 10
            ),
            cls.node.create_subscription(ActionIntent, "/voice/cmd/action", cls.actions.append, 10),
            cls.node.create_subscription(
                ValidatedActionCommand, "/g1/safe_cmd/stop", cls.safe_stop.append, 10
            ),
            cls.node.create_subscription(Request, "/api/sport/request", cls.sport.append, 10),
        ]

    @classmethod
    def tearDownClass(cls):
        cls.action_client.destroy()
        cls.node.destroy_node()
        rclpy.shutdown()

    def wait_for(self, predicate, timeout=15.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rclpy.spin_once(self.node, timeout_sec=0.05)
            if predicate():
                return
        self.fail("timed out waiting for TextOp control-chain condition")

    def publish_asr(self, text):
        self.asr_pub.publish(VoiceEvent(
            stamp=self.node.get_clock().now().to_msg(),
            source="test",
            event_type=VoiceEvent.EVENT_ASR,
            text=text,
            has_confidence=True,
            confidence=0.99,
            is_final=True,
        ))

    def test_textop_motion_then_stop(self):
        self.wait_for(lambda: any(status.ready for status in self.tracker_status), timeout=20.0)
        self.assertTrue(self.action_client.wait_for_server(timeout_sec=5.0))

        self.publish_asr("小宇 wave")
        self.wait_for(lambda: bool(self.references))
        self.wait_for(lambda: any(lease.active for lease in self.leases))
        self.wait_for(lambda: bool(self.candidates))
        self.wait_for(lambda: bool(self.lowcmd))
        self.assertEqual(self.sport, [])

        self.publish_asr("停止")
        self.wait_for(lambda: bool(self.actions) and bool(self.safe_stop))
        self.wait_for(lambda: any(not lease.active for lease in self.leases))

        quiet_deadline = time.monotonic() + 0.15
        while time.monotonic() < quiet_deadline:
            rclpy.spin_once(self.node, timeout_sec=0.02)
        lowcmd_count = len(self.lowcmd)
        quiet_deadline = time.monotonic() + 0.2
        while time.monotonic() < quiet_deadline:
            rclpy.spin_once(self.node, timeout_sec=0.02)
        self.assertEqual(len(self.lowcmd), lowcmd_count)


@launch_testing.post_shutdown_test()
class TestProcessesExitCleanly(unittest.TestCase):
    def test_exit_codes(self, proc_info):
        launch_testing.asserts.assertExitCodes(proc_info)


if __name__ == "__main__":
    unittest.main()
