import pytest

from g1_sim.config import G1SimConfig


def test_default_config_uses_unitree_native_topics():
    config = G1SimConfig.default()

    assert config.topics["low_state"] == "lowstate"
    assert config.topics["low_cmd_root"] == "/lowcmd"
    assert config.topics["user_lowcmd"] == "/user_lowcmd"
    assert config.topics["dex3_left_state"] == "/lf/dex3/left/state"
    assert config.topics["dex3_left_state_legacy"] == "/dex3/left/state"
    assert config.topics["audio_msg"] == "/audio_msg"
    assert config.topics["sport_request"] == "/api/sport/request"
    assert config.topics["voice_response"] == "/api/voice/response"
    assert config.topics["agv_request"] == "/api/agv/request"
    assert config.sim["sport_api_ids"]["get_balance_mode"] == 7003
    assert config.sim["sport_api_ids"]["set_velocity"] == 7105
    assert config.sim["voice_api_ids"]["tts"] == 1001
    assert config.sim["agv_api_ids"]["move"] == 1001


def test_default_topics_are_ros2_names_not_sdk2_dds_channels():
    config = G1SimConfig.default()

    assert all(not topic.startswith(("rt/", "/rt/")) for topic in config.topics.values())


@pytest.mark.parametrize("bad_topic", ["rt/lowstate", "/rt/lowstate"])
def test_config_rejects_sdk2_dds_channel_names_as_ros2_topics(bad_topic):
    raw = G1SimConfig.default()
    data = {"topics": dict(raw.topics), "sim": raw.sim}
    data["topics"]["low_state"] = bad_topic

    with pytest.raises(ValueError, match="must not include the DDS rt/ prefix"):
        G1SimConfig._from_dict(data)


def test_config_rejects_missing_api_id():
    raw = G1SimConfig.default()
    data = {"topics": raw.topics, "sim": dict(raw.sim)}
    data["sim"]["voice_api_ids"] = dict(data["sim"]["voice_api_ids"])
    data["sim"]["voice_api_ids"].pop("tts")

    with pytest.raises(ValueError, match="missing API id config in voice_api_ids: tts"):
        G1SimConfig._from_dict(data)
