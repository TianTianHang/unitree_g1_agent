from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription(
        [
            Node(
                package="voice_bridge_debug",
                executable="debug_panel_server",
                name="voice_bridge_debug_node",
                output="screen",
                arguments=[],
            )
        ]
    )
