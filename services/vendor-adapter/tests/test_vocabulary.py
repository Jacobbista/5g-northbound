from app.vocabulary import CORE_DIAGNOSTICS, MOVING_SPEED_THRESHOLD_MPS, is_core


def test_core_names_cover_v1():
    assert set(CORE_DIAGNOSTICS) == {"battery", "last_seen", "accuracy", "moving"}


def test_battery_is_percent():
    assert CORE_DIAGNOSTICS["battery"]["unit"] == "percent"


def test_is_core_rejects_unknown():
    assert is_core("battery") is True
    assert is_core("temperature") is False


def test_moving_threshold_fixed():
    assert MOVING_SPEED_THRESHOLD_MPS == 0.15
