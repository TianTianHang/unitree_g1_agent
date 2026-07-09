import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    config_dir = os.path.join(get_package_share_directory("asr_node"), "config")
    return LaunchDescription([
        Node(
            package="asr_node",
            executable="asr_node",
            name="asr_node",
            output="screen",
            parameters=[{
                "config_path": os.path.join(config_dir, "asr_node.yaml"),
            }],
        ),
    ])
