from pathlib import Path
import hashlib

import pytest

from textop_backend.manifest import ManifestError, load_manifest


ISAACLAB = [f"joint_{index}" for index in range(29)]
UNITREE = list(reversed(ISAACLAB))


def _manifest() -> dict:
    return {
        "schema_version": 1,
        "model_id": "textop-test",
        "robot_profile": "g1_29dof_unitree_v1",
        "control_profile": "textop_tracker_v1",
        "control_frequency": 50,
        "policy": {
            "path": "policy.onnx",
            "sha256": "a" * 64,
            "input_name": "obs",
            "output_name": "actions",
            "input_shape": [1, 431],
            "output_shape": [1, 29],
        },
        "generator": {
            "checkpoint": {"path": "ckpt.pth", "sha256": "b" * 64},
            "vae": {"path": "vae.pth", "sha256": "c" * 64},
            "statistics": {"path": "action_statistics.json", "sha256": "d" * 64},
            "normalization": {"path": "meanstd.pkl", "sha256": "e" * 64},
        },
        "joint_names": {"isaaclab": list(ISAACLAB), "unitree": list(UNITREE)},
        "default_q": [0.0] * 29,
        "action_scale": [0.25] * 29,
        "kp": [40.0] * 29,
        "kd": [1.0] * 29,
        "reference": {"future_steps": 5, "anchor_body": "torso_link", "quaternion_order": "wxyz"},
    }


def _write_generator_assets(tmp_path: Path, data: dict) -> None:
    for name, asset in data["generator"].items():
        content = f"{name} bytes".encode()
        (tmp_path / asset["path"]).write_bytes(content)
        asset["sha256"] = hashlib.sha256(content).hexdigest()


def test_load_manifest_builds_joint_bijection(tmp_path: Path):
    import yaml

    path = tmp_path / "model.yaml"
    path.write_text(yaml.safe_dump(_manifest()), encoding="utf-8")
    manifest = load_manifest(path, verify_assets=False)

    assert manifest.control_period == pytest.approx(0.02)
    assert manifest.isaaclab_to_unitree == tuple(reversed(range(29)))
    assert manifest.generator.checkpoint.path == tmp_path / "ckpt.pth"


def test_manifest_rejects_duplicate_joint_names(tmp_path: Path):
    import yaml

    data = _manifest()
    data["joint_names"]["isaaclab"][1] = data["joint_names"]["isaaclab"][0]
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(ManifestError, match="joint"):
        load_manifest(path, verify_assets=False)


def test_joint_mapping_direction_is_explicit(tmp_path: Path):
    import yaml

    data = _manifest()
    data["joint_names"]["unitree"] = ISAACLAB[1:] + ISAACLAB[:1]
    path = tmp_path / "mapping.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    manifest = load_manifest(path, verify_assets=False)

    assert manifest.isaaclab_to_unitree[:3] == (28, 0, 1)
    assert manifest.unitree_to_isaaclab[:3] == (1, 2, 3)


def test_manifest_verifies_policy_sha256(tmp_path: Path):
    import yaml

    policy = tmp_path / "policy.onnx"
    policy.write_bytes(b"known policy bytes")
    data = _manifest()
    _write_generator_assets(tmp_path, data)
    data["policy"]["sha256"] = hashlib.sha256(policy.read_bytes()).hexdigest()
    path = tmp_path / "model.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    load_manifest(path)
    data["policy"]["sha256"] = "0" * 64
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ManifestError, match="SHA-256 mismatch"):
        load_manifest(path)


def test_manifest_rejects_non_hex_digest(tmp_path: Path):
    import yaml

    data = _manifest()
    data["policy"]["sha256"] = "z" * 64
    path = tmp_path / "model.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ManifestError, match="hex digest"):
        load_manifest(path, verify_assets=False)


@pytest.mark.parametrize("asset_name", ["checkpoint", "vae", "statistics", "normalization"])
def test_manifest_verifies_every_generator_asset(tmp_path: Path, asset_name: str):
    import yaml

    data = _manifest()
    _write_generator_assets(tmp_path, data)
    policy = tmp_path / "policy.onnx"
    policy.write_bytes(b"policy bytes")
    data["policy"]["sha256"] = hashlib.sha256(policy.read_bytes()).hexdigest()
    data["generator"][asset_name]["sha256"] = "0" * 64
    path = tmp_path / "model.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(ManifestError, match=asset_name):
        load_manifest(path)
