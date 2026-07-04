from __future__ import annotations

import json
from dataclasses import asdict
from typing import Protocol
from urllib import request as urlrequest

from voice_bridge.config import VoiceBridgeConfig
from voice_bridge.intent import contains_stop_word, parse_duration_sec
from voice_bridge.internal_types import AgentCommand, AgentRequest, AgentResult


class AgentClient(Protocol):
    def decide(self, request: AgentRequest) -> AgentResult:
        ...


class DisabledAgentClient:
    def decide(self, request: AgentRequest) -> AgentResult:
        return AgentResult(reply_text="语音控制未启用")


class RuleBasedAgentClient:
    def __init__(self, config: VoiceBridgeConfig):
        self.config = config

    def decide(self, request: AgentRequest) -> AgentResult:
        text = request.text
        if contains_stop_word(text, self.config):
            return AgentResult(commands=[AgentCommand(kind="action", params={"action": "stop"})], reply_text="收到")

        command = self._loco_command(text)
        if command is not None:
            return AgentResult(commands=[command], reply_text="收到")

        return AgentResult(reply_text="我还不能执行这个指令")

    def _loco_command(self, text: str) -> AgentCommand | None:
        defaults = self.config.motion_defaults
        vx = 0.0
        vy = 0.0
        vyaw = 0.0

        if "向前" in text or "前进" in text or "往前" in text:
            vx = float(defaults["default_vx"])
        elif "后退" in text or "往后" in text:
            vx = -float(defaults["default_vx"])
        elif "左移" in text or "向左平移" in text:
            vy = float(defaults["default_vy"])
        elif "右移" in text or "向右平移" in text:
            vy = -float(defaults["default_vy"])
        elif "左转" in text or "向左转" in text:
            vyaw = float(defaults["default_vyaw"])
        elif "右转" in text or "向右转" in text:
            vyaw = -float(defaults["default_vyaw"])
        else:
            return None

        duration_sec = parse_duration_sec(
            text,
            default_duration=float(defaults["default_motion_duration_sec"]),
            max_duration=float(defaults["max_motion_duration_sec"]),
        )
        return AgentCommand(
            kind="loco",
            params={
                "vx": vx,
                "vy": vy,
                "vyaw": vyaw,
                "duration_sec": duration_sec,
            },
        )


class HttpJsonAgentClient:
    def __init__(self, config: VoiceBridgeConfig):
        self.endpoint = str(config.agent["http_endpoint"])
        self.timeout_sec = float(config.agent["timeout_sec"])

    def decide(self, request: AgentRequest) -> AgentResult:
        body = json.dumps(asdict(request), ensure_ascii=False).encode("utf-8")
        http_request = urlrequest.Request(
            self.endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlrequest.urlopen(http_request, timeout=self.timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return agent_result_from_payload(payload)


def agent_result_from_payload(payload: dict) -> AgentResult:
    commands = []
    for raw_command in payload.get("commands", []):
        if not isinstance(raw_command, dict):
            continue
        kind = str(raw_command.get("kind", "none"))
        params = raw_command.get("params", {})
        commands.append(AgentCommand(kind=kind, params=dict(params) if isinstance(params, dict) else {}))
    led = payload.get("led")
    return AgentResult(
        commands=commands,
        reply_text=payload.get("reply_text"),
        led=dict(led) if isinstance(led, dict) else None,
        requires_confirmation=bool(payload.get("requires_confirmation", False)),
    )


def build_agent_client(config: VoiceBridgeConfig) -> AgentClient:
    backend = config.agent["backend"]
    if backend == "rule_based":
        return RuleBasedAgentClient(config)
    if backend == "http_json":
        return HttpJsonAgentClient(config)
    return DisabledAgentClient()
