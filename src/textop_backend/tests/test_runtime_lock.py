import pytest

from textop_backend.runtime_lock import RuntimeLockError, load_robotmdar_lock


def test_load_robotmdar_lock(tmp_path):
    path = tmp_path / "lock.yaml"
    path.write_text("robotmdar:\n  version: 0.1.0\n  sha256: " + "A" * 64 + "\n", encoding="utf-8")
    assert load_robotmdar_lock(path) == ("0.1.0", "a" * 64)


def test_load_robotmdar_lock_rejects_invalid_digest(tmp_path):
    path = tmp_path / "lock.yaml"
    path.write_text("robotmdar:\n  version: 0.1.0\n  sha256: bad\n", encoding="utf-8")
    with pytest.raises(RuntimeLockError, match="SHA-256"):
        load_robotmdar_lock(path)
