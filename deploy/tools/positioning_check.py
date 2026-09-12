#!/usr/bin/env python3
"""Positioning fabric check.

Validates that the declarative pieces of the positioning fabric agree, the
same self-validating spirit as the env contracts:

  1. each adapter's compose ADAPTER_CAPABILITIES agrees with its
     adapter.contract.yaml `capabilities` on every key both declare (closes
     the "value in compose, source in contract" loop). A generic image
     declares only what is true of the binary, so compose supplying vendor
     traits it omits is wiring, not drift;
  2. each declared `accuracy_class` is in the vocabulary, an open-ended band
     carries its own `nominalAccuracy`, and an adapter whose emitted range is
     statically readable stays inside the band it claims;
  3. every source named by an asset's capabilities in dev/assets.json is
     advertised by some adapter;
  4. every asset's `kind` is advertised by some adapter;
  5. dev/assets.json conforms to schema/asset.schema.json (best-effort: only
     when jsonschema is importable).

Static: reads files, runs no containers. Exit 0 = consistent, 1 = drift.

Usage: deploy/tools/positioning_check.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
COMPOSE = REPO / "deploy" / "compose" / "docker-compose.yml"
ASSETS = REPO / "dev" / "assets.json"
ASSET_SCHEMA = REPO / "schema" / "asset.schema.json"
ACCURACY_CLASSES = REPO / "spec" / "private-profile" / "accuracy-class-vocabulary.json"

OK, BAD = "\033[32m✓\033[0m", "\033[31m✗\033[0m"


def _compose_services() -> dict:
    return (yaml.safe_load(COMPOSE.read_text()) or {}).get("services", {}) or {}


def _env_map(service: dict) -> dict:
    """Compose environment may be a dict or a list of KEY=VALUE strings."""
    env = service.get("environment") or {}
    if isinstance(env, list):
        out = {}
        for item in env:
            k, _, v = str(item).partition("=")
            out[k] = v
        return out
    return env


def _emitted_accuracy_range(svc_name: str) -> tuple[float, float] | None:
    """The accuracy band an adapter can emit, when that is statically readable
    from its own settings. Only the synthetic walker qualifies: it synthesises
    values inside a configured band. A real adapter computes accuracy per fix
    from the measurement, so there is nothing static to read and nothing to
    check here."""
    cfg = REPO / "services" / svc_name / "app" / "config.py"
    if not cfg.is_file():
        return None
    text = cfg.read_text()
    lo = re.search(r"^    accuracy_min_m: float = ([\d.]+)", text, re.M)
    hi = re.search(r"^    accuracy_max_m: float = ([\d.]+)", text, re.M)
    if lo is None or hi is None:
        return None
    return float(lo.group(1)), float(hi.group(1))


def main() -> int:
    errors: list[str] = []
    services = _compose_services()

    # adapter dir -> compose service name (basename matches the service key).
    contracts = sorted(REPO.glob("services/*/adapter.contract.yaml")) + \
        sorted(REPO.glob("mocks/*/adapter.contract.yaml"))
    if not contracts:
        print(f"{BAD} no adapter.contract.yaml found")
        return 1

    advertised_sources: set[str] = set()
    advertised_kinds: set[str] = set()
    declared: dict[str, dict] = {}

    print("· adapter capabilities (compose vs contract)")
    for path in contracts:
        svc_name = path.parent.name
        contract = yaml.safe_load(path.read_text()) or {}
        caps = contract.get("capabilities") or {}

        svc = services.get(svc_name)
        if svc is None:
            errors.append(f"{svc_name}: contract present but no compose service")
            print(f"  {BAD} {svc_name}: no compose service")
            continue
        raw = _env_map(svc).get("ADAPTER_CAPABILITIES")
        if not raw:
            errors.append(f"{svc_name}: compose has no ADAPTER_CAPABILITIES")
            print(f"  {BAD} {svc_name}: ADAPTER_CAPABILITIES unset in compose")
            continue
        try:
            compose_caps = json.loads(raw)
        except ValueError as exc:
            errors.append(f"{svc_name}: ADAPTER_CAPABILITIES not valid JSON ({exc})")
            print(f"  {BAD} {svc_name}: ADAPTER_CAPABILITIES invalid JSON")
            continue
        # The adapter merges the two at runtime: the baked contract is the base,
        # ADAPTER_CAPABILITIES overrides and extends it (register.py `_caps`).
        # A generic image declares only what is true of the binary, so compose
        # supplying traits the contract omits is deploy-time wiring, not drift.
        # Drift is the two disagreeing on a key they BOTH declare.
        effective = {**caps, **compose_caps}
        conflicts = {k: (caps[k], compose_caps[k])
                     for k in caps.keys() & compose_caps.keys()
                     if caps[k] != compose_caps[k]}
        if conflicts:
            errors.append(f"{svc_name}: compose ADAPTER_CAPABILITIES conflicts with contract capabilities")
            print(f"  {BAD} {svc_name}: drift on {sorted(conflicts)}")
            for k, (c, d) in sorted(conflicts.items()):
                print(f"      {k}: contract={c!r} compose={d!r}")
        else:
            print(f"  {OK} {svc_name}: {effective.get('source')} ({effective.get('accuracy_class')})")

        # Coverage is judged on what the deployment actually advertises.
        advertised_sources.add(effective.get("source"))
        advertised_kinds.update(effective.get("kinds") or [])
        declared[svc_name] = effective

    # Accuracy class: the declared band has to agree with what the adapter can
    # actually emit, and an open-ended band has to carry its own number. A class
    # nobody checks is decoration.
    print("· accuracy class (declaration vs emitted range)")
    bands = json.loads(ACCURACY_CLASSES.read_text())["classes"]
    for svc_name, caps in sorted(declared.items()):
        name = caps.get("accuracy_class")
        if name is None:
            print(f"  {OK} {svc_name}: none declared")
            continue
        band = bands.get(name)
        if band is None:
            errors.append(f"{svc_name}: accuracy_class '{name}' is not in the vocabulary")
            print(f"  {BAD} {svc_name}: unknown class '{name}'")
            continue
        lower, upper = band.get("lowerBound", 0.0), band.get("upperBound")
        nominal = caps.get("nominalAccuracy")
        if upper is None and nominal is None:
            errors.append(
                f"{svc_name}: accuracy_class '{name}' is open-ended, so it resolves to "
                f"no value on its own; declare nominalAccuracy"
            )
            print(f"  {BAD} {svc_name}: '{name}' is open-ended and declares no nominalAccuracy")
            continue
        # An adapter whose emitted range is readable from its own settings gets
        # checked against the band it claims. Today that is the synthetic
        # walker, whose range is config, not computed.
        emitted = _emitted_accuracy_range(svc_name)
        if emitted and not (lower <= emitted[0] and (upper is None or emitted[1] <= upper)):
            errors.append(
                f"{svc_name}: emits {emitted[0]}-{emitted[1]}m but declares '{name}' "
                f"({lower}-{upper if upper is not None else '∞'}m)"
            )
            print(f"  {BAD} {svc_name}: emits {emitted[0]}-{emitted[1]}m, declares '{name}'")
        else:
            span = f"{emitted[0]}-{emitted[1]}m" if emitted else "computed per fix"
            print(f"  {OK} {svc_name}: '{name}', {span}")

    # Asset coverage: every source + kind must be served by some adapter.
    print("· asset coverage (assets.json vs advertised capabilities)")
    amap = json.loads(ASSETS.read_text())
    for a in amap.get("assets", []):
        # Schema v3: an asset binds one or more capabilities, each naming the
        # source that tracks it. Every one of them must be served, since the
        # engine polls them all and fuses the results.
        sources = [c.get("source") for c in a.get("capabilities", [])]
        unserved = [s for s in sources if s not in advertised_sources]
        if not sources:
            errors.append(f"asset {a['assetId']}: no capabilities declared")
            print(f"  {BAD} {a['assetId']}: no capabilities")
        elif unserved:
            for s in unserved:
                errors.append(f"asset {a['assetId']}: source '{s}' not advertised by any adapter")
                print(f"  {BAD} {a['assetId']}: source '{s}' unserved")
        elif a["kind"] not in advertised_kinds:
            errors.append(f"asset {a['assetId']}: kind '{a['kind']}' not advertised by any adapter")
            print(f"  {BAD} {a['assetId']}: kind '{a['kind']}' unadvertised")
        else:
            print(f"  {OK} {a['assetId']}: {a['kind']} via {', '.join(sources)}")

    # Schema conformance (best-effort).
    print("· schema (assets.json vs schema/asset.schema.json)")
    try:
        import jsonschema  # noqa
        jsonschema.validate(amap, json.loads(ASSET_SCHEMA.read_text()))
        print(f"  {OK} assets.json conforms to asset.schema.json")
    except ImportError:
        print("  · jsonschema not installed; schema check skipped")
    except Exception as exc:  # jsonschema.ValidationError + friends
        errors.append(f"assets.json schema violation: {exc.args[0] if exc.args else exc}")
        print(f"  {BAD} assets.json does not conform: {str(exc).splitlines()[0]}")

    print()
    if errors:
        print(f"{BAD} positioning-check: {len(errors)} problem(s)")
        for e in errors:
            print(f"    - {e}")
        return 1
    print(f"{OK} positioning-check: fabric consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
