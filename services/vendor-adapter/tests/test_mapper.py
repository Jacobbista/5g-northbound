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
    assert out["latitude"] == 59.404251
    assert out["longitude"] == 17.949247
    # This real account's "accuracy" field is a [0,1] confidence score, not a
    # metres radius - mapped to `confidence`. The schema maps no accuracy at
    # all, so the key is absent rather than a fabricated number.
    assert "accuracy" not in out
    assert out["confidence"] == 0.85
    assert out["z"] == 1.2
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
        # accuracy = (1 - conf) * 50 expressed via linear y = -50x + 50
        accuracy=PathSpec(path="conf", transform=LinearTransform(type="linear", scale=-50.0, offset=50.0)),
        confidence=PathSpec(path="conf"),
        timestamp=ConstSpec(const=0.0),
    )
    out = to_measurement(mapping, {"conf": 0.8}, vendor_name="x")
    assert out["accuracy"] == 10.0
    assert out["confidence"] == 0.8


def test_to_measurement_venue_frame_maps_x_and_y():
    from app.schema import Mapping, ConstSpec, PathSpec

    mapping = Mapping(
        frame=ConstSpec(const="venue"),
        x=PathSpec(path="px"),
        y=PathSpec(path="py"),
        accuracy=ConstSpec(const=1.0),
        confidence=ConstSpec(const=0.5),
        timestamp=ConstSpec(const=0.0),
    )
    out = to_measurement(mapping, {"px": 3.0, "py": 4.0}, vendor_name="x")
    assert out["frame"] == "venue"
    assert out["x"] == 3.0
    assert out["y"] == 4.0
    assert "z" not in out
    assert "latitude" not in out
    assert "longitude" not in out


def test_to_measurement_iso8601_parses_to_epoch():
    from app.schema import Mapping, ConstSpec, PathSpec

    mapping = Mapping(
        frame=ConstSpec(const="wgs84"),
        latitude=ConstSpec(const=0.0),
        longitude=ConstSpec(const=0.0),
        accuracy=ConstSpec(const=1.0),
        confidence=ConstSpec(const=0.5),
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
    assert map_stream_diagnostics(block, payload) == {"vendorSpecific": {"motion": "STATIONARY"}}


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
    assert map_fetch_diagnostics(fetch, payload) == {
        "vendorSpecific": {"rssi": [-93, -87], "kind": "vendor-radius"}
    }


def test_to_measurement_carries_last_seen(wittra_schema, wittra_sample_payload):
    # lastSeen is the device's last communication, mapped on the fast path so
    # the engine can broadcast it. Distinct from the fix timestamp.
    out = to_measurement(wittra_schema.mapping, wittra_sample_payload, vendor_name="wittra")
    assert isinstance(out["lastSeen"], float)


def test_to_measurement_omits_last_seen_when_unmapped(wittra_schema_dict):
    # A vendor with no last-communication field omits the mapping; the
    # measurement then carries no lastSeen and liveness stays undetermined
    # rather than being faked from the fix time.
    from app.schema import Schema
    d = dict(wittra_schema_dict)
    d["mapping"] = {k: v for k, v in d["mapping"].items() if k != "lastSeen"}
    schema = Schema.model_validate(d)
    out = to_measurement(schema.mapping, {
        "latest": {"data": {"location": {
            "value": {"latitude": 1.0, "longitude": 2.0, "accuracy": 1.0, "height": 0.0},
            "timestamp": "2026-09-01T10:00:00Z",
        }}},
    }, vendor_name="wittra")
    assert "lastSeen" not in out


def test_to_measurement_carries_no_height_when_the_record_has_none(wittra_schema):
    payload = {"latest": {"data": {"location": {"timestamp": "2026-01-01T00:00:00Z",
               "value": {"latitude": 45.0, "longitude": 7.0}}}}}
    out = to_measurement(wittra_schema.mapping, payload, vendor_name="wittra")
    assert "z" not in out


def test_to_measurement_picks_the_pair_of_the_resolved_frame():
    from app.schema import Mapping

    m = Mapping.model_validate({
        "frame": {"path": "f"},
        "latitude": {"path": "lat"}, "longitude": {"path": "lon"},
        "x": {"path": "x"}, "y": {"path": "y"},
        "timestamp": {"path": "ts"},
    })
    venue = to_measurement(m, {"f": "venue", "x": 2.0, "y": 3.0, "ts": 1.0}, vendor_name="v")
    assert (venue["frame"], venue["x"], venue["y"]) == ("venue", 2.0, 3.0)
    geo = to_measurement(m, {"f": "wgs84", "lat": 59.4, "lon": 17.9, "ts": 1.0}, vendor_name="v")
    assert (geo["frame"], geo["latitude"], geo["longitude"]) == ("wgs84", 59.4, 17.9)
    assert to_measurement(m, {"f": "ecef", "x": 2.0, "y": 3.0, "ts": 1.0}, vendor_name="v") is None


def test_to_measurement_omits_confidence_the_vendor_does_not_report():
    from app.schema import Mapping, ConstSpec, PathSpec

    mapping = Mapping(
        frame=ConstSpec(const="wgs84"),
        latitude=PathSpec(path="lat"),
        longitude=PathSpec(path="lon"),
        accuracy=PathSpec(path="acc"),
        timestamp=ConstSpec(const=0.0),
    )
    out = to_measurement(mapping, {"lat": 59.4, "lon": 17.9, "acc": 3.0}, vendor_name="x")
    assert "confidence" not in out


def test_to_measurement_carries_vertical_accuracy_only_with_its_height():
    from app.schema import Mapping

    m = Mapping.model_validate({
        "frame": {"const": "wgs84"},
        "latitude": {"path": "lat"}, "longitude": {"path": "lon"},
        "z": {"path": "h"}, "verticalAccuracy": {"path": "hacc"},
        "timestamp": {"path": "ts"},
    })
    both = to_measurement(m, {"lat": 59.4, "lon": 17.9, "h": 1.2, "hacc": 0.3, "ts": 1.0}, vendor_name="v")
    assert (both["z"], both["verticalAccuracy"]) == (1.2, 0.3)
    no_height = to_measurement(m, {"lat": 59.4, "lon": 17.9, "hacc": 0.3, "ts": 1.0}, vendor_name="v")
    assert "z" not in no_height and "verticalAccuracy" not in no_height
