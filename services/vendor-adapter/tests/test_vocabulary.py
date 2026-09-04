import json
from pathlib import Path

from app.vocabulary import (
    CORE_DIAGNOSTICS,
    EXTENSION_BAG,
    MOVING_SPEED_THRESHOLD_MPS,
    _candidate_paths,
    is_core,
)

_REPO = Path(__file__).resolve().parents[3]


def test_candidate_paths_handle_shallow_container_layout():
    """The image copies app/ to /app/app/, so the module sits shallow at
    /app/app/vocabulary.py. Resolution must not assume repo depth (a fixed
    parents[N] index there raised IndexError and crash-looped the pod). It must
    not raise, and must offer the baked flat location as a candidate."""
    paths = _candidate_paths("/app/app/vocabulary.py", None, Path("/app/contracts"))
    assert Path("/app/contracts") / "diagnostics-vocabulary.json" in paths


def test_candidate_paths_include_repo_spec_dir():
    """From the repo tree, an ancestor's spec/private-profile/ is a candidate."""
    paths = _candidate_paths(__file__, None, Path("/app/contracts"))
    assert (_REPO / "spec/private-profile/diagnostics-vocabulary.json") in paths


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
