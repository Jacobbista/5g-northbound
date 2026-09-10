from app.routers.websocket import build_payload_item


class _Fused:
    def __init__(self, diagnostics, lastSeen=None):
        self.x = 1.0; self.z = 2.0; self.y = None
        self.accuracy = 0.9; self.sources = ["wittra"]
        self.timestamp = None; self.diagnostics = diagnostics
        self.lastSeen = lastSeen


class _Res:
    def __init__(self, diagnostics, lastSeen=None):
        class P:
            name = "weighted_avg"
        self.primary = P()
        self.primary.fused = _Fused(diagnostics, lastSeen)


def test_payload_item_carries_diagnostics():
    item = build_payload_item("dev1", _Res({"motion": "STATIONARY"}), origin=None)
    assert item["diagnostics"] == {"motion": "STATIONARY"}


def test_payload_item_omits_diagnostics_when_absent():
    assert "diagnostics" not in build_payload_item("dev1", _Res({}), origin=None)


def test_payload_item_carries_last_seen_as_iso():
    # Liveness is derived from lastSeen, so it must reach the broadcast. It is
    # serialised ISO like the other stream times.
    item = build_payload_item("dev1", _Res({}, lastSeen=1757000000.0), origin=None)
    assert item["lastCommunicationTime"].startswith("20")
    assert "T" in item["lastCommunicationTime"]


def test_payload_item_omits_last_seen_when_source_has_none():
    # A source with no last-communication signal emits no field; a consumer
    # must not mistake `observed_at` (fresh every tick) for liveness.
    assert "lastSeen" not in build_payload_item("dev1", _Res({}), origin=None)
