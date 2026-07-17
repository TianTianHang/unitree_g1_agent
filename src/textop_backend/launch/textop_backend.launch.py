import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    share = get_package_share_directory("textop_backend")
    generator_config = os.path.join(share, "config", "textop_generator.yaml")
    tracker_config = os.path.join(share, "config", "textop_tracker.yaml")
    arguments = [
        DeclareLaunchArgument(
            "manifest_path", default_value=os.path.join(share, "config", "textop_pretrained.yaml")
        ),
        DeclareLaunchArgument(
            "skeleton_asset_root",
            default_value="/home/ubuntu/Desktop/TextOp/TextOpRobotMDAR/description/robots/g1",
        ),
        DeclareLaunchArgument("device", default_value="cuda:3"),
    ]
    return LaunchDescription(arguments + [
        Node(
            package="textop_backend", executable="textop_generator_node",
            name="textop_generator_node", output="screen",
            parameters=[generator_config, {
                "manifest_path": LaunchConfiguration("manifest_path"),
                "skeleton_asset_root": LaunchConfiguration("skeleton_asset_root"),
                "device": LaunchConfiguration("device"),
            }],
        ),
        Node(
            package="textop_backend", executable="textop_tracker_node",
            name="textop_tracker_node", output="screen",
            parameters=[tracker_config, {"manifest_path": LaunchConfiguration("manifest_path")}],
        ),
    ])
