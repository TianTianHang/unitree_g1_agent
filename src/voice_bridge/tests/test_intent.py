from voice_bridge.config import VoiceBridgeConfig
from voice_bridge.intent import VoiceSession, parse_asr_event


def test_parse_json_asr_event():
    event = parse_asr_event('{"text":"宇树，向前走一秒","confidence":0.9,"is_final":true,"source":"mock"}')

    assert event.text == "宇树，向前走一秒"
    assert event.confidence == 0.9
    assert event.is_final is True
    assert event.source == "mock"


def test_parse_plain_text_asr_event():
    event = parse_asr_event("停止")

    assert event.text == "停止"
    assert event.confidence is None
    assert event.is_final is True


def test_partial_result_is_ignored_by_default():
    config = VoiceBridgeConfig.default()
    session = VoiceSession()
    event = parse_asr_event('{"text":"宇树，向前","is_final":false}')

    decision = session.handle_asr(event, config, now_sec=1.0)

    assert decision.kind == "ignore"
    assert decision.reason == "partial result"


def test_low_confidence_is_ignored():
    config = VoiceBridgeConfig.default()
    session = VoiceSession()
    event = parse_asr_event('{"text":"宇树，向前","confidence":0.1}')

    decision = session.handle_asr(event, config, now_sec=1.0)

    assert decision.kind == "ignore"
    assert decision.reason == "low confidence"


def test_low_confidence_stop_word_still_bypasses_filters():
    config = VoiceBridgeConfig.default()
    session = VoiceSession()
    event = parse_asr_event('{"text":"停止","confidence":0.1}')

    decision = session.handle_asr(event, config, now_sec=1.0)

    assert decision.kind == "action"
    assert decision.action == "stop"


def test_partial_stop_word_still_bypasses_filters():
    config = VoiceBridgeConfig.default()
    session = VoiceSession()
    event = parse_asr_event('{"text":"停止","is_final":false}')

    decision = session.handle_asr(event, config, now_sec=1.0)

    assert decision.kind == "action"
    assert decision.action == "stop"


def test_idle_ignores_non_wake_text():
    config = VoiceBridgeConfig.default()
    session = VoiceSession()

    decision = session.handle_asr(parse_asr_event("向前走"), config, now_sec=1.0)

    assert decision.kind == "ignore"
    assert decision.reason == "not awake"


def test_stop_word_does_not_require_wake_word():
    config = VoiceBridgeConfig.default()
    session = VoiceSession()

    decision = session.handle_asr(parse_asr_event("停止"), config, now_sec=1.0)

    assert decision.kind == "action"
    assert decision.action == "stop"
    assert decision.text == "停止"


def test_wake_word_and_command_in_same_text_goes_to_agent():
    config = VoiceBridgeConfig.default()
    session = VoiceSession()

    decision = session.handle_asr(parse_asr_event("宇树，向前走一秒"), config, now_sec=1.0)

    assert decision.kind == "agent"
    assert decision.text == "向前走一秒"
    assert session.state == "AGENT_PENDING"


def test_session_expires_after_idle_timeout():
    config = VoiceBridgeConfig.default()
    session = VoiceSession()

    session.handle_asr(parse_asr_event("宇树"), config, now_sec=1.0)
    decision = session.handle_asr(parse_asr_event("向前走"), config, now_sec=100.0)

    assert decision.kind == "ignore"
    assert decision.reason == "not awake"
