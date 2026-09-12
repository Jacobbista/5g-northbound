"""The profile's accuracy-class bands, as the engine reads them.

Single source of truth is `spec/private-profile/accuracy-class-vocabulary.json`,
published by the gateway (GET /contracts/accuracy-class-vocabulary.json) and
staged into this image by `make stage-contracts`. The engine consumes it, it
does not define it: an adapter declares which band its technology delivers, and
this module only turns that declaration into a number when a source reports no
per-fix accuracy of its own.
"""

import json
import os
from pathlib import Path
from typing import Optional

_ARTIFACT_NAME = "accuracy-class-vocabulary.json"


def _candidate_paths(module_file: str, override: Optional[str], baked_dir: Path) -> list[Path]:
    """Where the artifact might live, first existing wins. Mirrors the
    vendor-adapter's vocabulary loader: an explicit CONTRACTS_DIR, the copy
    baked into the image, then any ancestor carrying the repo layout (dev and
    tests). Walks `.parents` rather than indexing a fixed depth, because the
    image flattens the tree the repo nests."""
    out: list[Path] = []
    if override:
        out.append(Path(override) / _ARTIFACT_NAME)
    out.append(baked_dir / _ARTIFACT_NAME)
    for parent in Path(module_file).resolve().parents:
        out.append(parent / "spec/private-profile" / _ARTIFACT_NAME)
    return out


def _load() -> dict:
    for path in _candidate_paths(
        __file__, os.environ.get("CONTRACTS_DIR"), Path("/app/contracts")
    ):
        if path.is_file():
            return json.loads(path.read_text())
    raise RuntimeError(
        f"accuracy-class vocabulary not found; tried {[str(p) for p in _candidate_paths(__file__, os.environ.get('CONTRACTS_DIR'), Path('/app/contracts'))]}"
    )


_CLASSES: dict[str, dict] = _load()["classes"]


def nominal_for_class(name: Optional[str]) -> Optional[float]:
    """The radius a bounded band resolves to, in metres, or None.

    The band's `upperBound`: with nothing but the class to go on, the honest
    radius is the worst of the band, not a flattering midpoint. `coarse` is
    open-ended upward and carries no upper bound, so it resolves to None and an
    adapter declaring it has to supply its own `nominalAccuracy`.
    """
    spec = _CLASSES.get(name or "")
    if spec is None:
        return None
    bound = spec.get("upperBound")
    return float(bound) if bound is not None else None


def is_known(name: Optional[str]) -> bool:
    return (name or "") in _CLASSES


def bounds_for_class(name: Optional[str]) -> Optional[tuple[float, Optional[float]]]:
    """(lowerBound, upperBound) in metres for a declared class, or None when the
    class is unknown. The upper bound is None for an open-ended band."""
    spec = _CLASSES.get(name or "")
    if spec is None:
        return None
    upper = spec.get("upperBound")
    return float(spec.get("lowerBound", 0.0)), (float(upper) if upper is not None else None)
