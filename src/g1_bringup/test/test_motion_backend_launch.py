import pytest

from g1_bringup.backend import backend_plan


def test_backend_plan_rejects_unknown_backend():
    with pytest.raises(ValueError, match="motion_backend"):
        backend_plan("automatic")


def test_official_loco_plan_is_exclusive():
    assert backend_plan("official_loco") == {
        "g1_interface_backend": "official_loco",
        "start_textop": False,
        "start_low_level_guard": False,
    }


def test_textop_plan_is_exclusive():
    assert backend_plan("textop") == {
        "g1_interface_backend": "textop",
        "start_textop": True,
        "start_low_level_guard": True,
    }
