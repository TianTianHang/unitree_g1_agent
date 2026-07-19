from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    config_path = LaunchConfiguration("config_path")
    asr_source_mode = LaunchConfiguration("asr_source_mode")
    motion_backend = LaunchConfiguration("motion_backend")
    return LaunchDescription(
        [
            DeclareLaunchArgument("config_path", default_value=""),
            DeclareLaunchArgument("asr_source_mode", default_value=""),
            DeclareLaunchArgument("motion_backend", default_value="official_loco"),
            Node(
                package="g1_interface",
                executable="g1_interface_node",
                name="g1_interface_node",
                output="screen",
                parameters=[{
                    "config_path": config_path,
                    "asr_source_mode": asr_source_mode,
                    "motion_backend": motion_backend,
                }],
            ),
        ]
    )
