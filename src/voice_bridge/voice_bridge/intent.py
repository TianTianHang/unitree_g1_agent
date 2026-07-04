from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from voice_bridge.config import VoiceBridgeConfig
from voice_bridge.internal_types import AsrEvent, SessionDecision


PUNCTUATION_PREFIX = "，,。.!！?？:：;； "


def new_session_id(now_sec: float) -> str:
    dt = datetime.fromtimestamp(now_sec, tz=timezone.utc)
    return dt.strftime("%Y%m%dT%H%M%S.%fZ")


def parse_asr_event(raw_text: str) -> AsrEvent:
    text = raw_text.strip()
    if not text:
        return AsrEvent(text="")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return AsrEvent(text=text)

    if not isinstance(payload, dict):
        return AsrEvent(text=text)

    event_text = str(payload.get("text", "")).strip()
    confidence = payload.get("confidence")
    if confidence is not None:
        try:
            confidence = float(confidence)
        except (TypeError, ValueError) as exc:
            raise ValueError("confidence must be numeric") from exc

    return AsrEvent(
        text=event_text,
        confidence=confidence,
        is_final=bool(payload.get("is_final", True)),
        source=str(payload.get("source", "unknown")),
        stamp=payload.get("stamp"),
    )


def _contains_any(text: str, words: list[str]) -> bool:
    lower = text.lower()
    return any(word.lower() in lower for word in words)


def contains_stop_word(text: str, config: VoiceBridgeConfig) -> bool:
    return _contains_any(text, list(config.voice["stop_words"]))


def strip_wake_word(text: str, config: VoiceBridgeConfig) -> tuple[bool, str]:
    for word in config.voice["wake_words"]:
        index = text.lower().find(word.lower())
        if index >= 0:
            before = text[:index]
            after = text[index + len(word) :]
            return True, (before + after).lstrip(PUNCTUATION_PREFIX).strip()
    return False, text


def asr_event_is_usable(event: AsrEvent, config: VoiceBridgeConfig) -> tuple[bool, str | None]:
    if not event.text:
        return False, "empty text"
    if not config.voice["process_partial"] and not event.is_final:
        return False, "partial result"
    if event.confidence is not None and event.confidence < config.voice["min_confidence"]:
        return False, "low confidence"
    return True, None


@dataclass
class VoiceSession:
    state: str = "IDLE"
    session_id: str | None = None
    started_sec: float | None = None
    last_activity_sec: float | None = None

    def handle_asr(self, event: AsrEvent, config: VoiceBridgeConfig, now_sec: float) -> SessionDecision:
        self._expire_if_needed(config, now_sec)

        if event.text and contains_stop_word(event.text, config):
            self._reset()
            return SessionDecision(
                kind="action",
                session_id=new_session_id(now_sec),
                text=event.text,
                action="stop",
            )

        usable, reason = asr_event_is_usable(event, config)
        if not usable:
            return SessionDecision(kind="ignore", session_id=self.session_id, reason=reason)

        woke, command_text = strip_wake_word(event.text, config)
        if self.state == "IDLE":
            if not woke:
                return SessionDecision(kind="ignore", reason="not awake")
            self._start(now_sec)
            if not command_text:
                return SessionDecision(kind="activated", session_id=self.session_id, text=event.text)
            self.state = "AGENT_PENDING"
            self.last_activity_sec = now_sec
            return SessionDecision(kind="agent", session_id=self.session_id, text=command_text)

        if woke and command_text:
            event_text = command_text
        else:
            event_text = event.text
        self.state = "AGENT_PENDING"
        self.last_activity_sec = now_sec
        return SessionDecision(kind="agent", session_id=self.session_id, text=event_text)

    def mark_agent_done(self, now_sec: float) -> None:
        if self.session_id is not None:
            self.state = "ACTIVE"
            self.last_activity_sec = now_sec

    def mark_agent_failed(self, now_sec: float) -> None:
        if self.session_id is not None:
            self.state = "ACTIVE"
            self.last_activity_sec = now_sec

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "session_id": self.session_id,
            "started_sec": self.started_sec,
            "last_activity_sec": self.last_activity_sec,
        }

    def _start(self, now_sec: float) -> None:
        self.state = "ACTIVE"
        self.session_id = new_session_id(now_sec)
        self.started_sec = now_sec
        self.last_activity_sec = now_sec

    def _reset(self) -> None:
        self.state = "IDLE"
        self.session_id = None
        self.started_sec = None
        self.last_activity_sec = None

    def _expire_if_needed(self, config: VoiceBridgeConfig, now_sec: float) -> None:
        if self.state == "IDLE":
            return
        if self.last_activity_sec is not None and now_sec - self.last_activity_sec > config.voice["idle_timeout_sec"]:
            self._reset()
            return
        if self.started_sec is not None and now_sec - self.started_sec > config.voice["max_session_sec"]:
            self._reset()


def parse_duration_sec(text: str, default_duration: float, max_duration: float) -> float:
    match = re.search(r"(\d+(?:\.\d+)?)\s*秒", text)
    if match:
        duration = float(match.group(1))
    elif "两秒" in text or "二秒" in text:
        duration = 2.0
    elif "一秒" in text:
        duration = 1.0
    else:
        duration = float(default_duration)
    return max(0.1, min(duration, float(max_duration)))
