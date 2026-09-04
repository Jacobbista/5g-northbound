import json
from pathlib import Path

from app.vocabulary import (
    CORE_DIAGNOSTICS,
    EXTENSION_BAG,
    MOVING_SPEED_THRESHOLD_MPS,
    is_core,
)

_REPO = Path(__file__).resolve().parents[3]


def test_core_names_cover_v1():
    assert set(CORE_DIAGNOSTICS) == {"battery", "last_seen", "accuracy", "moving"}


def test_vocabulary_loaded_from_artifact():
    """The core set derives from the normative artifact, not a hardcoded dict."""
    artifact = json.loads(
        (_REPO / "spec/private-profile/diagnostics-vocabulary.json").read_text()
    )
    assert set(CORE_DIAGNOSTICS) == set(artifact["core"])
    assert EXTENSION_BAG == artifact["extension_bag"]


def test_vocabulary_agrees_with_published_diagnostics_schema():
    """Guard the two surfaces of the one vocabulary against drift: every core
    name the adapter routes on must be a named property in the gateway-published
    device-diagnostics.schema.json."""
    diag = json.loads(
        (_REPO / "schema/device-diagnostics.schema.json").read_text()
    )
    props = diag["properties"]["diagnostics"]["properties"]
    assert set(CORE_DIAGNOSTICS) <= set(props)


def test_battery_is_percent():
    assert CORE_DIAGNOSTICS["battery"]["unit"] == "percent"


def test_is_core_rejects_unknown():
    assert is_core("battery") is True
    assert is_core("temperature") is False


def test_moving_threshold_fixed():
    assert MOVING_SPEED_THRESHOLD_MPS == 0.15
