from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from g1_interface.internal_types import PendingApiRequest, SportCommand


class SportApiClient:
    def __init__(
        self,
        request_cls: Callable[[], Any],
        api_ids: dict[str, int],
        response_timeout_sec: float,
        request_id_factory: Callable[[], int] | None = None,
    ) -> None:
        self._request_cls = request_cls
        self._api_ids = dict(api_ids)
        self._response_timeout_sec = response_timeout_sec
        self._request_id_factory = request_id_factory or time.monotonic_ns
        self._last_sequence_id = 0
        self._pending: dict[int, PendingApiRequest] = {}

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def build_request(self, command: SportCommand, now_sec: float) -> Any:
        api_id = self._api_ids.get(command.action)
        if api_id is None:
            raise ValueError(f"unsupported sport action: {command.action}")

        sequence_id = int(self._request_id_factory())
        if sequence_id <= self._last_sequence_id:
            sequence_id = self._last_sequence_id + 1
        self._last_sequence_id = sequence_id

        request = self._request_cls()
        request.header.identity.id = sequence_id
        request.header.identity.api_id = int(api_id)
        request.parameter = json.dumps(command.params, sort_keys=True)

        self._pending[sequence_id] = PendingApiRequest(
            sequence_id=sequence_id,
            api_id=int(api_id),
            action=command.action,
            created_monotonic_sec=now_sec,
        )
        return request

    def record_response(self, msg: object, now_sec: float) -> dict[str, object]:
        identity = getattr(getattr(msg, "header", None), "identity", None)
        status = getattr(getattr(msg, "header", None), "status", None)
        sequence_id = int(getattr(identity, "id", 0))
        api_id = int(getattr(identity, "api_id", 0))
        pending = self._pending.get(sequence_id)
        if pending is None:
            return {
                "matched": False,
                "sequence_id": sequence_id,
                "api_id": api_id,
                "code": int(getattr(status, "code", -1)),
                "payload": decode_response_payload(msg),
            }
        if api_id != pending.api_id:
            return {
                "matched": False,
                "sequence_id": sequence_id,
                "api_id": api_id,
                "expected_api_id": pending.api_id,
                "code": int(getattr(status, "code", -1)),
                "payload": decode_response_payload(msg),
            }

        self._pending.pop(sequence_id, None)

        latency_ms = int(round((now_sec - pending.created_monotonic_sec) * 1000))
        return {
            "matched": True,
            "sequence_id": pending.sequence_id,
            "api_id": pending.api_id,
            "action": pending.action,
            "code": int(getattr(status, "code", -1)),
            "latency_ms": latency_ms,
            "payload": decode_response_payload(msg),
        }

    def expired_requests(self, now_sec: float) -> list[PendingApiRequest]:
        expired = [
            pending
            for pending in self._pending.values()
            if now_sec - pending.created_monotonic_sec > self._response_timeout_sec
        ]
        for pending in expired:
            self._pending.pop(pending.sequence_id, None)
        return expired


def decode_response_payload(msg: object) -> dict[str, object]:
    for attr in ["parameter", "data", "binary"]:
        if not hasattr(msg, attr):
            continue
        value = getattr(msg, attr)
        if value in (None, "", [], b""):
            continue
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        if isinstance(value, (list, tuple)) and all(isinstance(item, int) for item in value):
            value = bytes(value).decode("utf-8")
        payload = json.loads(str(value))
        if not isinstance(payload, dict):
            raise ValueError("response payload must be a JSON object")
        return payload
    return {}
