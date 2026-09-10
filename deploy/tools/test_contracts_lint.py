"""Static checks on the env contracts themselves, run with the repo's pytest."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_lint_is_clean_on_the_repo_contracts():
    r = subprocess.run(
        [sys.executable, str(ROOT / "deploy" / "tools" / "contracts.py"), "lint"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout


def test_every_declared_type_is_in_the_allowed_set():
    sys.path.insert(0, str(ROOT / "deploy" / "tools"))
    import contracts

    for c in contracts.load_contracts():
        for v in c.vars:
            assert v.type in contracts.ALLOWED_TYPES, f"{c.service}.{v.name}: {v.type}"


def test_no_service_declares_a_vendor_specific_variable():
    """The vendor-adapter image is generic: the variables a vendor needs are
    named by the schema an operator loads and are served at GET /contract, so
    no committed contract names one."""
    sys.path.insert(0, str(ROOT / "deploy" / "tools"))
    import contracts

    for c in contracts.load_contracts():
        for v in c.vars:
            assert not v.name.startswith("WITTRA_"), f"{c.service}.{v.name}"
