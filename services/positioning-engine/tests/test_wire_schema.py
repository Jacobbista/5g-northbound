"""The published southbound schemas are the ones these models produce."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_committed_schemas_match_the_models():
    r = subprocess.run(
        [sys.executable, str(ROOT / "deploy" / "tools" / "export-engine-schemas.py"), "--check"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
