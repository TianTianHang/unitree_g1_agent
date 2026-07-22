from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from g1_interface.internal_types import ImuPayload, LowStateSummary


def _float_list(value: object, length: int, default: list[float]) -> list[float]:
    if value is None:
        return list(default)
    if not isinstance(value, Iterable):
        return list(default)
    result = [float(item) for item in list(value)[:length]]
    while len(result) < length:
        result.append(default[len(result)])
    return result


def _float_value(value: Any, default: float = 0.0) -> float:
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        values = list(value)
        if not values:
            return default
        value = values[0]
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def lowstate_to_summary(msg: object, source: str, max_motors: int = 35) -> LowStateSummary:
    imu_state = getattr(msg, "imu_state", msg)
    motors = []
    for motor in list(getattr(msg, "motor_state", []))[:max_motors]:
        motors.append(
            {
                "q": _float_value(getattr(motor, "q", 0.0)),
                "dq": _float_value(getattr(motor, "dq", 0.0)),
                "tau_est": _float_value(getattr(motor, "tau_est", 0.0)),
                "temperature": _float_value(getattr(motor, "temperature", 0.0)),
            }
        )

    temperatures = [motor["temperature"] for motor in motors]
    max_temperature = max(temperatures) if temperatures else None

    return LowStateSummary(
        source=source,
        rpy=_float_list(getattr(imu_state, "rpy", None), 3, [0.0, 0.0, 0.0]),
        quaternion=_float_list(getattr(imu_state, "quaternion", None), 4, [1.0, 0.0, 0.0, 0.0]),
        gyroscope=_float_list(getattr(imu_state, "gyroscope", None), 3, [0.0, 0.0, 0.0]),
        accelerometer=_float_list(getattr(imu_state, "accelerometer", None), 3, [0.0, 0.0, 0.0]),
        motor_count=len(motors),
        max_temperature_c=max_temperature,
        motors=motors,
    )


def imu_to_payload(msg: object, frame_id: str) -> ImuPayload:
    quaternion_wxyz = _float_list(getattr(msg, "quaternion", None), 4, [1.0, 0.0, 0.0, 0.0])
    return ImuPayload(
        frame_id=frame_id,
        orientation_xyzw=[
            quaternion_wxyz[1],
            quaternion_wxyz[2],
            quaternion_wxyz[3],
            quaternion_wxyz[0],
        ],
        angular_velocity=_float_list(getattr(msg, "gyroscope", None), 3, [0.0, 0.0, 0.0]),
        linear_acceleration=_float_list(getattr(msg, "accelerometer", None), 3, [0.0, 0.0, 0.0]),
    )
