import pytest

from textop_backend.prompt_stream import (
    CommandState,
    PromptCommand,
    PromptStreamCoordinator,
)


def _command(request_id: str, prompt: str = "wave", duration: float = 1.0) -> PromptCommand:
    return PromptCommand(request_id=request_id, prompt=prompt, duration_sec=duration)


def test_first_command_becomes_active_at_boundary():
    stream = PromptStreamCoordinator()
    stream.submit(_command("r1"))

    transition = stream.activate_pending()

    assert transition is not None
    assert transition.previous is None
    assert transition.current.request_id == "r1"
    assert stream.outcome("r1").state is CommandState.ACTIVE


def test_active_command_is_superseded_only_when_replacement_activates():
    stream = PromptStreamCoordinator()
    stream.submit(_command("r1"))
    stream.activate_pending()
    stream.submit(_command("r2", "turn"))

    assert stream.outcome("r1").state is CommandState.ACTIVE
    transition = stream.activate_pending()

    assert transition.previous.request_id == "r1"
    assert transition.current.request_id == "r2"
    assert stream.outcome("r1").reason == "superseded_by:r2"
    assert stream.outcome("r2").state is CommandState.ACTIVE


def test_rapid_updates_keep_only_latest_pending_command():
    stream = PromptStreamCoordinator()
    stream.submit(_command("r1"))
    stream.activate_pending()
    stream.submit(_command("r2"))
    stream.submit(_command("r3"))

    assert stream.outcome("r2").state is CommandState.SUPERSEDED
    assert stream.outcome("r2").reason == "superseded_by:r3"
    assert stream.activate_pending().current.request_id == "r3"


def test_invalid_update_does_not_replace_pending_or_active_command():
    stream = PromptStreamCoordinator()
    stream.submit(_command("r1"))
    stream.activate_pending()

    with pytest.raises(ValueError):
        stream.submit(_command("r2", " "))

    assert stream.active.request_id == "r1"
    assert stream.pending is None


def test_stop_cancels_active_and_pending_commands():
    stream = PromptStreamCoordinator()
    stream.submit(_command("r1"))
    stream.activate_pending()
    stream.submit(_command("r2"))

    canceled = stream.cancel_all("safe_stop")

    assert [item.request_id for item in canceled] == ["r1", "r2"]
    assert stream.outcome("r1").state is CommandState.CANCELED
    assert stream.outcome("r2").state is CommandState.CANCELED
    assert stream.active is None and stream.pending is None


def test_finished_outcome_can_be_forgotten_without_leaking_request_ids():
    stream = PromptStreamCoordinator()
    stream.submit(_command("r1"))
    stream.activate_pending()
    stream.complete_active()

    stream.forget("r1")

    assert stream.outcome("r1") is None
    stream.submit(_command("r1", "new command"))


@pytest.mark.parametrize("duration", [0.0, -1.0, float("nan"), float("inf")])
def test_duration_must_be_positive_and_finite(duration):
    with pytest.raises(ValueError):
        PromptStreamCoordinator().submit(_command("r1", duration=duration))
