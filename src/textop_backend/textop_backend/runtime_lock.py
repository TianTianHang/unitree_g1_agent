from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class RuntimeLockError(ValueError):
    pass


def load_robotmdar_lock(path: str | Path) -> tuple[str, str]:
    raw: Any = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    robotmdar = raw.get("robotmdar") if isinstance(raw, dict) else None
    if not isinstance(robotmdar, dict):
        raise RuntimeLockError("lock.robotmdar must be a mapping")
    version, digest = robotmdar.get("version"), robotmdar.get("sha256")
    if not isinstance(version, str) or not version:
        raise RuntimeLockError("lock.robotmdar.version must not be empty")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdefABCDEF" for c in digest):
        raise RuntimeLockError("lock.robotmdar.sha256 must be a SHA-256 hex digest")
    return version, digest.lower()
