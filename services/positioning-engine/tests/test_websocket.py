from app.routers.websocket import build_payload_item


class _Fused:
    def __init__(self, diagnostics):
        self.x = 1.0; self.z = 2.0; self.y = None
        self.accuracy_m = 0.9; self.sources = ["wittra"]
        self.timestamp = None; self.diagnostics = diagnostics


class _Res:
    def __init__(self, diagnostics):
        class P:
            name = "weighted_avg"
        self.primary = P()
        self.primary.fused = _Fused(diagnostics)


def test_payload_item_carries_diagnostics():
    item = build_payload_item("dev1", _Res({"motion": "STATIONARY"}), origin=None)
    assert item["diagnostics"] == {"motion": "STATIONARY"}


def test_payload_item_omits_diagnostics_when_absent():
    assert "diagnostics" not in build_payload_item("dev1", _Res({}), origin=None)
