from pathlib import Path

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
        "joint_names": {"isaaclab": ISAACLAB, "unitree": UNITREE},
        "default_q": [0.0] * 29,
        "action_scale": [0.25] * 29,
        "kp": [40.0] * 29,
        "kd": [1.0] * 29,
        "reference": {"future_steps": 5, "anchor_body": "torso_link", "quaternion_order": "wxyz"},
    }


def test_load_manifest_builds_joint_bijection(tmp_path: Path):
    import yaml

    path = tmp_path / "model.yaml"
    path.write_text(yaml.safe_dump(_manifest()), encoding="utf-8")
    manifest = load_manifest(path, verify_assets=False)

    assert manifest.control_period == pytest.approx(0.02)
    assert manifest.isaaclab_to_unitree == tuple(reversed(range(29)))


def test_manifest_rejects_duplicate_joint_names(tmp_path: Path):
    import yaml

    data = _manifest()
    data["joint_names"]["isaaclab"][1] = data["joint_names"]["isaaclab"][0]
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(ManifestError, match="joint"):
        load_manifest(path, verify_assets=False)
