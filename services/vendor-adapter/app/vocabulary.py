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
import os
from pathlib import Path

_ARTIFACT_NAME = "diagnostics-vocabulary.json"


def _candidate_paths(module_file: str, override: str | None, baked_dir: Path) -> list[Path]:
    """Where the artifact might live, first existing wins:

    - ``override``: an explicit CONTRACTS_DIR, holding the file flat.
    - ``baked_dir``: the copy `make stage-contracts` bakes into the image.
    - any ancestor of this module carrying `spec/private-profile/<artifact>`,
      for dev and tests running from the repo tree.

    The image copies `app/` to `/app/app/`, so the module sits shallow at
    `/app/app/vocabulary.py`; the repo nests it deeper. Walking ``.parents``
    (never indexing a fixed depth) resolves both layouts without assuming one.
    """
    out: list[Path] = []
    if override:
        out.append(Path(override) / _ARTIFACT_NAME)
    out.append(baked_dir / _ARTIFACT_NAME)
    for parent in Path(module_file).resolve().parents:
        out.append(parent / "spec/private-profile" / _ARTIFACT_NAME)
    return out


def _load() -> dict:
    candidates = _candidate_paths(
        __file__, os.environ.get("CONTRACTS_DIR"), Path("/app/contracts")
    )
    for path in candidates:
        if path.is_file():
            return json.loads(path.read_text())
    raise RuntimeError(
        f"diagnostics vocabulary artifact not found; tried {[str(p) for p in candidates]}"
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
