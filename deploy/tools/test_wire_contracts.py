"""Pin the two ends of every internal contract to each other.

Each of these contracts has a producer and a consumer that live in different
service trees of this repository. Their suites test each side against its own
expectation, so a rename on one side leaves both green and fails in the cluster.
These tests read both sides.

The v0.15.1 outage came from exactly that gap: the vendor adapter began emitting
`accuracy` while the engine still parsed `accuracy_m`, and 195 tests stayed
green.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _names(path: Path, pattern: str) -> set[str]:
    return set(re.findall(pattern, path.read_text()))


def test_measurement_keys_the_engine_parses_are_the_keys_adapters_emit():
    """`GET /measurement/{id}`: three producers, one consumer."""
    engine = ROOT / "services/positioning-engine/app/adapters/http.py"
    # A key read under a `.get()` guard is optional: wifi and synthetic have no
    # last-communication signal to report and legitimately omit it.
    optional = _names(engine, r'body\.get\("([a-zA-Z_]+)"')
    required = _names(engine, r'body\["([a-zA-Z_]+)"\]') - optional

    for adapter, emit_file, pattern in (
        ("vendor-adapter", "services/vendor-adapter/app/mapper.py", r'"([a-zA-Z_]+)":'),
        ("wifi-adapter", "services/wifi-adapter/app/models.py", r"^    ([a-zA-Z_]+):"),
        ("synthetic-adapter", "services/synthetic-adapter/app/models.py", r"^    ([a-zA-Z_]+):"),
    ):
        emitted = set(re.findall(pattern, (ROOT / emit_file).read_text(), re.M))
        missing = required - emitted
        assert not missing, f"{adapter} does not emit {sorted(missing)}"

    # An optional key still has to be spelled the same on both sides wherever a
    # producer does emit it.
    vendor: set[str] = set()
    for f in ("services/vendor-adapter/app/mapper.py",
              "services/vendor-adapter/app/routers/measurement.py"):
        vendor |= _names(ROOT / f, r'"([a-zA-Z_]+)":')
        vendor |= _names(ROOT / f, r'out\["([a-zA-Z_]+)"\]')
        vendor |= _names(ROOT / f, r'\["([a-zA-Z_]+)"\] =')
    for key in optional:
        assert key in vendor, f"the engine reads optional {key!r} that no producer emits"


def test_devices_fields_the_engine_copies_are_the_fields_adapters_emit():
    """`GET /devices`: the engine aggregates what each adapter reports."""
    engine = (ROOT / "services/positioning-engine/app/routers/devices.py").read_text()
    copied = set(re.findall(r'_COPY_FIELDS = \(([^)]*)\)', engine)[0].replace('"', "").split(", "))
    emitted: set[str] = set()
    for f in ("services/vendor-adapter/app/mapper.py",
              "services/vendor-adapter/app/routers/devices.py",
              "services/wifi-adapter/app/wifi.py",
              "services/synthetic-adapter/app/routers/devices.py"):
        emitted |= _names(ROOT / f, r'"([a-zA-Z_]+)":')
        emitted |= _names(ROOT / f, r'out\["([a-zA-Z_]+)"\]')
    # `position` is assembled by the engine, never emitted under that name.
    unknown = {c for c in copied - emitted if c != "position"}
    assert not unknown, f"the engine copies fields no adapter emits: {sorted(unknown)}"


def test_no_internal_contract_still_carries_a_unit_in_a_field_name():
    """One convention across everything this project names. The blueprint and
    the wifi bindings are operator documents and keep their own."""
    offenders: list[str] = []
    for f in ("services/positioning-engine/app/adapters/base.py",
              "services/positioning-engine/app/models.py",
              "services/wifi-adapter/app/models.py",
              "services/synthetic-adapter/app/models.py"):
        for name in _names(ROOT / f, r"^    ([a-z_]+): "):
            if re.search(r"_(m|s|ms|dbm|mps)$", name):
                offenders.append(f"{f}:{name}")
    # FloorPlan and Room live in the engine's models and describe the blueprint.
    offenders = [o for o in offenders if not re.search(r"(width|depth|height)_m$", o)]
    assert offenders == [], offenders
