from types import SimpleNamespace

import pytest

from textop_backend.stop_gate import StopGate, validated_stop_action


def _message(*, action="stop", decision="allow", kind="action", command_id="cmd-1"):
    return SimpleNamespace(
        intent=SimpleNamespace(command_id=command_id, action=action),
        validation=SimpleNamespace(
            command_id=command_id,
            command_kind=kind,
            decision=decision,
        ),
    )


def test_validated_stop_action_accepts_stop_and_cancel():
    assert validated_stop_action(_message(action="stop")) == "stop"
    assert validated_stop_action(_message(action="cancel")) == "cancel"


@pytest.mark.parametrize(
    "message",
    [
        _message(action="stand"),
        _message(decision="reject"),
        _message(kind="loco"),
        _message(command_id=""),
    ],
)
def test_validated_stop_action_rejects_unsafe_message(message):
    with pytest.raises(ValueError):
        validated_stop_action(message)


def test_stop_gate_invalidates_only_active_generation():
    gate = StopGate()
    first = gate.begin("request-1")

    assert gate.request_stop("request-1", reason="safe_stop") is True
    assert gate.is_stopped(first) is True

    second = gate.begin("request-2")
    assert gate.is_stopped(second) is False
    assert gate.request_stop("request-1", reason="late_stop") is False
    assert gate.is_stopped(second) is False


def test_stop_gate_is_idempotent_and_preserves_first_reason():
    gate = StopGate()
    token = gate.begin("request-1")

    assert gate.request_stop("request-1", reason="safe_stop") is True
    assert gate.request_stop("request-1", reason="action_cancel") is False
    assert gate.stop_reason(token) == "safe_stop"


def test_stop_without_active_request_is_noop():
    gate = StopGate()

    assert gate.request_active_stop(reason="safe_stop") is None
