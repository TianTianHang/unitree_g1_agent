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
                package="g1_interface",
                executable="g1_interface_node",
                name="g1_interface_node",
                output="screen",
                parameters=[{"config_path": config_path}],
            ),
        ]
    )
