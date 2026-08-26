from app.mapper import get_path, to_measurement


def test_get_path_dict():
    assert get_path({"a": {"b": 1}}, "a.b") == 1


def test_get_path_list_index():
    assert get_path({"a": [{"x": 7}]}, "a.0.x") == 7


def test_get_path_missing_returns_none():
    assert get_path({"a": {"b": 1}}, "a.c") is None


def test_get_path_index_out_of_range_returns_none():
    assert get_path({"a": []}, "a.0") is None


def test_get_path_traverse_scalar_returns_none():
    assert get_path({"a": 1}, "a.b") is None


def test_to_measurement_wgs84(wittra_schema, wittra_sample_payload):
    out = to_measurement(wittra_schema.mapping, wittra_sample_payload, vendor_name="wittra")
    assert out["source"] == "wittra"
    assert out["frame"] == "wgs84"
    assert out["latitude"] == 45.064547
    assert out["longitude"] == 7.659272
    # v4 schema: accuracy_m pulled from the vendor (radius in metres);
    # confidence is a fixed 0.5 because v4 does not expose a 0-1 score.
    assert out["accuracy_m"] == 0.85
    assert out["confidence"] == 0.5
    assert out["y"] == 1.2
    assert isinstance(out["timestamp"], float)


def test_to_measurement_none_when_position_missing(wittra_schema):
    # A vendor record with no resolvable position is 'no fix', not a (0,0)
    # phantom fix. The adapter must 404 so the gateway surfaces UNABLE_TO_LOCATE.
    assert to_measurement(wittra_schema.mapping, {}, vendor_name="wittra") is None


def test_to_measurement_none_when_position_partial(wittra_schema):
    # Latitude resolves but longitude is absent: still no fix (a half-position
    # is not a location).
    payload = {"latest": {"data": {"location": {"timestamp": "2026-01-01T00:00:00Z", "value": {"latitude": 45.0}}}}}
    assert to_measurement(wittra_schema.mapping, payload, vendor_name="wittra") is None


def test_to_measurement_keeps_genuine_zero(wittra_schema):
    # A coordinate the vendor genuinely reports as 0 is a real value, kept.
    payload = {"latest": {"data": {"location": {"timestamp": "2026-01-01T00:00:00Z", "value": {"latitude": 0.0, "longitude": 0.0}}}}}
    out = to_measurement(wittra_schema.mapping, payload, vendor_name="wittra")
    assert out is not None
    assert out["latitude"] == 0.0 and out["longitude"] == 0.0


def test_to_measurement_applies_linear_transform():
    from app.schema import Mapping, ConstSpec, PathSpec, LinearTransform

    mapping = Mapping(
        frame=ConstSpec(const="wgs84"),
        latitude=ConstSpec(const=0.0),
        longitude=ConstSpec(const=0.0),
        # accuracy_m = (1 - conf) * 50 expressed via linear y = -50x + 50
        accuracy_m=PathSpec(path="conf", transform=LinearTransform(type="linear", scale=-50.0, offset=50.0)),
        confidence=PathSpec(path="conf"),
        y=ConstSpec(const=0.0),
        timestamp=ConstSpec(const=0.0),
    )
    out = to_measurement(mapping, {"conf": 0.8}, vendor_name="x")
    assert out["accuracy_m"] == 10.0
    assert out["confidence"] == 0.8


def test_to_measurement_local_frame_maps_lat_to_x_and_lon_to_z():
    from app.schema import Mapping, ConstSpec, PathSpec

    mapping = Mapping(
        frame=ConstSpec(const="local"),
        latitude=PathSpec(path="px"),
        longitude=PathSpec(path="pz"),
        accuracy_m=ConstSpec(const=1.0),
        confidence=ConstSpec(const=0.5),
        y=ConstSpec(const=0.0),
        timestamp=ConstSpec(const=0.0),
    )
    out = to_measurement(mapping, {"px": 3.0, "pz": 4.0}, vendor_name="x")
    assert out["frame"] == "local"
    assert out["x"] == 3.0
    assert out["z"] == 4.0
    assert "latitude" not in out
    assert "longitude" not in out


def test_to_measurement_iso8601_parses_to_epoch():
    from app.schema import Mapping, ConstSpec, PathSpec

    mapping = Mapping(
        frame=ConstSpec(const="wgs84"),
        latitude=ConstSpec(const=0.0),
        longitude=ConstSpec(const=0.0),
        accuracy_m=ConstSpec(const=1.0),
        confidence=ConstSpec(const=0.5),
        y=ConstSpec(const=0.0),
        timestamp=PathSpec(path="ts", format="iso8601"),
    )
    out = to_measurement(mapping, {"ts": "1970-01-01T00:00:10+00:00"}, vendor_name="x")
    assert out["timestamp"] == 10.0


def test_map_stream_diagnostics_reads_current_record():
    from app.schema import DiagnosticsBlock
    from app.mapper import map_stream_diagnostics
    block = DiagnosticsBlock.model_validate(
        {"stream": {"motion": {"path": "latest.data.location.value.motion"}}}
    )
    payload = {"latest": {"data": {"location": {"value": {"motion": "STATIONARY"}}}}}
    assert map_stream_diagnostics(block, payload) == {"motion": "STATIONARY"}


def test_map_stream_diagnostics_skips_absent():
    from app.schema import DiagnosticsBlock
    from app.mapper import map_stream_diagnostics
    block = DiagnosticsBlock.model_validate({"stream": {"motion": {"path": "a.b"}}})
    assert map_stream_diagnostics(block, {}) == {}


def test_map_fetch_diagnostics_maps_mapping():
    from app.schema import DiagnosticsFetch
    from app.mapper import map_fetch_diagnostics
    fetch = DiagnosticsFetch.model_validate({
        "path": "/x",
        "mapping": {"rssi": {"path": "uwb.rssi"}, "kind": {"const": "vendor-radius"}},
    })
    payload = {"uwb": {"rssi": [-93, -87]}}
    assert map_fetch_diagnostics(fetch, payload) == {"rssi": [-93, -87], "kind": "vendor-radius"}
