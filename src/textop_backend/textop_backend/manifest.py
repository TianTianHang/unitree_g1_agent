from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class PolicyManifest:
    path: Path
    sha256: str
    input_name: str
    output_name: str
    input_shape: tuple[int, ...]
    output_shape: tuple[int, ...]


@dataclass(frozen=True)
class ModelManifest:
    model_id: str
    robot_profile: str
    control_profile: str
    control_frequency: float
    policy: PolicyManifest
    isaaclab_joint_names: tuple[str, ...]
    unitree_joint_names: tuple[str, ...]
    default_q: tuple[float, ...]
    action_scale: tuple[float, ...]
    kp: tuple[float, ...]
    kd: tuple[float, ...]
    future_steps: int
    anchor_body: str
    quaternion_order: str

    @property
    def control_period(self) -> float:
        return 1.0 / self.control_frequency

    @property
    def isaaclab_to_unitree(self) -> tuple[int, ...]:
        lookup = {name: index for index, name in enumerate(self.unitree_joint_names)}
        return tuple(lookup[name] for name in self.isaaclab_joint_names)


def _sequence(data: dict[str, Any], key: str, length: int) -> tuple[float, ...]:
    value = data.get(key)
    if not isinstance(value, list) or len(value) != length:
        raise ManifestError(f"{key} must contain {length} values")
    try:
        result = tuple(float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"{key} contains a non-numeric value") from exc
    return result


def _joint_names(data: Any, key: str) -> tuple[str, ...]:
    if not isinstance(data, list) or len(data) != 29 or not all(isinstance(item, str) and item for item in data):
        raise ManifestError(f"joint_names.{key} must contain 29 non-empty joint names")
    if len(set(data)) != 29:
        raise ManifestError(f"joint_names.{key} contains duplicate joint names")
    return tuple(data)


def load_manifest(path: Path | str, *, verify_assets: bool = True) -> ModelManifest:
    manifest_path = Path(path).resolve()
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ManifestError("unsupported schema_version")
    joints = raw.get("joint_names", {})
    isaaclab = _joint_names(joints.get("isaaclab"), "isaaclab")
    unitree = _joint_names(joints.get("unitree"), "unitree")
    if set(isaaclab) != set(unitree):
        raise ManifestError("joint name sets must form a bijection")
    policy_raw = raw.get("policy", {})
    policy_path = (manifest_path.parent / str(policy_raw.get("path", ""))).resolve()
    sha256 = str(policy_raw.get("sha256", ""))
    if len(sha256) != 64:
        raise ManifestError("policy.sha256 must be a SHA-256 hex digest")
    if verify_assets and not policy_path.is_file():
        raise ManifestError(f"policy asset does not exist: {policy_path}")
    policy = PolicyManifest(
        path=policy_path,
        sha256=sha256,
        input_name=str(policy_raw.get("input_name", "")),
        output_name=str(policy_raw.get("output_name", "")),
        input_shape=tuple(policy_raw.get("input_shape", ())),
        output_shape=tuple(policy_raw.get("output_shape", ())),
    )
    if policy.input_shape != (1, 431) or policy.output_shape != (1, 29):
        raise ManifestError("policy shapes must be [1,431] and [1,29]")
    frequency = float(raw.get("control_frequency", 0.0))
    reference = raw.get("reference", {})
    if frequency != 50.0 or reference.get("future_steps") != 5:
        raise ManifestError("TextOp v1 requires 50 Hz and five future steps")
    if reference.get("quaternion_order") != "wxyz":
        raise ManifestError("TextOp v1 requires wxyz quaternions")
    return ModelManifest(
        model_id=str(raw.get("model_id", "")),
        robot_profile=str(raw.get("robot_profile", "")),
        control_profile=str(raw.get("control_profile", "")),
        control_frequency=frequency,
        policy=policy,
        isaaclab_joint_names=isaaclab,
        unitree_joint_names=unitree,
        default_q=_sequence(raw, "default_q", 29),
        action_scale=_sequence(raw, "action_scale", 29),
        kp=_sequence(raw, "kp", 29),
        kd=_sequence(raw, "kd", 29),
        future_steps=5,
        anchor_body=str(reference.get("anchor_body", "")),
        quaternion_order="wxyz",
    )
