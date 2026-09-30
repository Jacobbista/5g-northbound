"""Every published image declares exactly the environment variables it reads.

A variable is read when the service's `Settings` class names it, when its code
calls `os.environ` or `os.getenv` with a literal name, or when its
`entrypoint.sh` expands it. A name built at runtime, such as
f"ADAPTER_{key}_API_KEY", is declared with the placeholder {NAME}. A variable a
service reads without declaring it is invisible to a deployment. One it
declares without reading is a promise the binary does not keep."""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = sorted((ROOT / "services").glob("*/env.contract.yaml"))

_ENV_CALL = re.compile(r'os\.(?:environ\.get|getenv)\(\s*"([A-Z0-9_]+)"|os\.environ\[\s*"([A-Z0-9_]+)"')
_SETTINGS_CLASS = re.compile(r"^class Settings\(BaseSettings\):\n(.*?)(?=^\S|\Z)", re.M | re.S)
_SETTINGS_FIELD = re.compile(r"^    ([a-z_][a-z0-9_]*)\s*:", re.M)
_SHELL_VAR = re.compile(r"\$\{([A-Z0-9_]+)")
_ENV_FSTRING = re.compile(r'os\.(?:environ\.get|getenv)\(\s*f"([A-Z0-9_]*\{[a-z_]+\}[A-Z0-9_{}a-z]*)"')
_PLACEHOLDER = re.compile(r"\{[a-z_]+\}")


def _declared(contract: Path) -> set[str]:
    raw = yaml.safe_load(contract.read_text())
    return {e["name"] for tier in ("required", "recommended", "optional") for e in raw.get(tier) or []}


def _read(service: Path) -> set[str]:
    names: set[str] = set()
    for source in (service / "app").rglob("*.py") if (service / "app").is_dir() else []:
        text = source.read_text()
        names |= {a or b for a, b in _ENV_CALL.findall(text)}
        names |= {_PLACEHOLDER.sub("{NAME}", n) for n in _ENV_FSTRING.findall(text)}
        for block in _SETTINGS_CLASS.findall(text):
            names |= {f.upper() for f in _SETTINGS_FIELD.findall(block) if f != "model_config"}
    entrypoint = service / "entrypoint.sh"
    if entrypoint.is_file():
        names |= set(_SHELL_VAR.findall(entrypoint.read_text()))
    return names


@pytest.mark.parametrize("contract", CONTRACTS, ids=lambda p: p.parent.name)
def test_contract_declares_what_the_service_reads(contract):
    service = contract.parent
    read, declared = _read(service), _declared(contract)
    assert not read - declared, f"{service.name} reads undeclared {sorted(read - declared)}"
    if (service / "app").is_dir():
        assert not declared - read, f"{service.name} declares unread {sorted(declared - read)}"
