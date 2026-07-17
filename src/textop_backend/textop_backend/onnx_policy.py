from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray


class PolicyError(RuntimeError):
    pass


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


def load_onnx_policy(path: str, *, input_name: str, output_name: str, providers: list[str] | None = None) -> OnnxPolicy:
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise PolicyError("onnxruntime is not installed") from exc
    session = ort.InferenceSession(path, providers=providers or ["CPUExecutionProvider"])
    return OnnxPolicy(session, input_name=input_name, output_name=output_name)
