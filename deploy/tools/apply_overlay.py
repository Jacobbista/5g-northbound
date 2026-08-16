#!/usr/bin/env python3
"""Apply an OpenAPI Overlay (1.0.0) to a base OpenAPI document.

Supports the dotted-JSONPath targets the private-asset profile overlays use
(`$.a.b.c`): `update` deep-merges an object into the target (or replaces a
scalar); `remove: true` deletes it. Enough to produce the profiled spec from the
pinned CAMARA base without hand-editing it - a full Overlay tool (e.g. Redocly)
applies the same files. Depends only on PyYAML.

    apply_overlay.py <base.yaml> <overlay.yaml> <out.yaml>
"""
import sys

import yaml


def resolve_parent(doc, target):
    if not target.startswith("$."):
        raise ValueError(f"unsupported target (expected '$.…'): {target}")
    parts = target[2:].split(".")
    node = doc
    for p in parts[:-1]:
        node = node[p]
    return node, parts[-1]


def deep_merge(dst, src):
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            deep_merge(dst[k], v)
        else:
            dst[k] = v


def apply_overlay(base, overlay):
    for i, action in enumerate(overlay.get("actions", [])):
        parent, key = resolve_parent(base, action["target"])
        if action.get("remove"):
            parent.pop(key, None)
        elif "update" in action:
            upd = action["update"]
            if isinstance(upd, dict) and isinstance(parent.get(key), dict):
                deep_merge(parent[key], upd)
            else:
                parent[key] = upd
        else:
            raise ValueError(f"action {i}: neither 'update' nor 'remove'")
    return base


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    base_p, overlay_p, out_p = sys.argv[1:]
    with open(base_p) as f:
        base = yaml.safe_load(f)
    with open(overlay_p) as f:
        overlay = yaml.safe_load(f)
    merged = apply_overlay(base, overlay)
    for required in ("openapi", "info", "paths", "components"):
        if required not in merged:
            sys.exit(f"merged spec is missing top-level '{required}'")
    with open(out_p, "w") as f:
        yaml.safe_dump(merged, f, sort_keys=False, allow_unicode=True)
    print(f"  wrote {out_p}")


if __name__ == "__main__":
    main()
