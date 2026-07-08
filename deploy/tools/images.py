#!/usr/bin/env python3
"""Show what is published per image, and which images a release changed.

The CI (`.github/workflows/build.yml`) builds EVERY image on EVERY `v*` tag,
so a version tag exists for all of them even when a service did not change.
Docker builds are not reproducible (layer timestamps differ), so the rebuilt
image gets a new digest every time - the digest cannot tell you whether the
SOURCE changed. The reliable signal is the git diff over each service's path
between the two tags. So:

    python deploy/tools/images.py            # latest published tag per image (ghcr)
    python deploy/tools/images.py v0.8.6 v0.8.7   # which images' SOURCE changed (git)

The `latest` view needs the `gh` CLI (logged in); the diff view is pure git.
Only the images the diff marks CHANGED are worth re-pinning; the rest carry
identical source and a re-pin would just churn to an equivalent image.
"""
from __future__ import annotations

import json
import subprocess
import sys

REPO = "5g-northbound"
# image -> build context path (mirrors .github/workflows/build.yml matrix).
IMAGES = {
    "camara-gateway": "services/camara-gateway",
    "positioning-engine": "services/positioning-engine",
    "wifi-positioning": "services/wifi-positioning",
    "rest-adapter": "services/rest-adapter",
    "placement-editor": "services/placement-editor",
    "positioning-demo": "services/positioning-demo",
    "mock-positioning": "mocks/mock-positioning",
}


def _versions(image: str) -> list[dict]:
    """Return ghcr version records for one image (newest first)."""
    pkg = f"{REPO}%2F{image}"
    try:
        out = subprocess.run(
            ["gh", "api", "--paginate", f"user/packages/container/{pkg}/versions"],
            capture_output=True, text=True, check=True,
        ).stdout
    except subprocess.CalledProcessError as exc:
        print(f"  ! {image}: gh api failed ({exc.stderr.strip() or exc})", file=sys.stderr)
        return []
    # --paginate concatenates JSON arrays; wrap so json can read them all.
    records: list[dict] = []
    for chunk in out.replace("][", "]\x00[").split("\x00"):
        chunk = chunk.strip()
        if chunk:
            records.extend(json.loads(chunk))
    return records


def _semver_key(t: str) -> list[int]:
    return [int(p) for p in t.lstrip("v").split(".") if p.isdigit()]


def latest_report() -> None:
    """Latest published version tag per image, from ghcr."""
    for image in IMAGES:
        tags = []
        for v in _versions(image):
            for t in v.get("metadata", {}).get("container", {}).get("tags", []):
                if t and t[0].isdigit():  # semver only; skip latest / sha-...
                    tags.append(t)
        if not tags:
            print(f"{image:22} (no published versions)")
            continue
        print(f"{image:22} {max(tags, key=_semver_key)}")


def _git_changed(path: str, a: str, b: str) -> int:
    """Number of files changed under `path` between two refs (0 = unchanged)."""
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{a}..{b}", "--", path],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return len([ln for ln in out.splitlines() if ln])


def diff_report(a: str, b: str) -> None:
    """Which images' SOURCE changed between two tags (git, reproducible)."""
    lo, hi = sorted([a, b], key=_semver_key)
    print(f"source changed between {lo} and {hi} (re-pin only these):")
    changed = False
    for image, path in IMAGES.items():
        n = _git_changed(path, lo, hi)
        if n:
            changed = True
            print(f"  {image:22} CHANGED ({n} file{'s' if n != 1 else ''})")
    if not changed:
        print("  (no service source changed)")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if len(args) == 2:
        diff_report(args[0], args[1])
    else:
        latest_report()
