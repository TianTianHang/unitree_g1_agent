from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_textop_dependency_group_contains_direct_runtime_dependencies():
    source = (ROOT / "pyproject.toml").read_text()
    start = source.index("textop = [")
    dependencies = source[start:source.index("]", start)]

    assert "torch==2.5.1" in dependencies
    assert "torchvision==0.20.1" in dependencies
    assert "openai-clip==1.0.1" in dependencies
    assert "einops==0.8.1" in dependencies
    assert "onnxruntime-gpu==1.17.1" in dependencies
    assert "numpy==1.26.4" in dependencies
    assert "pytest==8.3.5" in dependencies


def test_textop_uses_cuda_118_index_and_conflicts_with_asr_group():
    source = (ROOT / "pyproject.toml").read_text()

    assert 'name = "pytorch-cu118"' in source
    assert 'url = "https://download.pytorch.org/whl/cu118"' in source
    assert 'torch = { index = "pytorch-cu118" }' in source
    assert 'torchvision = { index = "pytorch-cu118" }' in source
    assert '{ group = "asr" }, { group = "textop" }' in source
    assert '{ group = "test" }, { group = "textop" }' in source
    assert 'textop_cudnn8 = [' in source
    assert 'nvidia-cudnn-cu11==8.9.6.50' in source
    assert '{ group = "textop" }, { group = "textop_cudnn8" }' in source
    assert '{ group = "asr" }, { group = "textop_cudnn8" }' in source


def test_makefile_bootstrap_textop_syncs_project_ros_environment():
    source = (ROOT / "Makefile").read_text()

    assert "bootstrap-env:" in source
    assert "bootstrap: bootstrap-env" in source
    assert "bootstrap-textop: bootstrap-env" in source
    assert "uv sync --frozen --no-default-groups --group textop" in source
    assert "build-textop: bootstrap-textop" in source
    assert "$(UV_ENV)/bin/python -m colcon build" in source
    assert "TEXTOP_CUDNN_ENV := $(COMMON_REPO_ROOT)/.unitree/textop-cudnn8-venv" in source
    assert "--group textop_cudnn8" in source
    assert "openaipublic.azureedge.net/clip/models/$(TEXTOP_CLIP_SHA256)/ViT-B-32.pt" in source
    assert "40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af" in source
    assert "$(COMMON_REPO_ROOT)/.unitree/models/textop/ViT-B-32.pt" in source


def test_bootstrap_does_not_reject_compatible_uv_patch_versions():
    source = (ROOT / "Makefile").read_text()

    assert 'uv 0.11.26' not in source
    assert "uv --version >/dev/null" in source
