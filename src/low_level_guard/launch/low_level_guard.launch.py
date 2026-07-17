from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    config_path = LaunchConfiguration("config_path")
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "config_path",
                default_value=PathJoinSubstitution(
                    [FindPackageShare("low_level_guard"), "config", "low_level_guard.yaml"]
                ),
            ),
            Node(
                package="low_level_guard",
                executable="low_level_guard_node",
                name="low_level_guard_node",
                output="screen",
                parameters=[config_path],
            ),
        ]
    )
