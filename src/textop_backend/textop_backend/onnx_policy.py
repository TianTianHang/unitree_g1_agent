from __future__ import annotations

import ctypes
import os
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray


class PolicyError(RuntimeError):
    pass


def preload_cuda_libraries(library_dirs: list[str]) -> None:
    for value in library_dirs:
        expanded = os.path.expandvars(value)
        if "$" in expanded:
            raise PolicyError(f"CUDA library directory contains an unresolved environment variable: {value}")
        directory = Path(expanded).expanduser().resolve()
        main = directory / "libcudnn.so.8"
        if not main.is_file():
            raise PolicyError(f"cuDNN 8 library is missing: {main}")
        libraries = [main, *sorted(directory.glob("libcudnn_*.so.8"))]
        try:
            for library in libraries:
                ctypes.CDLL(str(library), mode=ctypes.RTLD_GLOBAL)
        except OSError as exc:
            raise PolicyError(f"failed to preload CUDA library: {library}") from exc


class OnnxPolicy:
    def __init__(self, session: Any, *, input_name: str, output_name: str) -> None:
        self.session = session
        self.input_name = input_name
        self.output_name = output_name
        inputs = {item.name: tuple(item.shape) for item in session.get_inputs()}
        outputs = {item.name: tuple(item.shape) for item in session.get_outputs()}
        if inputs.get(input_name) != (1, 431):
            raise PolicyError(f"policy input {input_name} must have shape [1,431]")
        if outputs.get(output_name) != (1, 29):
            raise PolicyError(f"policy output {output_name} must have shape [1,29]")

    def predict(self, observation: NDArray[np.float32]) -> NDArray[np.float32]:
        value = np.asarray(observation, dtype=np.float32)
        if value.shape != (431,) or not np.isfinite(value).all():
            raise PolicyError("observation must contain 431 finite values")
        output = self.session.run([self.output_name], {self.input_name: value.reshape(1, 431)})[0]
        action = np.asarray(output, dtype=np.float32)
        if action.shape != (1, 29):
            raise PolicyError("policy output must have shape [1,29]")
        action = action[0]
        if not np.isfinite(action).all():
            raise PolicyError("policy output must contain finite values")
        return action


def load_onnx_policy(
    path: str,
    *,
    input_name: str,
    output_name: str,
    providers: list[str] | None = None,
    cuda_library_dirs: list[str] | None = None,
    cuda_device_id: int = 0,
) -> OnnxPolicy:
    preload_cuda_libraries(list(cuda_library_dirs or []))
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise PolicyError("onnxruntime is not installed") from exc
    requested = list(providers or ["CPUExecutionProvider"])
    available = set(ort.get_available_providers())
    missing = [provider for provider in requested if provider not in available]
    if missing:
        raise PolicyError(
            "requested ONNX Runtime provider(s) are unavailable: "
            + ", ".join(missing)
            + f"; available={sorted(available)}"
        )
    session_providers: list[Any] = [
        (provider, {"device_id": cuda_device_id})
        if provider == "CUDAExecutionProvider"
        else provider
        for provider in requested
    ]
    session = ort.InferenceSession(path, providers=session_providers)
    active = set(session.get_providers())
    if requested and requested[0] not in active:
        raise PolicyError(
            f"ONNX Runtime fell back from {requested[0]} to {session.get_providers()}"
        )
    return OnnxPolicy(session, input_name=input_name, output_name=output_name)
