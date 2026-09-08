from app.routers.websocket import build_payload_item


class _Fused:
    def __init__(self, diagnostics, last_seen=None):
        self.x = 1.0; self.z = 2.0; self.y = None
        self.accuracy_m = 0.9; self.sources = ["wittra"]
        self.timestamp = None; self.diagnostics = diagnostics
        self.last_seen = last_seen


class _Res:
    def __init__(self, diagnostics, last_seen=None):
        class P:
            name = "weighted_avg"
        self.primary = P()
        self.primary.fused = _Fused(diagnostics, last_seen)


def test_payload_item_carries_diagnostics():
    item = build_payload_item("dev1", _Res({"motion": "STATIONARY"}), origin=None)
    assert item["diagnostics"] == {"motion": "STATIONARY"}


def test_payload_item_omits_diagnostics_when_absent():
    assert "diagnostics" not in build_payload_item("dev1", _Res({}), origin=None)


def test_payload_item_carries_last_seen_as_iso():
    # Liveness is derived from last_seen, so it must reach the broadcast. It is
    # serialised ISO like the other stream times.
    item = build_payload_item("dev1", _Res({}, last_seen=1757000000.0), origin=None)
    assert item["last_seen"].startswith("20")
    assert "T" in item["last_seen"]


def test_payload_item_omits_last_seen_when_source_has_none():
    # A source with no last-communication signal emits no field; a consumer
    # must not mistake `observed_at` (fresh every tick) for liveness.
    assert "last_seen" not in build_payload_item("dev1", _Res({}), origin=None)
