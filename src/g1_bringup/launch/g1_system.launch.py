from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, LogInfo, OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare

from g1_bringup.backend import backend_plan


def _include(package: str, launch_file: str, arguments=None):
    source = PythonLaunchDescriptionSource(
        [get_package_share_directory(package), "/launch/", launch_file]
    )
    return IncludeLaunchDescription(source, launch_arguments=(arguments or {}).items())


def _construct_backend(context):
    backend = LaunchConfiguration("motion_backend").perform(context)
    plan = backend_plan(backend)
    actions = [
        LogInfo(msg=f"configured_backend={backend} runtime_switching=false"),
        _include(
            "g1_interface",
            "g1_interface.launch.py",
            {"motion_backend": plan["g1_interface_backend"]},
        ),
    ]
    if plan["start_textop"]:
        actions.append(_include("textop_backend", "textop_backend.launch.py", {
            "manifest_path": LaunchConfiguration("textop_manifest_path"),
            "device": LaunchConfiguration("textop_device"),
        }))
    if plan["start_low_level_guard"]:
        actions.append(_include("low_level_guard", "low_level_guard.launch.py"))
    return actions


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("motion_backend", default_value="official_loco"),
        DeclareLaunchArgument(
            "textop_manifest_path",
            default_value=PathJoinSubstitution(
                [FindPackageShare("textop_backend"), "config", "textop_pretrained.yaml"]
            ),
        ),
        DeclareLaunchArgument("textop_device", default_value="cuda:3"),
        OpaqueFunction(function=_construct_backend),
    ])
