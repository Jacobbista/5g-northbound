#!/usr/bin/env python3
"""Transform a stored Asset Identity Map from schema v3 to v4.

v4 renames the two identifier fields to the profile's naming convention:
`asset_id` becomes `assetId` and a capability's `positioning_id` becomes
`positioningId`. The map is both the `GET/PUT /assets` body and the document on
the gateway's PVC, so the API and the stored document move together.

Run it with the gateway scaled to zero, against the PVC copy:

    deploy/tools/migrate_assets_v3_to_v4.py --in assets.json --dry-run
    deploy/tools/migrate_assets_v3_to_v4.py --in assets.json --out assets.v4.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RENAMES = {"asset_id": "assetId"}
CAPABILITY_RENAMES = {"positioning_id": "positioningId"}


def transform(doc: dict) -> dict:
    version = doc.get("version")
    if version == 4:
        sys.exit("already v4; nothing to do")
    if version != 3:
        sys.exit(f"refusing to transform version {version!r}: this tool reads v3 only")

    out = {"version": 4, "assets": []}
    for asset in doc.get("assets") or []:
        new = {RENAMES.get(k, k): v for k, v in asset.items()}
        new["capabilities"] = [
            {CAPABILITY_RENAMES.get(k, k): v for k, v in cap.items()}
            for cap in asset.get("capabilities") or []
        ]
        out["assets"].append(new)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="src", required=True, help="v3 asset map")
    ap.add_argument("--out", dest="dst", help="where to write the v4 map")
    ap.add_argument("--dry-run", action="store_true", help="report, write nothing")
    args = ap.parse_args()

    src = Path(args.src)
    doc = json.loads(src.read_text())
    out = transform(doc)

    print(f"v3 -> v4: {len(out['assets'])} asset(s)")
    for asset in out["assets"]:
        ids = ", ".join(c["positioningId"] for c in asset["capabilities"])
        print(f"  {asset['assetId']:<16} {len(asset['capabilities'])} capability(ies): {ids}")

    if args.dry_run:
        print("\ndry run: nothing written")
        return 0
    if not args.dst:
        sys.exit("give --out, or --dry-run to preview")
    Path(args.dst).write_text(json.dumps(out, indent=2) + "\n")
    print(f"\nwrote {args.dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
