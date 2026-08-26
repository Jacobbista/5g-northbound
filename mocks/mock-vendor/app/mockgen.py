"""Turn a vendor schema into responses that satisfy it.

`vendor-adapter` reads a schema and PARSES a vendor response into a Measurement
(dotted-path lookups, list indices, `-1` = last element). This module does the
inverse: given the same schema, it BUILDS a response whose structure the schema
resolves back to the injected values. So the mock is not tied to one vendor -
point it at a different schema and it emits that vendor's shape.
"""

import re
from typing import Any


def _is_index(part: str) -> bool:
    try:
        int(part)
        return True
    except ValueError:
        return False


def set_path(root: Any, dotted: str, value: Any) -> Any:
    """Inverse of the adapter's `get_path`: build nested dict/list so that a
    later `get_path(root, dotted)` returns `value`. Integer segments (including
    `-1`) are list indices; `-1` maps to a single-element list (index 0)."""
    cur = root
    parts = dotted.split(".")
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        if _is_index(part):
            idx = int(part)
            pos = 0 if idx < 0 else idx
            while len(cur) <= pos:
                cur.append(None)
            if last:
                cur[pos] = value
            else:
                if cur[pos] is None:
                    cur[pos] = [] if _is_index(parts[i + 1]) else {}
                cur = cur[pos]
        else:
            if last:
                cur[part] = value
            else:
                if cur.get(part) is None:
                    cur[part] = [] if _is_index(parts[i + 1]) else {}
                cur = cur[part]
    return root


def _root_for(dotted: str) -> Any:
    return [] if _is_index(dotted.split(".")[0]) else {}


def parse_template(tpl: str) -> tuple[str, dict[str, str]]:
    """Split a path template into its path part and a {param: value_template}
    query map. `.../data?deviceId={device_id}&dataType=location` ->
    ("/.../data", {"deviceId": "{device_id}", "dataType": "location"})."""
    if "?" not in tpl:
        return tpl, {}
    path_part, query = tpl.split("?", 1)
    params: dict[str, str] = {}
    for pair in query.split("&"):
        key, _, val = pair.partition("=")
        params[key] = val
    return path_part, params


def _path_regex(path_part: str) -> re.Pattern:
    regex = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", path_part)
    return re.compile("^" + regex + "$")


def match_template(tpl: str, req_path: str, query: dict[str, str]) -> dict[str, str] | None:
    """Match a request path + query params against a template. Returns the
    extracted template variables, or None when the request does not fit."""
    path_part, qtpl = parse_template(tpl)
    m = _path_regex(path_part).match(req_path)
    if m is None:
        return None
    out = dict(m.groupdict())
    for key, val_tpl in qtpl.items():
        var = re.fullmatch(r"\{(\w+)\}", val_tpl)
        if var:
            if key not in query:
                return None
            out[var[1]] = query[key]
        elif query.get(key) != val_tpl:
            return None
    return out


def build_telemetry(mapping: dict, values: dict[str, Any]) -> Any:
    """Build one telemetry response whose `mapping` PathSpecs resolve to
    `values` (keyed by the mapping field name: latitude, longitude, ...)."""
    specs = [(name, spec) for name, spec in mapping.items()
             if isinstance(spec, dict) and "path" in spec]
    if not specs:
        return {}
    root = _root_for(specs[0][1]["path"])
    for name, spec in specs:
        set_path(root, spec["path"], values.get(name, 0.0))
    return root


def _set_if_path(entry: dict, spec: Any, value: Any) -> None:
    if isinstance(spec, dict) and "path" in spec:
        set_path(entry, spec["path"], value)


def build_discover(discover: dict, lat: float, lon: float, height: float) -> Any:
    """Build a device list that exercises the schema's `discover` block: one
    mobile asset (no fixed position) and one fixed-position node, with the
    device_type each `classify` branch keys off, so onboarding sees both an
    asset and an infrastructure candidate."""
    dmap = discover.get("mapping", {})
    classify = discover.get("classify") or {}
    asset_when = classify.get("asset_when") or {}
    asset_type = asset_when.get("equals") if asset_when.get("path") else None

    specs = [
        {"id": "MOCK-ASSET-01", "label": "Mock Asset 01", "type": asset_type or "tag", "fixed": False},
        {"id": "MOCK-NODE-01", "label": "Mock Node 01", "type": "node", "fixed": True},
    ]
    entries = []
    for s in specs:
        entry: dict = {}
        _set_if_path(entry, dmap.get("vendor_device_id"), s["id"])
        _set_if_path(entry, dmap.get("label"), s["label"])
        if s["type"] is not None:
            _set_if_path(entry, dmap.get("device_type"), s["type"])
        if s["fixed"]:
            _set_if_path(entry, dmap.get("latitude"), lat)
            _set_if_path(entry, dmap.get("longitude"), lon)
            _set_if_path(entry, dmap.get("height_m"), height)
        entries.append(entry)

    list_path = discover.get("list_path", "")
    if list_path:
        return set_path(_root_for(list_path), list_path, entries)
    return entries


def build_diagnostics(mapping: dict) -> Any:
    """Build a body satisfying a diagnostics on_demand mapping: set a plausible
    value at each PathSpec's dotted path. ConstSpecs need no synthetic source."""
    specs = [(name, spec) for name, spec in mapping.items()
             if isinstance(spec, dict) and "path" in spec]
    if not specs:
        return {}
    root = _root_for(specs[0][1]["path"])
    for _name, spec in specs:
        value = [-93, -87] if "rssi" in spec["path"] else 1
        set_path(root, spec["path"], value)
    return root
