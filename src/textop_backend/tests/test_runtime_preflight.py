import pytest

from textop_backend.runtime_preflight import (
    PreflightError,
    RuntimeFacts,
    validate_generator_runtime,
    validate_tracker_runtime,
)


def _facts(**overrides):
    values = {
        "python_version": (3, 10, 12),
        "torch_version": "2.7.1",
        "cuda_available": True,
        "cuda_device_count": 4,
        "onnxruntime_version": "1.22.0",
        "onnx_providers": ("CUDAExecutionProvider", "CPUExecutionProvider"),
    }
    values.update(overrides)
    return RuntimeFacts(**values)


def test_generator_runtime_accepts_gpu_3_without_robotmdar_distribution():
    report = validate_generator_runtime(_facts(), device="cuda:3")

    assert report.device_index == 3
    assert report.torch_version == "2.7.1"


@pytest.mark.parametrize("device", ["cuda", "cuda:0", "cpu", "cuda:4", "cuda:not-a-number"])
def test_generator_runtime_rejects_device_other_than_available_gpu_3(device):
    with pytest.raises(PreflightError):
        validate_generator_runtime(_facts(), device=device)


def test_generator_runtime_rejects_wrong_python_or_missing_cuda():
    facts = _facts(python_version=(3, 11, 9), cuda_available=False)

    with pytest.raises(PreflightError) as error:
        validate_generator_runtime(facts, device="cuda:3")

    assert "Python 3.10" in str(error.value)
    assert "CUDA is unavailable" in str(error.value)


def test_tracker_runtime_requires_cuda_execution_provider():
    facts = _facts(onnx_providers=("CPUExecutionProvider",))

    with pytest.raises(PreflightError, match="CUDAExecutionProvider"):
        validate_tracker_runtime(facts)


def test_tracker_runtime_accepts_cuda_provider():
    report = validate_tracker_runtime(_facts())

    assert report.onnxruntime_version == "1.22.0"
    assert report.onnx_providers[0] == "CUDAExecutionProvider"
