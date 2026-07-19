from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass


class PreflightError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeFacts:
    python_version: tuple[int, int, int]
    torch_version: str | None = None
    cuda_available: bool | None = None
    cuda_device_count: int | None = None
    onnxruntime_version: str | None = None
    onnx_providers: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreflightReport:
    python_version: tuple[int, int, int]
    device_index: int | None = None
    torch_version: str | None = None
    onnxruntime_version: str | None = None
    onnx_providers: tuple[str, ...] = ()


def _python_errors(facts: RuntimeFacts) -> list[str]:
    if facts.python_version[:2] != (3, 10):
        return [f"TextOp requires Python 3.10, got {'.'.join(map(str, facts.python_version))}"]
    return []


def _raise_errors(errors: list[str]) -> None:
    if errors:
        raise PreflightError("; ".join(errors))


def validate_generator_runtime(
    facts: RuntimeFacts,
    *,
    device: str,
) -> PreflightReport:
    errors = _python_errors(facts)
    device_index = None
    if device != "cuda:3":
        errors.append(f"TextOp generator device must be cuda:3, got {device!r}")
    else:
        device_index = 3
    if not facts.torch_version:
        errors.append("torch is not installed")
    if facts.cuda_available is not True:
        errors.append("CUDA is unavailable")
    if facts.cuda_device_count is None or facts.cuda_device_count <= 3:
        errors.append(f"cuda:3 is unavailable: device_count={facts.cuda_device_count}")
    _raise_errors(errors)
    return PreflightReport(
        python_version=facts.python_version,
        device_index=device_index,
        torch_version=facts.torch_version,
    )


def validate_tracker_runtime(facts: RuntimeFacts) -> PreflightReport:
    errors = _python_errors(facts)
    if not facts.onnxruntime_version:
        errors.append("onnxruntime is not installed")
    if "CUDAExecutionProvider" not in facts.onnx_providers:
        errors.append(f"onnxruntime CUDAExecutionProvider is unavailable: providers={facts.onnx_providers}")
    _raise_errors(errors)
    return PreflightReport(
        python_version=facts.python_version,
        onnxruntime_version=facts.onnxruntime_version,
        onnx_providers=facts.onnx_providers,
    )


def probe_generator_runtime() -> RuntimeFacts:
    try:
        torch = importlib.import_module("torch")
    except ImportError as exc:
        raise PreflightError("torch is not installed") from exc
    return RuntimeFacts(
        python_version=sys.version_info[:3],
        torch_version=str(torch.__version__),
        cuda_available=bool(torch.cuda.is_available()),
        cuda_device_count=int(torch.cuda.device_count()),
    )


def probe_tracker_runtime() -> RuntimeFacts:
    try:
        onnxruntime = importlib.import_module("onnxruntime")
    except ImportError as exc:
        raise PreflightError("onnxruntime is not installed") from exc
    return RuntimeFacts(
        python_version=sys.version_info[:3],
        onnxruntime_version=str(onnxruntime.__version__),
        onnx_providers=tuple(onnxruntime.get_available_providers()),
    )


def preflight_generator_runtime(*, device: str) -> PreflightReport:
    return validate_generator_runtime(probe_generator_runtime(), device=device)


def preflight_tracker_runtime() -> PreflightReport:
    return validate_tracker_runtime(probe_tracker_runtime())
