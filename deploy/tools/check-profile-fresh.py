#!/usr/bin/env python3
"""Fail if the committed profiled specs drift from the base + overlays.

Regenerates each profiled document in memory and compares it semantically
(parsed YAML equality, not byte diff) against the committed file in
`generated/`, so a PyYAML formatting change never trips the gate - only a real
divergence does. Run by CI and re-runnable locally.

    check-profile-fresh.py
"""
import sys
from pathlib import Path

import yaml

from apply_overlay import apply_overlay

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "services/camara-gateway/spec"
PROFILE = ROOT / "spec/private-profile"
GENERATED = PROFILE / "generated"

PAIRS = [
    ("location-retrieval.yaml", "overlay-retrieval.yaml", "location-retrieval.profiled.yaml"),
    ("location-verification.yaml", "overlay-verification.yaml", "location-verification.profiled.yaml"),
]


def main():
    stale = []
    for base_name, overlay_name, out_name in PAIRS:
        base = yaml.safe_load((BASE / base_name).read_text())
        overlay = yaml.safe_load((PROFILE / overlay_name).read_text())
        fresh = apply_overlay(base, overlay)
        committed_path = GENERATED / out_name
        if not committed_path.exists():
            stale.append(f"{out_name}: missing (run `make profile-spec`)")
            continue
        committed = yaml.safe_load(committed_path.read_text())
        if fresh != committed:
            stale.append(f"{out_name}: stale (run `make profile-spec` and commit)")
    if stale:
        print("Profiled specs out of date:")
        for s in stale:
            print(f"  {s}")
        sys.exit(1)
    print("Profiled specs up to date.")


if __name__ == "__main__":
    main()
