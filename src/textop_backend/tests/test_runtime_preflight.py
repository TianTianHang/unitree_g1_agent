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
        "robotmdar_origin": "/opt/unitree/textop_runtime/robotmdar/__init__.py",
        "robotmdar_version": "0.1.0",
        "robotmdar_digest": "a" * 64,
    }
    values.update(overrides)
    return RuntimeFacts(**values)


def test_generator_runtime_accepts_gpu_3_and_installed_robotmdar():
    report = validate_generator_runtime(
        _facts(), device="cuda:3", expected_robotmdar_version="0.1.0", expected_robotmdar_digest="a" * 64
    )

    assert report.device_index == 3
    assert report.torch_version == "2.7.1"
    assert report.robotmdar_version == "0.1.0"


@pytest.mark.parametrize("device", ["cuda", "cuda:0", "cpu", "cuda:4", "cuda:not-a-number"])
def test_generator_runtime_rejects_device_other_than_available_gpu_3(device):
    with pytest.raises(PreflightError):
        validate_generator_runtime(
            _facts(), device=device, expected_robotmdar_version="0.1.0", expected_robotmdar_digest="a" * 64
        )


def test_generator_runtime_rejects_external_textop_checkout_import():
    facts = _facts(robotmdar_origin="/home/ubuntu/Desktop/TextOp/TextOpRobotMDAR/robotmdar/__init__.py")

    with pytest.raises(PreflightError, match="external TextOp checkout"):
        validate_generator_runtime(
            facts, device="cuda:3", expected_robotmdar_version="0.1.0", expected_robotmdar_digest="a" * 64
        )


def test_generator_runtime_rejects_wrong_python_or_missing_cuda():
    facts = _facts(python_version=(3, 11, 9), cuda_available=False)

    with pytest.raises(PreflightError) as error:
        validate_generator_runtime(
            facts, device="cuda:3", expected_robotmdar_version="0.1.0", expected_robotmdar_digest="a" * 64
        )

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


@pytest.mark.parametrize("field", ["robotmdar_version", "robotmdar_digest"])
def test_generator_runtime_rejects_artifact_lock_mismatch(field):
    facts = _facts(**{field: "b" * 64 if field.endswith("digest") else "0.2.0"})
    with pytest.raises(PreflightError, match="does not match lock"):
        validate_generator_runtime(
            facts, device="cuda:3", expected_robotmdar_version="0.1.0", expected_robotmdar_digest="a" * 64
        )
