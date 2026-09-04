"""The profile's core diagnostics vocabulary.

Single source of truth is the normative artifact
`spec/private-profile/diagnostics-vocabulary.json`, published by the gateway
(GET /contracts/diagnostics-vocabulary.json) and imported here so the adapter
routes against the same names, units and threshold it publishes. A field is
core only when this artifact names it (each entry cites the external standard
it adopts); everything else a schema maps is routed to the `x_vendor` bag.

The adapter is southbound: it conforms to the vocabulary, it does not define
it. Hence the artifact, not this module, is authoritative.
"""

import json
from pathlib import Path

_ARTIFACT_NAME = "diagnostics-vocabulary.json"

# First existing path wins: the copy baked into the image by `make
# stage-contracts`, then the repo tree (parents[3] is the repo root from
# services/vendor-adapter/app/vocabulary.py) for dev and tests.
_CANDIDATES = [
    Path("/app/contracts") / _ARTIFACT_NAME,
    Path(__file__).resolve().parents[3] / "spec/private-profile" / _ARTIFACT_NAME,
]


def _load() -> dict:
    for path in _CANDIDATES:
        if path.is_file():
            return json.loads(path.read_text())
    raise RuntimeError(
        f"diagnostics vocabulary artifact not found; tried {[str(p) for p in _CANDIDATES]}"
    )


_VOCAB = _load()
_CORE: dict[str, dict] = _VOCAB["core"]

# Name of the bag non-core fields are routed into. Declared by the artifact so
# the routing key stays authoritative in one place.
EXTENSION_BAG: str = _VOCAB["extension_bag"]

# Speed over which the derived `moving` flag reads True. Normative, one value.
MOVING_SPEED_THRESHOLD_MPS: float = float(_CORE["moving"]["derivation"]["threshold_mps"])

# Core field -> its declared unit, type and default delivery tier. The keys are
# the routing authority: a mapped field whose name is here is coerced to the
# core unit, everything else lands in `x_vendor`.
CORE_DIAGNOSTICS: dict[str, dict] = {
    name: {
        "unit": spec.get("unit"),
        "type": spec["type"],
        "tier_default": spec.get("tier_default"),
    }
    for name, spec in _CORE.items()
}


def is_core(name: str) -> bool:
    return name in CORE_DIAGNOSTICS
