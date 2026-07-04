from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class LowStateSummary:
    source: str
    rpy: list[float]
    quaternion: list[float]
    gyroscope: list[float]
    accelerometer: list[float]
    motor_count: int
    max_temperature_c: float | None
    motors: list[dict[str, float]]

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class ImuPayload:
    frame_id: str
    orientation_xyzw: list[float]
    angular_velocity: list[float]
    linear_acceleration: list[float]


@dataclass(frozen=True)
class SportCommand:
    action: str
    params: dict[str, Any]


@dataclass(frozen=True)
class PendingApiRequest:
    sequence_id: int
    api_id: int
    action: str
    created_monotonic_sec: float
