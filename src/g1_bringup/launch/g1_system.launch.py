from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    GroupAction,
    IncludeLaunchDescription,
    LogInfo,
    OpaqueFunction,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare

from g1_bringup.backend import backend_plan


def _include(package: str, launch_file: str, arguments=None):
    source = PythonLaunchDescriptionSource(
        [get_package_share_directory(package), "/launch/", launch_file]
    )
    include = IncludeLaunchDescription(source, launch_arguments=(arguments or {}).items())
    return GroupAction(actions=[include], scoped=True)


def _enabled(context, name: str) -> bool:
    return LaunchConfiguration(name).perform(context).strip().lower() in {"1", "true", "yes", "on"}


def _construct_backend(context):
    backend = LaunchConfiguration("motion_backend").perform(context)
    plan = backend_plan(backend)
    actions = [
        LogInfo(
            msg=(
                f"configured_backend={backend} runtime_switching=false "
                f"start_sim={_enabled(context, 'start_sim')}"
            )
        ),
    ]
    if _enabled(context, "start_sim"):
        actions.append(_include(
            "g1_sim",
            "g1_sim.launch.py",
            {"config_path": LaunchConfiguration("sim_config_path")},
        ))
    actions.extend([
        _include(
            "g1_interface",
            "g1_interface.launch.py",
            {
                "config_path": LaunchConfiguration("g1_interface_config_path"),
                "asr_source_mode": LaunchConfiguration("asr_source_mode"),
                "motion_backend": plan["g1_interface_backend"],
            },
        ),
        _include(
            "safety_control",
            "safety_control.launch.py",
            {"config_path": LaunchConfiguration("safety_config_path")},
        ),
        _include(
            "voice_bridge",
            "voice_bridge.launch.py",
            {
                "config_path": LaunchConfiguration("voice_config_path"),
                "motion_backend": backend,
            },
        ),
    ])
    if _enabled(context, "start_custom_asr"):
        actions.append(_include("asr_node", "asr_node.launch.py"))
    if plan["start_textop"] and _enabled(context, "start_textop_runtime"):
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
            "g1_interface_config_path",
            default_value=PathJoinSubstitution(
                [FindPackageShare("g1_interface"), "config", "g1_interface.yaml"]
            ),
        ),
        DeclareLaunchArgument(
            "safety_config_path",
            default_value=PathJoinSubstitution(
                [FindPackageShare("safety_control"), "config", "safety_control.yaml"]
            ),
        ),
        DeclareLaunchArgument(
            "voice_config_path",
            default_value=PathJoinSubstitution(
                [FindPackageShare("voice_bridge"), "config", "voice_bridge.yaml"]
            ),
        ),
        DeclareLaunchArgument("asr_source_mode", default_value=""),
        DeclareLaunchArgument("start_custom_asr", default_value="false"),
        DeclareLaunchArgument("start_sim", default_value="false"),
        DeclareLaunchArgument("sim_config_path", default_value=""),
        DeclareLaunchArgument(
            "textop_manifest_path",
            default_value=PathJoinSubstitution(
                [FindPackageShare("textop_backend"), "config", "textop_pretrained.yaml"]
            ),
        ),
        DeclareLaunchArgument("textop_device", default_value="cuda:3"),
        DeclareLaunchArgument("start_textop_runtime", default_value="true"),
        OpaqueFunction(function=_construct_backend),
    ])
