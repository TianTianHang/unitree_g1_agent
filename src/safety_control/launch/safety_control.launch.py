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
                package="safety_control",
                executable="safety_control_node",
                name="safety_control_node",
                output="screen",
                parameters=[{"config_path": config_path}],
            ),
        ]
    )
