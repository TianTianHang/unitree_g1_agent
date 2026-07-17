from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
from pathlib import Path
from typing import Any

import yaml


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class AssetManifest:
    path: Path
    sha256: str


@dataclass(frozen=True)
class GeneratorManifest:
    checkpoint: AssetManifest
    vae: AssetManifest
    statistics: AssetManifest
    normalization: AssetManifest


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
    generator: GeneratorManifest
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

    @property
    def unitree_to_isaaclab(self) -> tuple[int, ...]:
        lookup = {name: index for index, name in enumerate(self.isaaclab_joint_names)}
        return tuple(lookup[name] for name in self.unitree_joint_names)


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


def _asset(manifest_path: Path, raw: Any, name: str, verify: bool) -> AssetManifest:
    if not isinstance(raw, dict):
        raise ManifestError(f"{name} must be an asset mapping")
    path_value = raw.get("path")
    if not isinstance(path_value, str) or not path_value:
        raise ManifestError(f"{name}.path must not be empty")
    path = (manifest_path.parent / path_value).resolve()
    digest_text = str(raw.get("sha256", ""))
    if len(digest_text) != 64 or any(c not in "0123456789abcdefABCDEF" for c in digest_text):
        raise ManifestError(f"{name}.sha256 must be a SHA-256 hex digest")
    if verify:
        if not path.is_file():
            raise ManifestError(f"{name} asset does not exist: {path}")
        digest = hashlib.sha256()
        with path.open("rb") as asset_file:
            for chunk in iter(lambda: asset_file.read(1024 * 1024), b""):
                digest.update(chunk)
        if not hmac.compare_digest(digest.hexdigest(), digest_text.lower()):
            raise ManifestError(f"{name} SHA-256 mismatch: {path}")
    return AssetManifest(path=path, sha256=digest_text.lower())


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
    policy_asset = _asset(manifest_path, policy_raw, "policy", verify_assets)
    policy = PolicyManifest(
        path=policy_asset.path,
        sha256=policy_asset.sha256,
        input_name=str(policy_raw.get("input_name", "")),
        output_name=str(policy_raw.get("output_name", "")),
        input_shape=tuple(policy_raw.get("input_shape", ())),
        output_shape=tuple(policy_raw.get("output_shape", ())),
    )
    if policy.input_shape != (1, 431) or policy.output_shape != (1, 29):
        raise ManifestError("policy shapes must be [1,431] and [1,29]")
    generator_raw = raw.get("generator")
    if not isinstance(generator_raw, dict):
        raise ManifestError("generator must be an asset mapping")
    generator = GeneratorManifest(
        checkpoint=_asset(manifest_path, generator_raw.get("checkpoint"), "generator.checkpoint", verify_assets),
        vae=_asset(manifest_path, generator_raw.get("vae"), "generator.vae", verify_assets),
        statistics=_asset(manifest_path, generator_raw.get("statistics"), "generator.statistics", verify_assets),
        normalization=_asset(manifest_path, generator_raw.get("normalization"), "generator.normalization", verify_assets),
    )
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
        generator=generator,
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
