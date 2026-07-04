from __future__ import annotations

import json
from typing import Callable

from g1_interface.internal_types import PendingApiRequest, SportCommand


class SportApiClient:
    def __init__(
        self,
        request_cls: Callable[[], object],
        api_ids: dict[str, int],
        response_timeout_sec: float,
    ) -> None:
        self._request_cls = request_cls
        self._api_ids = dict(api_ids)
        self._response_timeout_sec = response_timeout_sec
        self._next_sequence_id = 1
        self._pending: dict[int, PendingApiRequest] = {}

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def build_request(self, command: SportCommand, now_sec: float) -> object:
        api_id = self._api_ids.get(command.action)
        if api_id is None:
            raise ValueError(f"unsupported sport action: {command.action}")

        request = self._request_cls()
        request.header.identity.id = self._next_sequence_id
        request.header.identity.api_id = int(api_id)
        request.parameter = json.dumps(command.params, sort_keys=True)

        self._pending[self._next_sequence_id] = PendingApiRequest(
            sequence_id=self._next_sequence_id,
            api_id=int(api_id),
            action=command.action,
            created_monotonic_sec=now_sec,
        )
        self._next_sequence_id += 1
        return request

    def record_response(self, msg: object, now_sec: float) -> dict[str, object]:
        identity = getattr(getattr(msg, "header", None), "identity", None)
        status = getattr(getattr(msg, "header", None), "status", None)
        sequence_id = int(getattr(identity, "id", 0))
        pending = self._pending.pop(sequence_id, None)
        if pending is None:
            return {
                "matched": False,
                "sequence_id": sequence_id,
                "api_id": int(getattr(identity, "api_id", 0)),
                "code": int(getattr(status, "code", -1)),
            }

        latency_ms = int(round((now_sec - pending.created_monotonic_sec) * 1000))
        return {
            "matched": True,
            "sequence_id": pending.sequence_id,
            "api_id": pending.api_id,
            "action": pending.action,
            "code": int(getattr(status, "code", -1)),
            "latency_ms": latency_ms,
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
