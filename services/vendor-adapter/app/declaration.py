"""The source's declared behaviour, checked against the schema and the payloads.

The adapter declares how its source reports and whether it measures height
(`reporting`, `reportingInterval`, `z`), and the engine interprets every
measurement from that declaration. Two checks keep it honest.

At load, the schema must be able to carry what the declaration promises: an
on-motion source needs the last communication, a declared interval is needed
to judge currency, and a height is mapped exactly when one is declared.

At runtime, the payloads are compared with the declaration: mapped fields that
never resolve, reports further apart than the declared interval, and, for an
on-motion source, positions that move without a new fix time. The counts are
served on GET /contract.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from .schema import Mapping, Schema


def check(schema: Schema, caps: dict) -> list[str]:
    """Contradictions between the schema and the declared capabilities."""
    errors: list[str] = []
    mapping = schema.mapping
    reporting = caps.get("reporting")
    if reporting == "on_motion" and mapping.lastSeen is None:
        errors.append("reporting on_motion requires a lastSeen mapping: it confirms the last fix")
    if reporting in ("periodic", "on_motion") and not caps.get("reportingInterval"):
        errors.append(f"reporting {reporting} requires reportingInterval")
    if caps.get("z") is True and mapping.z is None:
        errors.append("z: true requires a z mapping")
    if caps.get("z") is False and mapping.z is not None:
        errors.append("a z mapping requires z: true")
    if caps.get("nominalVerticalAccuracy") is not None and caps.get("z") is not True:
        errors.append("nominalVerticalAccuracy requires z: true")
    return errors


# Mapping fields whose resolution shows up as the same key in the measurement.
_OPTIONAL_KEYS = ("accuracy", "confidence", "z", "verticalAccuracy", "timestamp", "lastSeen")


@dataclass
class Observed:
    """Payload statistics since the schema was applied."""

    measurements: int = 0
    unresolved: dict[str, int] = field(default_factory=dict)
    intervalExceeded: int = 0
    movedWithoutFix: int = 0
    # Records that were not a fix, by reason: frame, position, timestamp,
    # confidence. Each answered 404 to the engine.
    noFix: dict[str, int] = field(default_factory=dict)
    _last: dict[str, tuple[Optional[float], Optional[float], tuple]] = field(default_factory=dict)

    def record(self, device_id: str, mapping: Mapping, measurement: dict[str, Any], caps: dict) -> None:
        self.measurements += 1
        for key in _OPTIONAL_KEYS:
            if getattr(mapping, key) is not None and measurement.get(key) is None:
                self.unresolved[key] = self.unresolved.get(key, 0) + 1

        fix = measurement.get("timestamp")
        seen = measurement.get("lastSeen")
        position = tuple(measurement.get(k) for k in ("latitude", "longitude", "x", "y"))
        report = max(t for t in (fix, seen) if t is not None) if (fix or seen) else None
        previous = self._last.get(device_id)
        self._last[device_id] = (report, fix, position)
        if previous is None:
            return
        prev_report, prev_fix, prev_position = previous
        interval = caps.get("reportingInterval")
        if (
            interval
            and report is not None
            and prev_report is not None
            and report > prev_report
            and report - prev_report > float(interval)
        ):
            self.intervalExceeded += 1
        if (
            caps.get("reporting") == "on_motion"
            and fix is not None
            and fix == prev_fix
            and position != prev_position
        ):
            self.movedWithoutFix += 1

    def record_no_fix(self, reason: Optional[str]) -> None:
        key = reason or "position"
        self.noFix[key] = self.noFix.get(key, 0) + 1

    def as_dict(self) -> dict:
        return {
            "measurements": self.measurements,
            "unresolved": dict(sorted(self.unresolved.items())),
            "intervalExceeded": self.intervalExceeded,
            "movedWithoutFix": self.movedWithoutFix,
            "noFix": dict(sorted(self.noFix.items())),
        }
