from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    config_path = LaunchConfiguration("config_path")
    return LaunchDescription(
        [
            DeclareLaunchArgument("config_path", default_value=""),
            Node(
                package="voice_bridge",
                executable="voice_bridge_node",
                name="voice_bridge_node",
                output="screen",
                parameters=[{"config_path": config_path}],
            ),
        ]
    )
