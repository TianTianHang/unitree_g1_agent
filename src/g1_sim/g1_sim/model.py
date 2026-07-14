from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from typing import Any


def dumps(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def parse_mapping(raw: object) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if isinstance(raw, list | tuple) and all(isinstance(item, int) for item in raw):
        raw = bytes(raw).decode("utf-8")
    text = str(raw or "").strip()
    if not text:
        return {}
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    return payload


def finite_float(payload: dict[str, Any], field: str, default: float | None = None) -> float:
    if field not in payload:
        if default is None:
            raise ValueError(f"missing field: {field}")
        value = default
    else:
        value = payload[field]
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def request_identity(msg: object) -> tuple[int, int]:
    identity = getattr(getattr(msg, "header", None), "identity", None)
    return int(getattr(identity, "id", 0)), int(getattr(identity, "api_id", 0))


def decode_request_parameter(msg: object) -> dict[str, Any]:
    for attr in ["parameter", "data", "binary"]:
        if hasattr(msg, attr):
            value = getattr(msg, attr)
            if value not in (None, "", [], b""):
                return parse_mapping(value)
    return {}


def _api_name(api_ids: dict[str, int], api_id: int) -> str | None:
    for name, configured_id in api_ids.items():
        if int(configured_id) == int(api_id):
            return name
    return None


@dataclass
class SimulatedRobotState:
    motor_count: int = 35
    hand_motor_count: int = 7
    x: float = 0.0
    y: float = 0.0
    yaw: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    vyaw: float = 0.0
    command_until_sec: float = 0.0
    last_update_sec: float | None = None
    fsm_id: int = 0
    fsm_mode: int = 2
    balance_mode: int = 0
    swing_height: float = 0.08
    stand_height: float = 0.0
    phase: list[float] | None = None
    speed_mode: int = 0
    arm_task_id: int = 0
    control_owner: str = "internal"
    volume: int = 50
    silent: bool = False
    selected_motion_mode: str = "normal"
    agv_height: float = 0.0
    last_sport_request: dict[str, Any] | None = None
    last_arm_request: dict[str, Any] | None = None
    last_voice_request: dict[str, Any] | None = None
    last_agv_request: dict[str, Any] | None = None
    last_motion_switcher_request: dict[str, Any] | None = None
    last_lowcmd_sec: float | None = None
    last_arm_sdk_sec: float | None = None
    last_dex3_cmd: dict[str, Any] | None = None
    active_playback: dict[str, dict[str, Any]] = field(default_factory=dict)
    playback_history: list[dict[str, Any]] = field(default_factory=list)
    asr_index: int = 0

    def integrate(self, now_sec: float) -> None:
        if self.last_update_sec is None:
            self.last_update_sec = now_sec
            return

        active_until = min(now_sec, self.command_until_sec)
        dt = max(0.0, active_until - self.last_update_sec)
        if dt > 0.0:
            cos_yaw = math.cos(self.yaw)
            sin_yaw = math.sin(self.yaw)
            self.x += (cos_yaw * self.vx - sin_yaw * self.vy) * dt
            self.y += (sin_yaw * self.vx + cos_yaw * self.vy) * dt
            self.yaw = _wrap_angle(self.yaw + self.vyaw * dt)

        if now_sec >= self.command_until_sec:
            self.vx = 0.0
            self.vy = 0.0
            self.vyaw = 0.0
        self.last_update_sec = now_sec

    def apply_velocity_command(self, params: dict[str, Any], now_sec: float) -> dict[str, Any]:
        self.integrate(now_sec)
        velocity = params.get("velocity", [0.0, 0.0, 0.0])
        if not isinstance(velocity, list) or len(velocity) != 3:
            raise ValueError("velocity must be [vx, vy, vyaw]")
        duration = finite_float(params, "duration", default=0.1)
        self.vx = float(velocity[0])
        self.vy = float(velocity[1])
        self.vyaw = float(velocity[2])
        self.command_until_sec = now_sec + max(0.0, duration)
        self.last_sport_request = {
            "action": "set_velocity",
            "velocity": [self.vx, self.vy, self.vyaw],
            "duration": duration,
        }
        return dict(self.last_sport_request)

    def record_lowcmd(self, now_sec: float) -> None:
        self.last_lowcmd_sec = now_sec

    def record_arm_sdk(self, now_sec: float) -> None:
        self.last_arm_sdk_sec = now_sec

    def record_dex3_cmd(self, side: str, now_sec: float) -> None:
        self.last_dex3_cmd = {"side": side, "stamp_sec": now_sec}

    def snapshot(self, now_sec: float) -> dict[str, Any]:
        self.integrate(now_sec)
        return {
            "pose": {"x": self.x, "y": self.y, "yaw": self.yaw},
            "velocity": {"vx": self.vx, "vy": self.vy, "vyaw": self.vyaw},
            "command_active": now_sec < self.command_until_sec,
            "fsm_id": self.fsm_id,
            "fsm_mode": self.fsm_mode,
            "balance_mode": self.balance_mode,
            "swing_height": self.swing_height,
            "stand_height": self.stand_height,
            "phase": list(self.phase or []),
            "speed_mode": self.speed_mode,
            "arm_task_id": self.arm_task_id,
            "control_owner": self.control_owner,
            "volume": self.volume,
            "silent": self.silent,
            "selected_motion_mode": self.selected_motion_mode,
            "agv_height": self.agv_height,
            "active_playback": {
                app_name: dict(playback)
                for app_name, playback in self.active_playback.items()
            },
            "playback_history": [dict(playback) for playback in self.playback_history],
        }


def handle_sport_api(
    state: SimulatedRobotState,
    api_id: int,
    params: dict[str, Any],
    api_ids: dict[str, int],
    now_sec: float,
) -> tuple[int, dict[str, Any]]:
    action = _api_name(api_ids, api_id)
    if action == "get_fsm_id":
        return 0, {"action": action, "data": state.fsm_id}
    if action == "get_fsm_mode":
        return 0, {"action": action, "data": state.fsm_mode}
    if action == "get_balance_mode":
        return 0, {"action": action, "data": state.balance_mode}
    if action == "get_swing_height":
        return 0, {"action": action, "data": state.swing_height}
    if action == "get_stand_height":
        return 0, {"action": action, "data": state.stand_height}
    if action == "get_phase":
        return 0, {"action": action, "data": list(state.phase or [0.0, 0.0])}
    if action == "set_fsm_id":
        state.fsm_id = int(params.get("data", state.fsm_id))
        state.last_sport_request = {"action": action, "data": state.fsm_id}
        return 0, dict(state.last_sport_request)
    if action == "set_balance_mode":
        state.balance_mode = int(params.get("data", state.balance_mode))
        state.last_sport_request = {"action": action, "data": state.balance_mode}
        return 0, dict(state.last_sport_request)
    if action == "set_swing_height":
        state.swing_height = finite_float(params, "data", default=state.swing_height)
        state.last_sport_request = {"action": action, "data": state.swing_height}
        return 0, dict(state.last_sport_request)
    if action == "set_stand_height":
        state.stand_height = finite_float(params, "data", default=state.stand_height)
        state.last_sport_request = {"action": action, "data": state.stand_height}
        return 0, dict(state.last_sport_request)
    if action == "set_velocity":
        return 0, state.apply_velocity_command(params, now_sec)
    if action == "set_arm_task":
        state.arm_task_id = int(params.get("data", state.arm_task_id))
        state.last_sport_request = {"action": action, "data": state.arm_task_id}
        return 0, dict(state.last_sport_request)
    if action == "set_speed_mode":
        state.speed_mode = int(params.get("data", state.speed_mode))
        state.last_sport_request = {"action": action, "data": state.speed_mode}
        return 0, dict(state.last_sport_request)
    if action == "switch_to_user_ctrl":
        state.control_owner = "user"
        state.last_sport_request = {"action": action}
        return 0, {"action": action, "control_owner": state.control_owner}
    if action == "switch_to_internal_ctrl":
        state.control_owner = "internal"
        if "data" in params:
            state.fsm_mode = int(params["data"])
        state.last_sport_request = {"action": action}
        return 0, {"action": action, "control_owner": state.control_owner, "data": state.fsm_mode}
    return 1, {"accepted": False, "error": f"unsupported sport api_id: {api_id}"}


def handle_arm_api(
    state: SimulatedRobotState,
    api_id: int,
    params: dict[str, Any],
    api_ids: dict[str, int],
) -> tuple[int, dict[str, Any]]:
    action = _api_name(api_ids, api_id)
    if action is None:
        return 1, {"accepted": False, "error": f"unsupported arm api_id: {api_id}"}
    if action == "get_action_list":
        payload = {"action": action, "actions": ["wave_hand", "shake_hand", "reset_arm"]}
    else:
        payload = {"action": action, "accepted": True, "params": params}
    state.last_arm_request = payload
    return 0, payload


def handle_voice_api(
    state: SimulatedRobotState,
    api_id: int,
    params: dict[str, Any],
    api_ids: dict[str, int],
    default_asr_text: str,
) -> tuple[int, dict[str, Any]]:
    action = _api_name(api_ids, api_id)
    if action is None:
        return 1, {"accepted": False, "error": f"unsupported voice api_id: {api_id}"}

    if action == "tts":
        payload = {
            "action": action,
            "accepted": True,
            "index": int(params.get("index", 0)),
            "speaker_id": int(params.get("speaker_id", 0)),
            "text": str(params.get("text", "")),
        }
    elif action == "asr":
        payload = {
            "action": action,
            "text": str(params.get("text", default_asr_text) or default_asr_text),
            "confidence": float(params.get("confidence", 0.9)),
            "is_final": bool(params.get("is_final", True)),
        }
    elif action == "start_play":
        app_name = str(params.get("app_name", ""))
        stream_id = str(params.get("stream_id", ""))
        start_time = float(time.time())
        state.active_playback[app_name] = {
            "stream_id": stream_id,
            "start_time": start_time,
        }
        payload = {
            "action": action,
            "accepted": True,
            "app_name": app_name,
            "stream_id": stream_id,
            "status": "playing",
        }
        state.playback_history.append({**payload, "start_time": start_time})
    elif action == "stop_play":
        app_name = str(params.get("app_name", ""))
        playback = state.active_playback.pop(app_name, None)
        stopped_streams = [] if playback is None else [str(playback.get("stream_id", ""))]
        payload = {
            "action": action,
            "accepted": True,
            "app_name": app_name,
            "stopped_streams": stopped_streams,
        }
        state.playback_history.append({**payload, "stop_time": float(time.time())})
    elif action == "get_volume":
        payload = {"action": action, "volume": state.volume}
    elif action == "set_volume":
        state.volume = max(0, min(100, int(params.get("volume", state.volume))))
        payload = {"action": action, "volume": state.volume}
    elif action == "set_rgb_led":
        payload = {
            "action": action,
            "r": max(0, min(255, int(params.get("r", params.get("R", 0))))),
            "g": max(0, min(255, int(params.get("g", params.get("G", 0))))),
            "b": max(0, min(255, int(params.get("b", params.get("B", 0))))),
        }
    else:
        payload = {"action": action, "accepted": True, "params": params}

    state.last_voice_request = payload
    return 0, payload


def handle_agv_api(
    state: SimulatedRobotState,
    api_id: int,
    params: dict[str, Any],
    api_ids: dict[str, int],
    now_sec: float,
) -> tuple[int, dict[str, Any]]:
    action = _api_name(api_ids, api_id)
    if action is None:
        return 1, {"accepted": False, "error": f"unsupported agv api_id: {api_id}"}

    if action == "move":
        velocity = [
            finite_float(params, "vx", default=0.0),
            finite_float(params, "vy", default=0.0),
            finite_float(params, "vyaw", default=0.0),
        ]
        duration = finite_float(params, "duration", default=0.1)
        payload = state.apply_velocity_command({"velocity": velocity, "duration": duration}, now_sec)
        payload["action"] = action
    elif action == "height_adjust":
        state.agv_height = finite_float(params, "data", default=params.get("height", state.agv_height))
        payload = {"action": action, "data": state.agv_height}
    else:
        payload = {"action": action, "accepted": True, "params": params}

    state.last_agv_request = payload
    return 0, payload


def handle_motion_switcher_api(
    state: SimulatedRobotState,
    api_id: int,
    params: dict[str, Any],
    api_ids: dict[str, int],
) -> tuple[int, dict[str, Any]]:
    action = _api_name(api_ids, api_id)
    if action is None:
        return 1, {"accepted": False, "error": f"unsupported motion_switcher api_id: {api_id}"}

    if action == "check_mode":
        payload = {"action": action, "name": state.selected_motion_mode, "form": "g1_sim"}
    elif action == "select_mode":
        state.selected_motion_mode = str(params.get("name", params.get("mode", state.selected_motion_mode)))
        payload = {"action": action, "name": state.selected_motion_mode, "form": "g1_sim"}
    elif action == "release_mode":
        state.selected_motion_mode = "normal"
        payload = {"action": action, "name": state.selected_motion_mode, "form": "g1_sim"}
    elif action == "set_silent":
        state.silent = bool(params.get("silent", True))
        payload = {"action": action, "silent": state.silent}
    elif action == "get_silent":
        payload = {"action": action, "silent": state.silent}
    else:
        payload = {"action": action, "accepted": True, "params": params}

    state.last_motion_switcher_request = payload
    return 0, payload


def _wrap_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))
