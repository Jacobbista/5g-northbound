#!/usr/bin/env python3
"""Local demo config check.

`services/location-app/public/env-config.js` is gitignored and `make demo`
never overwrites it, so local values (a real Mapbox token, the real venue
blueprint) survive. The cost is that it drifts: it keeps whatever it was
copied from, while the committed template and the realm move on.

Two checks, both against the thing that actually defines the answer rather
than against a list kept here:

  1. the Keycloak client the file names must be defined in the realm the demo
     imports (`dev/keycloak-realm.json`). A stale client id is accepted by
     every layer until the browser, which reports only "Keycloak init failed";
  2. keys the template has gained since the local copy was made are reported,
     since a missing one silently falls through to a hard-coded default.

Advisory: prints and exits 0 either way. A local config that has drifted is a
reason to warn, not a reason to refuse to start the demo.

Usage: deploy/tools/check_demo_env.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENV_CONFIG = REPO / "services" / "location-app" / "public" / "env-config.js"
ENV_TEMPLATE = REPO / "services" / "location-app" / "public" / "env-config.example.js"
REALM = REPO / "dev" / "keycloak-realm.json"

WARN, OK = "\033[33m!\033[0m", "\033[32m✓\033[0m"


def _keys_and_values(path: Path) -> dict[str, str]:
    """Parse `KEY: "value",` pairs out of the config object. Comment lines are
    skipped, so a commented-out key does not read as declared."""
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        m = re.match(r'(VITE_[A-Z0-9_]+)\s*:\s*"([^"]*)"', stripped)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def main() -> int:
    if not ENV_CONFIG.is_file():
        # Fresh checkout: `make demo` bootstraps it from the template first,
        # so there is nothing to have drifted.
        return 0

    local = _keys_and_values(ENV_CONFIG)
    warned = False

    if REALM.is_file():
        realm = json.loads(REALM.read_text())
        defined = {c.get("clientId") for c in realm.get("clients", [])}
        client = local.get("VITE_KEYCLOAK_CLIENT_ID")
        if client and client not in defined:
            warned = True
            print(
                f"  {WARN} env-config.js names Keycloak client '{client}', which realm "
                f"'{realm.get('realm')}' does not define."
            )
            print(f"      The realm defines: {', '.join(sorted(c for c in defined if c))}.")
            print(f"      The browser will report only \"Keycloak init failed\". Edit {ENV_CONFIG.relative_to(REPO)}.")

    if ENV_TEMPLATE.is_file():
        missing = sorted(set(_keys_and_values(ENV_TEMPLATE)) - set(local))
        if missing:
            warned = True
            print(f"  {WARN} env-config.js is missing keys the template has: {', '.join(missing)}.")
            print("      Each falls through to a hard-coded default until you add it.")

    if not warned:
        print(f"  {OK} demo env config: consistent with the template and the realm")
    return 0


if __name__ == "__main__":
    sys.exit(main())
