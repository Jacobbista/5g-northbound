"""Kind-2 surfaces carry one convention.

No standard governs the surfaces this project adds beside CAMARA: Commonalities
mandates lowerCamelCase for CAMARA-defined attributes and is silent on added
ones. The project therefore declares CAMARA's own convention for them, so a
consumer meets one spelling across the profile. See docs/contracts.md.
"""

import re
from pathlib import Path

import yaml

SPEC = Path(__file__).resolve().parents[3] / "spec" / "private-profile"
CAMEL = re.compile(r"[a-z]+([A-Z][a-z0-9]*)*")


def _property_names(node, out):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "properties" and isinstance(value, dict):
                out.update(value.keys())
            _property_names(value, out)
    elif isinstance(node, list):
        for value in node:
            _property_names(value, out)


def _bad_names(filename: str) -> list[str]:
    names: set[str] = set()
    _property_names(yaml.safe_load((SPEC / filename).read_text()), names)
    return sorted(n for n in names if not CAMEL.fullmatch(n))


def test_extension_endpoints_are_lower_camel_case():
    assert _bad_names("extensions.yaml") == []


def test_stream_channel_is_lower_camel_case():
    assert _bad_names("asyncapi-stream.yaml") == []


def test_diagnostics_resource_is_lower_camel_case():
    # The vendorSpecific bag declares additionalProperties and names no
    # properties, so its contents never reach this check. That is the boundary:
    # a bag's contents are carried as authored, a field this project names is not.
    assert _bad_names("device-diagnostics.yaml") == []
