import json

from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue

from voice_bridge_debug.state import PanelState, normalize_health, parse_json_topic


def test_parse_json_topic_success():
    assert parse_json_topic('{"mode":"sport_api_loco"}') == {"data": {"mode": "sport_api_loco"}}


def test_parse_json_topic_error_keeps_raw():
    parsed = parse_json_topic("not json")

    assert parsed["raw"] == "not json"
    assert "parse_error" in parsed


def test_panel_state_ring_buffer_keeps_latest_events():
    state = PanelState(max_events=2, notify_web=None)

    state.push_event("test", "first", {"index": 1}, timestamp=1.0)
    state.push_event("test", "second", {"index": 2}, timestamp=2.0)
    state.push_event("test", "third", {"index": 3}, timestamp=3.0)

    assert [event.kind for event in state.timeline] == ["second", "third"]


def test_push_event_notifies_web_with_timeline_event():
    messages = []
    state = PanelState(max_events=10, notify_web=messages.append)

    state.push_event("asr", "asr_received", {"text": "小宇"}, session_id="s1", timestamp=1.0)

    assert messages == [
        {
            "type": "timeline_event",
            "data": {
                "timestamp": 1.0,
                "source": "asr",
                "kind": "asr_received",
                "data": {"text": "小宇"},
                "session_id": "s1",
            },
        }
    ]


def test_normalize_health_maps_status_levels():
    key_value = KeyValue()
    key_value.key = "dds"
    key_value.value = "ok"
    status = DiagnosticStatus()
    status.name = "g1_interface"
    status.level = 1
    status.message = "degraded"
    status.values.append(key_value)
    msg = DiagnosticArray()
    msg.status.append(status)

    health = normalize_health(msg, now_sec=10.0, stale_after_sec=2.0)

    assert health.summary == "warn"
    assert health.max_level == 1
    assert health.status_count == 1
    assert health.raw["statuses"][0]["values"] == {"dds": "ok"}


def test_snapshot_is_json_serializable():
    state = PanelState(max_events=10, notify_web=None)
    state.robot_mode = {"data": {"mode": "sport_api_loco"}}
    state.push_event("asr", "asr_received", {"text": "小宇"}, timestamp=1.0)

    json.dumps(state.snapshot(), ensure_ascii=False)
