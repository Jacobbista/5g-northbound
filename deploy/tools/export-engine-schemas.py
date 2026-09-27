#!/usr/bin/env python3
"""Write the engine's wire contracts as JSON Schema under schema/.

The models in services/positioning-engine are the single definition: the
engine parses with them, and this script publishes them. `--check` compares
instead of writing and exits 1 on drift. Run it with the engine's pinned
pydantic (`make contract-schemas` uses the engine venv): the schema text
depends on the pydantic version.

Usage:
    deploy/tools/export-engine-schemas.py           # write
    deploy/tools/export-engine-schemas.py --check   # verify the committed copies
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "positioning-engine"))

from app.models import EnginePosition  # noqa: E402
from app.wire import Announcement, DevicesBody, MeasurementBody  # noqa: E402

BASE = "https://github.com/Jacobbista/5g-northbound/blob/main/schema/"

# file name -> (model, description)
SCHEMAS = {
    "adapter-measurement.schema.json": (
        MeasurementBody,
        "Body of an adapter's GET /measurement/{positioningId}, read by the positioning engine. "
        "See docs/adapters.md.",
    ),
    "adapter-announcement.schema.json": (
        Announcement,
        "Body of POST /adapters, with which an adapter registers with the engine and declares its "
        "capabilities. See docs/adapter-registry.md.",
    ),
    "adapter-devices.schema.json": (
        DevicesBody,
        "Body of an adapter's GET /devices, the devices a source knows, read by the engine for "
        "onboarding.",
    ),
    "engine-position.schema.json": (
        EnginePosition,
        "Body of the engine's GET /position/{positioningId}, read by the CAMARA gateway.",
    ),
}


def render(model, description: str, name: str) -> str:
    schema = model.model_json_schema()
    doc = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": BASE + name, **schema}
    doc["description"] = description
    return json.dumps(doc, indent=2) + "\n"


def main() -> int:
    check = "--check" in sys.argv[1:]
    stale = []
    for name, (model, description) in SCHEMAS.items():
        path = ROOT / "schema" / name
        text = render(model, description, name)
        if check:
            if not path.is_file() or path.read_text() != text:
                stale.append(name)
        else:
            path.write_text(text)
    if stale:
        print("stale engine schemas, run `make contract-schemas`: " + ", ".join(stale))
        return 1
    print("engine schemas up to date." if check else "engine schemas written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
