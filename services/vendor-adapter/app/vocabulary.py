"""The profile's core diagnostics vocabulary.

A field is core only when an external standard names it (omlox / LwM2M) and a
consumer renders it. Everything else the schema maps is routed to `x_vendor`.
See docs/superpowers/specs/2026-09-03-vendor-neutral-vocabulary-design.md.
"""

# Speed over which the derived `moving` flag reads True. Normative, one value.
MOVING_SPEED_THRESHOLD_MPS: float = 0.15

CORE_DIAGNOSTICS: dict[str, dict] = {
    "battery": {"unit": "percent", "type": "number"},  # LwM2M 3/0/9, 0-100
    "last_seen": {"unit": None, "type": "number"},  # omlox timestamp_generated
    "accuracy": {"unit": "m", "type": "number"},  # omlox accuracy
    "moving": {"unit": None, "type": "boolean"},  # derived from omlox speed
}


def is_core(name: str) -> bool:
    return name in CORE_DIAGNOSTICS
