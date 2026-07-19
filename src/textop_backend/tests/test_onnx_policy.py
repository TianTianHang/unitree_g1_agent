import numpy as np
import pytest

from textop_backend.onnx_policy import OnnxPolicy, PolicyError


class _Info:
    def __init__(self, name, shape):
        self.name = name
        self.shape = shape


class FakeSession:
    def __init__(self, output=None):
        self.output = np.zeros((1, 29), np.float32) if output is None else output
        self.feed = None

    def get_inputs(self):
        return [_Info("obs", [1, 431])]

    def get_outputs(self):
        return [_Info("actions", [1, 29])]

    def run(self, names, feed):
        self.feed = (names, feed)
        return [self.output]


class _OrtModule:
    def __init__(self, session_providers, available):
        self._session_providers = session_providers
        self._available = available

    def get_available_providers(self):
        return self._available

    def InferenceSession(self, path, providers):
        session = FakeSession()
        session.get_providers = lambda: self._session_providers
        return session


def test_policy_passes_batched_float32_observation():
    session = FakeSession(output=np.arange(29, dtype=np.float32).reshape(1, 29))
    policy = OnnxPolicy(session, input_name="obs", output_name="actions")
    result = policy.predict(np.zeros(431, dtype=np.float64))

    assert session.feed[0] == ["actions"]
    assert session.feed[1]["obs"].shape == (1, 431)
    assert session.feed[1]["obs"].dtype == np.float32
    np.testing.assert_array_equal(result, np.arange(29, dtype=np.float32))


def test_policy_rejects_wrong_session_abi():
    session = FakeSession()
    session.get_inputs = lambda: [_Info("obs", [1, 428])]
    with pytest.raises(PolicyError, match="input"):
        OnnxPolicy(session, input_name="obs", output_name="actions")


def test_policy_rejects_non_finite_output():
    output = np.zeros((1, 29), np.float32)
    output[0, 0] = np.nan
    policy = OnnxPolicy(FakeSession(output), input_name="obs", output_name="actions")
    with pytest.raises(PolicyError, match="finite"):
        policy.predict(np.zeros(431, np.float32))


def test_load_policy_rejects_unavailable_requested_provider(monkeypatch, tmp_path):
    import textop_backend.onnx_policy as module

    monkeypatch.setitem(__import__("sys").modules, "onnxruntime", _OrtModule(
        ["CPUExecutionProvider"], ["CPUExecutionProvider"]
    ))
    with pytest.raises(PolicyError, match="CUDAExecutionProvider"):
        module.load_onnx_policy(
            str(tmp_path / "policy.onnx"),
            input_name="obs", output_name="actions",
            providers=["CUDAExecutionProvider"],
        )


def test_load_policy_rejects_runtime_provider_fallback(monkeypatch, tmp_path):
    import textop_backend.onnx_policy as module

    monkeypatch.setitem(__import__("sys").modules, "onnxruntime", _OrtModule(
        ["CPUExecutionProvider"], ["CUDAExecutionProvider", "CPUExecutionProvider"]
    ))
    with pytest.raises(PolicyError, match="fell back"):
        module.load_onnx_policy(
            str(tmp_path / "policy.onnx"),
            input_name="obs", output_name="actions",
            providers=["CUDAExecutionProvider"],
        )
