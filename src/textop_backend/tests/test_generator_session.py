import pytest

from textop_backend.generator_session import GeneratorSession


def test_duration_is_rounded_up_to_complete_eight_frame_primitives():
    session = GeneratorSession(future_len=8, dt=0.02)

    assert session.primitive_count(0.01) == 1
    assert session.primitive_count(0.16) == 1
    assert session.primitive_count(0.17) == 2


def test_session_tracks_generation_and_real_tracker_progress():
    session = GeneratorSession(future_len=8, dt=0.02)
    session.begin("r1", duration_seconds=0.32)

    assert session.mark_generated("r1") is False
    assert session.generated_frames == 8
    assert session.mark_generated("r1") is True
    session.update_executed("r1", 7)
    assert not session.execution_complete
    session.update_executed("r1", 16)
    assert session.execution_complete


def test_stale_tracker_status_and_cancelled_session_are_rejected():
    session = GeneratorSession(future_len=8, dt=0.02)
    session.begin("r1", duration_seconds=0.16)

    session.update_executed("other", 100)
    assert session.executed_frames == 0
    session.cancel("r1")
    with pytest.raises(RuntimeError, match="not active"):
        session.mark_generated("r1")


def test_replacement_restarts_duration_accounting_for_new_request():
    session = GeneratorSession(future_len=8, dt=0.02)
    session.begin("r1", duration_seconds=0.32)
    session.mark_generated("r1")
    session.update_executed("r1", 5)

    session.replace("r2", duration_seconds=0.17)

    assert session.active_request_id == "r2"
    assert session.required_primitives == 2
    assert session.generated_frames == 0
    assert session.executed_frames == 0


@pytest.mark.parametrize("duration", [0.0, -1.0, float("nan"), float("inf")])
def test_duration_must_be_finite_and_positive(duration):
    session = GeneratorSession(future_len=8, dt=0.02)
    with pytest.raises(ValueError):
        session.begin("r1", duration_seconds=duration)
