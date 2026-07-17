from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    config = os.path.join(get_package_share_directory("textop_backend"), "config", "textop_tracker.yaml")
    return LaunchDescription(
        [
            DeclareLaunchArgument("manifest_path", default_value=os.path.join(config.rsplit("/", 1)[0], "textop_pretrained.yaml")),
            Node(
                package="textop_backend",
                executable="textop_tracker_node",
                name="textop_tracker_node",
                output="screen",
                parameters=[config, {"manifest_path": LaunchConfiguration("manifest_path")}],
            ),
        ]
    )
