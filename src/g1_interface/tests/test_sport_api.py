import json

import pytest

from g1_interface.internal_types import SportCommand
from g1_interface.sport_api import SportApiClient


class FakeRequest:
    def __init__(self):
        self.header = type(
            "RequestHeader",
            (),
            {"identity": type("RequestIdentity", (), {"id": 0, "api_id": 0})()},
        )()
        self.parameter = ""
        self.binary = []


class FakeResponse:
    def __init__(self, request, code=0, payload=None):
        self.header = type(
            "ResponseHeader",
            (),
            {
                "identity": type(
                    "RequestIdentity",
                    (),
                    {
                        "id": request.header.identity.id,
                        "api_id": request.header.identity.api_id,
                    },
                )(),
                "status": type("ResponseStatus", (), {"code": code})(),
            },
        )()
        self.data = json.dumps(payload or {})
        self.binary = []


def test_build_velocity_request_sets_sequence_api_id_and_json_payload():
    client = SportApiClient(
        request_cls=FakeRequest,
        api_ids={"set_velocity": 7105},
        response_timeout_sec=0.5,
    )

    request = client.build_request(
        SportCommand(action="set_velocity", params={"velocity": [0.2, 0.0, 0.1], "duration": 1.5}),
        now_sec=10.0,
    )

    assert request.header.identity.id == 1
    assert request.header.identity.api_id == 7105
    assert json.loads(request.parameter) == {"duration": 1.5, "velocity": [0.2, 0.0, 0.1]}
    assert client.pending_count == 1


def test_build_request_rejects_unknown_action():
    client = SportApiClient(request_cls=FakeRequest, api_ids={"set_velocity": 7105}, response_timeout_sec=0.5)

    with pytest.raises(ValueError, match="unsupported sport action"):
        client.build_request(SportCommand(action="dance", params={}), now_sec=10.0)


def test_record_response_clears_pending_request():
    client = SportApiClient(request_cls=FakeRequest, api_ids={"set_velocity": 7105}, response_timeout_sec=0.5)
    request = client.build_request(
        SportCommand(action="set_velocity", params={"velocity": [0.0, 0.0, 0.0], "duration": 0.1}),
        now_sec=10.0,
    )
    response = FakeResponse(request)

    result = client.record_response(response, now_sec=10.1)

    assert result == {
        "matched": True,
        "sequence_id": 1,
        "api_id": 7105,
        "action": "set_velocity",
        "code": 0,
        "latency_ms": 100,
        "payload": {},
    }
    assert client.pending_count == 0


def test_record_response_decodes_payload():
    client = SportApiClient(request_cls=FakeRequest, api_ids={"get_fsm_mode": 7002}, response_timeout_sec=0.5)
    request = client.build_request(SportCommand(action="get_fsm_mode", params={}), now_sec=10.0)
    response = FakeResponse(request, payload={"action": "get_fsm_mode", "data": 2})

    result = client.record_response(response, now_sec=10.1)

    assert result["action"] == "get_fsm_mode"
    assert result["payload"] == {"action": "get_fsm_mode", "data": 2}


def test_expired_requests_are_returned_and_removed():
    client = SportApiClient(request_cls=FakeRequest, api_ids={"set_velocity": 7105}, response_timeout_sec=0.5)
    client.build_request(
        SportCommand(action="set_velocity", params={"velocity": [0.1, 0.0, 0.0], "duration": 1.0}),
        now_sec=10.0,
    )

    expired = client.expired_requests(now_sec=10.6)

    assert len(expired) == 1
    assert expired[0].action == "set_velocity"
    assert client.pending_count == 0
