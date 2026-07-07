from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from voice_bridge.pi_types import BLOCKED_ENV_PREFIXES, DEFAULT_PI_TIMEOUTS

DEFAULT_PI_WORKSPACE = Path(".agent-runtime") / ".unitree_agent"
DEFAULT_ROBOT_TOOLS_EXTENSION = "src/voice_bridge/pi_extensions/robot-tools.ts"

ROBOT_APPEND_SYSTEM_PROMPT = (
    "You control a Unitree G1 robot only by calling robot_* tools. "
    "Use robot_walk for movement, robot_stop for immediate stop, robot_say for speech, "
    "and robot_led for LED color. Motion safety limits are enforced outside Pi by voice_bridge."
)

DEFAULT_PI_CONFIG: dict[str, Any] = {
    "enabled": True,
    "command": "pi",
    "args": ["--mode", "rpc", "--no-session"],
    "workspace": str(DEFAULT_PI_WORKSPACE),
    "model": "",
    "provider": "",
    "extensions": [DEFAULT_ROBOT_TOOLS_EXTENSION],
    "env_keep": ["HOME", "PATH", "NODE_PATH", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"],
    "env_extra": {},
    "timeouts": deepcopy(DEFAULT_PI_TIMEOUTS),
    "append_system_prompt": ROBOT_APPEND_SYSTEM_PROMPT,
}


def _blocked(key: str) -> bool:
    return key.startswith(BLOCKED_ENV_PREFIXES)


def resolve_repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return current


def resolve_workspace(pi_config: dict[str, Any], repo_root: Path) -> Path:
    raw = pi_config.get("workspace") or str(DEFAULT_PI_WORKSPACE)
    path = Path(str(raw))
    if not path.is_absolute():
        path = repo_root / path
    return path


def _resolve_extension_path(extension: str, repo_root: Path | None) -> str:
    path = Path(extension)
    if path.is_absolute():
        return str(path)
    root = repo_root or resolve_repo_root()
    return str(root / path)


def build_pi_command(pi_config: dict[str, Any], workspace: Path, repo_root: Path | None = None) -> list[str]:
    command = str(pi_config.get("command") or "pi")
    args = pi_config.get("args", ["--mode", "rpc", "--no-session"])
    cmd = [command, *list(args)]
    model = str(pi_config.get("model") or "")
    provider = str(pi_config.get("provider") or "")
    if model:
        cmd.extend(["--model", model])
    if provider:
        cmd.extend(["--provider", provider])
    robot_tools = workspace / ".pi" / "extensions" / "robot-tools.ts"
    if robot_tools.exists():
        cmd.extend(["-e", str(robot_tools)])
    for extension in pi_config.get("extensions", []):
        cmd.extend(["-e", _resolve_extension_path(str(extension), repo_root)])
    append_prompt = str(pi_config.get("append_system_prompt", DEFAULT_PI_CONFIG["append_system_prompt"]) or "")
    if append_prompt:
        cmd.extend(["--append-system-prompt", append_prompt])
    return cmd


def scrubbed_env(pi_config: dict[str, Any], base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    source = dict(os.environ if base_env is None else base_env)
    keep = set(pi_config.get("env_keep", DEFAULT_PI_CONFIG["env_keep"]))
    keep = {key for key in keep if not _blocked(str(key))}
    env = {key: value for key, value in source.items() if key in keep and not _blocked(key)}
    for key, value in pi_config.get("env_extra", {}).items():
        if not _blocked(str(key)):
            env[str(key)] = str(value)
    return env


def validate_pi_config(pi_config: object) -> None:
    if not isinstance(pi_config, dict):
        raise ValueError("agent.pi must be a mapping")
    enabled = pi_config.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("agent.pi.enabled must be boolean")
    if not enabled:
        raise ValueError("agent.backend=pi_rpc requires agent.pi.enabled=true")
    command = pi_config.get("command", "pi")
    if not isinstance(command, str) or not command:
        raise ValueError("agent.pi.command must be non-empty string")
    workspace = pi_config.get("workspace", str(DEFAULT_PI_WORKSPACE))
    if not isinstance(workspace, str):
        raise ValueError("agent.pi.workspace must be string")
    args = pi_config.get("args", ["--mode", "rpc", "--no-session"])
    if not isinstance(args, list) or any(not isinstance(item, str) for item in args):
        raise ValueError("agent.pi.args must be list[str]")
    extensions = pi_config.get("extensions", [])
    if not isinstance(extensions, list) or any(not isinstance(item, str) for item in extensions):
        raise ValueError("agent.pi.extensions must be list[str]")
    for key in ("model", "provider", "append_system_prompt"):
        if key in pi_config and pi_config[key] is not None and not isinstance(pi_config[key], str):
            raise ValueError(f"agent.pi.{key} must be string")
    env_keep = pi_config.get("env_keep", DEFAULT_PI_CONFIG["env_keep"])
    if not isinstance(env_keep, list) or any(not isinstance(item, str) or not item for item in env_keep):
        raise ValueError("agent.pi.env_keep must be a non-empty string list")
    for key in env_keep:
        if _blocked(key):
            raise ValueError(f"agent.pi.env_keep key '{key}' is not allowed")
    env_extra = pi_config.get("env_extra", {})
    if not isinstance(env_extra, dict):
        raise ValueError("agent.pi.env_extra must be mapping")
    for key in env_extra:
        if not isinstance(key, str):
            raise ValueError("agent.pi.env_extra keys must be strings")
        if _blocked(key):
            raise ValueError(f"agent.pi.env_extra key '{key}' is not allowed")
    timeouts = pi_config.get("timeouts", {})
    if not isinstance(timeouts, dict):
        raise ValueError("agent.pi.timeouts must be mapping")
    for key, value in timeouts.items():
        if key == "restart_max_attempts":
            if not isinstance(value, int) or value <= 0:
                raise ValueError("agent.pi.timeouts.restart_max_attempts must be positive integer")
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"agent.pi.timeouts.{key} must be positive")
