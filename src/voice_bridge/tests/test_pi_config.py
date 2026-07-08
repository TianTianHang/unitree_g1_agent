from pathlib import Path

import pytest

from voice_bridge.pi_config import (
    DEFAULT_PI_CONFIG,
    build_pi_command,
    resolve_repo_root,
    resolve_workspace,
    scrubbed_env,
    validate_pi_config,
)


def test_resolve_workspace_defaults_under_repo_root(tmp_path: Path):
    workspace = resolve_workspace({}, tmp_path)

    assert workspace == tmp_path / ".agent-runtime" / ".unitree_agent"


def test_resolve_workspace_accepts_absolute_path(tmp_path: Path):
    absolute = tmp_path / "pi-workspace"

    assert resolve_workspace({"workspace": str(absolute)}, tmp_path) == absolute


def test_resolve_repo_root_searches_for_git_marker(tmp_path: Path):
    root = tmp_path / "repo"
    child = root / "src" / "voice_bridge"
    child.mkdir(parents=True)
    (root / ".git").mkdir()

    assert resolve_repo_root(child) == root


def test_default_pi_config_lists_tracked_robot_tools_extension():
    assert DEFAULT_PI_CONFIG["extensions"] == ["src/voice_bridge/pi_extensions/robot-tools.ts"]


def test_build_pi_command_loads_robot_tools_when_present(tmp_path: Path):
    workspace = tmp_path / ".agent-runtime" / ".unitree_agent"
    tools = workspace / ".pi" / "extensions" / "robot-tools.ts"
    tools.parent.mkdir(parents=True)
    tools.write_text("export default function() {}", encoding="utf-8")

    command = build_pi_command(
        {
            "command": "pi",
            "args": ["--mode", "rpc", "--no-session"],
            "model": "gpt-5-mini",
            "provider": "openai",
            "extensions": [],
        },
        workspace,
    )

    assert command == [
        "pi",
        "--mode",
        "rpc",
        "--no-session",
        "--model",
        "gpt-5-mini",
        "--provider",
        "openai",
        "-e",
        str(tools),
        "--append-system-prompt",
        DEFAULT_PI_CONFIG["append_system_prompt"],
    ]


def test_build_pi_command_loads_configured_extensions_without_workspace_tools(tmp_path: Path):
    workspace = tmp_path / ".agent-runtime" / ".unitree_agent"
    repo_root = tmp_path / "repo"

    command = build_pi_command(
        {
            "command": "pi",
            "args": ["--mode", "rpc", "--no-session"],
            "extensions": ["src/voice_bridge/pi_extensions/robot-tools.ts"],
            "append_system_prompt": "",
        },
        workspace,
        repo_root=repo_root,
    )

    assert command == [
        "pi",
        "--mode",
        "rpc",
        "--no-session",
        "-e",
        str(repo_root / "src/voice_bridge/pi_extensions/robot-tools.ts"),
    ]


def test_scrubbed_env_removes_ros_dds_and_ssh_values():
    env = scrubbed_env(
        {
            "env_keep": ["HOME", "PATH", "ROS_DOMAIN_ID", "OPENAI_API_KEY"],
            "env_extra": {"SAFE_VALUE": "1", "ROS_LOCALHOST_ONLY": "1"},
        },
        base_env={
            "HOME": "/home/test",
            "PATH": "/usr/bin",
            "ROS_DOMAIN_ID": "7",
            "RMW_IMPLEMENTATION": "rmw",
            "CYCLONEDDS_URI": "file.xml",
            "SSH_AUTH_SOCK": "sock",
            "OPENAI_API_KEY": "sk-test",
        },
    )

    assert env == {
        "HOME": "/home/test",
        "PATH": "/usr/bin",
        "OPENAI_API_KEY": "sk-test",
        "SAFE_VALUE": "1",
    }


def test_scrubbed_env_prepends_absolute_pi_command_directory_to_path():
    env = scrubbed_env(
        {
            "command": "/opt/node/bin/pi",
            "env_keep": ["PATH"],
            "env_extra": {},
        },
        base_env={"PATH": "/usr/bin"},
    )

    assert env["PATH"] == "/opt/node/bin:/usr/bin"


@pytest.mark.parametrize(
    ("pi_config", "message"),
    [
        ([], "agent.pi must be a mapping"),
        ({"enabled": False}, "agent.backend=pi_rpc requires agent.pi.enabled=true"),
        ({"command": ""}, "agent.pi.command must be non-empty string"),
        ({"args": "--mode rpc"}, "agent.pi.args must be list\\[str\\]"),
        ({"extensions": [1]}, "agent.pi.extensions must be list\\[str\\]"),
        ({"env_keep": ["ROS_DOMAIN_ID"]}, "agent.pi.env_keep key 'ROS_DOMAIN_ID' is not allowed"),
        ({"env_extra": {"SSH_AUTH_SOCK": "sock"}}, "agent.pi.env_extra key 'SSH_AUTH_SOCK' is not allowed"),
        ({"timeouts": {"restart_max_attempts": 0}}, "restart_max_attempts must be positive integer"),
    ],
)
def test_validate_pi_config_rejects_invalid_values(pi_config, message):
    with pytest.raises(ValueError, match=message):
        validate_pi_config(pi_config)
