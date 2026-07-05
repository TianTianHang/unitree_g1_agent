import pytest

from g1_sim.config import G1SimConfig
from g1_sim.model import (
    SimulatedRobotState,
    decode_request_parameter,
    dumps,
    handle_motion_switcher_api,
    handle_agv_api,
    handle_sport_api,
    handle_voice_api,
    request_identity,
)


class FakeIdentity:
    def __init__(self, sequence_id=7, api_id=7105):
        self.id = sequence_id
        self.api_id = api_id


class FakeHeader:
    def __init__(self):
        self.identity = FakeIdentity()


class FakeRequest:
    def __init__(self, parameter):
        self.header = FakeHeader()
        self.parameter = parameter


def test_decode_request_parameter_and_identity():
    request = FakeRequest(dumps({"velocity": [0.1, 0.0, 0.0], "duration": 1.0}))

    assert request_identity(request) == (7, 7105)
    assert decode_request_parameter(request) == {"velocity": [0.1, 0.0, 0.0], "duration": 1.0}


def test_sport_velocity_api_integrates_motion():
    config = G1SimConfig.default()
    state = SimulatedRobotState()
    state.integrate(10.0)

    code, payload = handle_sport_api(
        state,
        api_id=config.sim["sport_api_ids"]["set_velocity"],
        params={"velocity": [0.2, 0.0, 0.0], "duration": 1.0},
        api_ids=config.sim["sport_api_ids"],
        now_sec=10.0,
    )

    assert code == 0
    assert payload["action"] == "set_velocity"
    assert state.snapshot(10.5)["pose"]["x"] == pytest.approx(0.1)
    assert state.snapshot(11.5)["velocity"]["vx"] == 0.0


def test_sport_get_fsm_mode_uses_official_data_field():
    config = G1SimConfig.default()
    state = SimulatedRobotState(fsm_mode=2)

    code, payload = handle_sport_api(
        state,
        api_id=config.sim["sport_api_ids"]["get_fsm_mode"],
        params={},
        api_ids=config.sim["sport_api_ids"],
        now_sec=1.0,
    )

    assert code == 0
    assert payload == {"action": "get_fsm_mode", "data": 2}


def test_sport_set_balance_mode_and_get_balance_mode():
    config = G1SimConfig.default()
    state = SimulatedRobotState()

    set_code, set_payload = handle_sport_api(
        state,
        api_id=config.sim["sport_api_ids"]["set_balance_mode"],
        params={"data": 1},
        api_ids=config.sim["sport_api_ids"],
        now_sec=1.0,
    )
    get_code, get_payload = handle_sport_api(
        state,
        api_id=config.sim["sport_api_ids"]["get_balance_mode"],
        params={},
        api_ids=config.sim["sport_api_ids"],
        now_sec=1.1,
    )

    assert set_code == 0
    assert set_payload == {"action": "set_balance_mode", "data": 1}
    assert get_code == 0
    assert get_payload == {"action": "get_balance_mode", "data": 1}


def test_voice_tts_and_asr_api_payloads():
    config = G1SimConfig.default()
    state = SimulatedRobotState()

    tts_code, tts_payload = handle_voice_api(
        state,
        api_id=config.sim["voice_api_ids"]["tts"],
        params={"text": "收到", "speaker_id": 0},
        api_ids=config.sim["voice_api_ids"],
        default_asr_text=config.sim["default_asr_text"],
    )
    asr_code, asr_payload = handle_voice_api(
        state,
        api_id=config.sim["voice_api_ids"]["asr"],
        params={},
        api_ids=config.sim["voice_api_ids"],
        default_asr_text=config.sim["default_asr_text"],
    )

    assert tts_code == 0
    assert tts_payload["action"] == "tts"
    assert tts_payload["text"] == "收到"
    assert asr_code == 0
    assert asr_payload["action"] == "asr"
    assert asr_payload["text"] == config.sim["default_asr_text"]


def test_motion_switcher_select_and_check_mode():
    config = G1SimConfig.default()
    state = SimulatedRobotState()

    select_code, select_payload = handle_motion_switcher_api(
        state,
        api_id=config.sim["motion_switcher_api_ids"]["select_mode"],
        params={"mode": "ai"},
        api_ids=config.sim["motion_switcher_api_ids"],
    )
    check_code, check_payload = handle_motion_switcher_api(
        state,
        api_id=config.sim["motion_switcher_api_ids"]["check_mode"],
        params={},
        api_ids=config.sim["motion_switcher_api_ids"],
    )

    assert select_code == 0
    assert select_payload["name"] == "ai"
    assert check_code == 0
    assert check_payload["name"] == "ai"
    assert check_payload["form"] == "g1_sim"


def test_agv_move_api_uses_velocity_fields():
    config = G1SimConfig.default()
    state = SimulatedRobotState()
    state.integrate(2.0)

    code, payload = handle_agv_api(
        state,
        api_id=config.sim["agv_api_ids"]["move"],
        params={"vx": 0.1, "vy": 0.0, "vyaw": 0.2, "duration": 1.0},
        api_ids=config.sim["agv_api_ids"],
        now_sec=2.0,
    )

    assert code == 0
    assert payload["action"] == "move"
    assert state.snapshot(2.5)["pose"]["x"] == pytest.approx(0.05)
