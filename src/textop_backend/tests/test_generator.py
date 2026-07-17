import pytest

from textop_backend.generator import GeneratorState, GeneratorStateMachine, StaleGeneration


def test_cancel_invalidates_inflight_generation():
    machine = GeneratorStateMachine()
    machine.loaded()
    token = machine.begin("request-1", "wave")
    machine.cancel("request-1")

    assert machine.state is GeneratorState.READY
    with pytest.raises(StaleGeneration):
        machine.accept(token)


def test_new_request_cannot_start_while_generating():
    machine = GeneratorStateMachine()
    machine.loaded()
    machine.begin("request-1", "wave")

    with pytest.raises(RuntimeError, match="GENERATING"):
        machine.begin("request-2", "walk")


def test_drain_returns_to_ready_only_for_active_token():
    machine = GeneratorStateMachine()
    machine.loaded()
    token = machine.begin("request-1", "wave")
    machine.accept(token)
    machine.drained(token)

    assert machine.state is GeneratorState.READY
    assert machine.request_id is None
