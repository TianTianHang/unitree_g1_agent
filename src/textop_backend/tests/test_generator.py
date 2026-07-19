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


def test_new_request_replaces_active_generation_and_invalidates_old_token():
    machine = GeneratorStateMachine()
    machine.loaded()
    old = machine.begin("request-1", "wave")
    new = machine.replace("request-2", "walk")

    assert machine.request_id == "request-2"
    assert machine.prompt == "walk"
    assert machine.state is GeneratorState.GENERATING
    machine.ensure_active(new)
    with pytest.raises(StaleGeneration):
        machine.ensure_active(old)


def test_invalid_replacement_does_not_destroy_active_generation():
    machine = GeneratorStateMachine()
    machine.loaded()
    token = machine.begin("request-1", "wave")

    with pytest.raises(ValueError):
        machine.replace("request-2", " ")

    machine.ensure_active(token)


def test_draining_generation_can_be_replaced_before_execution_finishes():
    machine = GeneratorStateMachine()
    machine.loaded()
    old = machine.begin("request-1", "wave")
    machine.accept(old)

    new = machine.replace("request-2", "turn")

    assert machine.state is GeneratorState.GENERATING
    machine.ensure_active(new)


def test_drain_returns_to_ready_only_for_active_token():
    machine = GeneratorStateMachine()
    machine.loaded()
    token = machine.begin("request-1", "wave")
    machine.accept(token)
    machine.drained(token)

    assert machine.state is GeneratorState.READY
    assert machine.request_id is None
