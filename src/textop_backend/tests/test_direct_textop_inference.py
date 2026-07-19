import ast
from pathlib import Path

ROOT = Path(__file__).parents[1] / "textop_backend"


def test_direct_inference_sources_do_not_import_robotmdar():
    files = [ROOT / "robotmdar_runtime.py", *sorted((ROOT / "textop_model").rglob("*.py"))]
    for path in files:
        tree = ast.parse(path.read_text(), filename=str(path))
        imports = [node for node in ast.walk(tree) if isinstance(node, ast.Import | ast.ImportFrom)]
        names = [alias.name for node in imports for alias in node.names]
        assert all(not name.startswith("robotmdar") for name in names), path


def test_runtime_constructs_project_local_models_without_hydra():
    source = (ROOT / "robotmdar_runtime.py").read_text()
    assert "textop_model.model.mld_vae" in source
    assert "textop_model.model.mld_denoiser" in source
    assert "from hydra" not in source
    assert "instantiate(" not in source


def test_model_config_is_owned_by_project_without_external_hydra_yaml():
    from textop_backend.robotmdar_runtime import _textop_model_configs

    vae, denoiser = _textop_model_configs()

    assert vae["nfeats"] == 57
    assert vae["latent_dim"] == [1, 128]
    assert denoiser["history_shape"] == [2, 57]
    assert denoiser["noise_shape"] == [1, 128]


def test_runtime_loads_clip_only_from_explicit_local_weights():
    source = (ROOT / "robotmdar_runtime.py").read_text()

    assert 'clip.load(str(clip_weights)' in source
    assert 'clip.load("ViT-B/32"' not in source
    assert 'checkpoint.parent / ".hydra"' not in source


def test_generator_interface_has_no_unused_skeleton_or_statistics_assets():
    package_root = ROOT.parent
    generator_source = (ROOT / "generator_node.py").read_text()
    launch_source = (package_root / "launch" / "textop_backend.launch.py").read_text()
    config_source = (package_root / "config" / "textop_generator.yaml").read_text()

    for source in (generator_source, launch_source, config_source):
        assert "skeleton_asset_root" not in source
    assert "generator.statistics" not in generator_source


def test_zero_feature_matches_textop_v3_standing_seed():
    import pytest
    torch = pytest.importorskip("torch")
    from textop_backend.textop_model.motion import zero_feature

    value = zero_feature(1, 2, 57, torch.device("cpu"))

    assert value.shape == (1, 2, 57)
    assert torch.all(value[..., 5:7] == 1.0)
    assert torch.all(value[..., 10] == 0.75)
    assert value[0, 0, 11:34].tolist() == pytest.approx([
        -0.1, 0.0, 0.0, 0.3, -0.2, 0.0, -0.1, 0.0, 0.0, 0.3, -0.2,
        0.0, 0.0, 0.0, 0.0, 0.2, 0.2, 0.0, 0.9, 0.2, -0.2, 0.0, 0.9,
    ])


def test_dof_velocity_matches_textop_forward_difference_layout():
    import pytest
    torch = pytest.importorskip("torch")
    from textop_backend.robotmdar_runtime import _textop_dof_velocity

    dof = torch.tensor([[0.0], [1.0], [3.0], [6.0]])

    velocity = _textop_dof_velocity(dof, dt=0.5)

    assert velocity[:, 0].tolist() == pytest.approx([2.0, 4.0, 6.0, 4.0])
