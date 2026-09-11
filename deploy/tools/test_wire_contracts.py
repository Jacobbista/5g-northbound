"""Pin the two ends of every internal contract to each other.

Each of these contracts has a producer and a consumer that live in different
service trees of this repository. Their suites test each side against its own
expectation, so a rename on one side leaves both green and fails in the cluster.
These tests read both sides, and where reading is not enough they run them.

Two outages came from that gap. In v0.15.1 the vendor adapter began emitting
`accuracy` while the engine still parsed `accuracy_m`. In v0.16.0 no adapter
reached the engine at all: the announcement task died on a renamed key in the
adapter's own config dict, and a service suite cannot see that because the
producer and the consumer are in different trees.

Run by `make test` and by the `pytest (deploy/tools)` CI job.
"""

import asyncio
import importlib.util
import os
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _names(path: Path, pattern: str) -> set[str]:
    return set(re.findall(pattern, path.read_text(), re.M))


def test_measurement_keys_the_engine_parses_are_the_keys_adapters_emit():
    """`GET /measurement/{id}`: three producers, one consumer."""
    engine = ROOT / "services/positioning-engine/app/adapters/http.py"
    # A key read under a `.get()` guard is optional: wifi and synthetic have no
    # last-communication signal to report and legitimately omit it.
    optional = _names(engine, r'body\.get\("([a-zA-Z_]+)"')
    required = _names(engine, r'body\["([a-zA-Z_]+)"\]') - optional

    for adapter, emit_file, pattern in (
        ("vendor-adapter", "services/vendor-adapter/app/mapper.py", r'"([a-zA-Z_]+)":'),
        ("wifi-adapter", "services/wifi-adapter/app/models.py", r"^    ([a-zA-Z_]+):"),
        ("synthetic-adapter", "services/synthetic-adapter/app/models.py", r"^    ([a-zA-Z_]+):"),
    ):
        emitted = set(re.findall(pattern, (ROOT / emit_file).read_text(), re.M))
        missing = required - emitted
        assert not missing, f"{adapter} does not emit {sorted(missing)}"

    # An optional key still has to be spelled the same on both sides wherever a
    # producer does emit it.
    vendor: set[str] = set()
    for f in ("services/vendor-adapter/app/mapper.py",
              "services/vendor-adapter/app/routers/measurement.py"):
        vendor |= _names(ROOT / f, r'"([a-zA-Z_]+)":')
        vendor |= _names(ROOT / f, r'out\["([a-zA-Z_]+)"\]')
        vendor |= _names(ROOT / f, r'\["([a-zA-Z_]+)"\] =')
    for key in optional:
        assert key in vendor, f"the engine reads optional {key!r} that no producer emits"


def test_devices_fields_the_engine_copies_are_the_fields_adapters_emit():
    """`GET /devices`: the engine aggregates what each adapter reports."""
    engine = (ROOT / "services/positioning-engine/app/routers/devices.py").read_text()
    copied = set(re.findall(r'_COPY_FIELDS = \(([^)]*)\)', engine)[0].replace('"', "").split(", "))
    emitted: set[str] = set()
    for f in ("services/vendor-adapter/app/mapper.py",
              "services/vendor-adapter/app/routers/devices.py",
              "services/wifi-adapter/app/wifi.py",
              "services/synthetic-adapter/app/routers/devices.py"):
        emitted |= _names(ROOT / f, r'"([a-zA-Z_]+)":')
        emitted |= _names(ROOT / f, r'out\["([a-zA-Z_]+)"\]')
    # `position` is assembled by the engine, never emitted under that name.
    unknown = {c for c in copied - emitted if c != "position"}
    assert not unknown, f"the engine copies fields no adapter emits: {sorted(unknown)}"


# Models that describe an operator document rather than a wire body. They
# follow the document they read, not this project's convention, so a unit in
# the field name is correct there. Named one by one: an exemption by pattern
# would also excuse a wire model that happens to match.
_DOCUMENT_MODELS = ("GpsOrigin", "Floor", "FloorPlan", "Room", "Anchor",
                    "CalibrationSample", "Bindings", "WifiConfig")


def _wire_fields(path: Path) -> set[str]:
    """Field names declared by every model in the file except the ones that
    describe an operator document."""
    src = path.read_text()
    fields: set[str] = set()
    for block in re.split(r"^class ", src, flags=re.M)[1:]:
        if block.split("(")[0].strip() in _DOCUMENT_MODELS:
            continue
        fields |= set(re.findall(r"^    ([a-z_]+): ", block, re.M))
    return fields


def test_no_internal_contract_still_carries_a_unit_in_a_field_name():
    """One convention across everything this project names."""
    offenders: list[str] = []
    for f in ("services/positioning-engine/app/adapters/base.py",
              "services/positioning-engine/app/models.py",
              "services/wifi-adapter/app/models.py",
              "services/synthetic-adapter/app/models.py"):
        for name in _wire_fields(ROOT / f):
            if re.search(r"_(m|s|ms|dbm|mps)$", name):
                offenders.append(f"{f}:{name}")
    assert offenders == [], offenders


# --- POST /adapters: the announcement ------------------------------------
#
# Reading the two sides is not enough here. The v0.16.0 outage had both sides
# spelling `baseUrl` correctly on the wire: what broke was the adapter's own
# config dict, whose key was renamed while its readers were not, so the
# announcement task died of a KeyError before it ever posted. Only running the
# producer catches that, so this one executes it against a stub engine.


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _register_request_fields() -> set[str]:
    src = (ROOT / "services/positioning-engine/app/routers/adapters.py").read_text()
    body = re.search(r"class RegisterRequest\(BaseModel\):(.*?)\n\n", src, re.S).group(1)
    return set(re.findall(r"^    ([a-zA-Z_]+):", body, re.M))


async def _announce_once(mod, env: dict[str, str]) -> dict:
    """Run the heartbeat loop against a stub engine and return what it posted.

    An exception inside the loop propagates out of `wait_for` and fails the
    test, which is the point: in the pod that same exception killed a
    background task nobody awaited, and the log stayed silent.
    """
    captured: dict = {}

    class _Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None):
            captured["url"] = url
            captured["body"] = json

    original_env = {k: os.environ.get(k) for k in env}
    original_httpx = mod.httpx
    os.environ.update(env)
    mod.httpx = types.SimpleNamespace(AsyncClient=_Client)
    try:
        await asyncio.wait_for(mod.heartbeat_loop(), 0.3)
    except asyncio.TimeoutError:
        pass
    finally:
        mod.httpx = original_httpx
        for k, v in original_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return captured


def test_every_adapter_announces_itself_with_the_body_the_engine_accepts():
    accepted = _register_request_fields()
    assert "baseUrl" in accepted
    env = {
        "POSITIONING_ENGINE_URL": "http://engine:8000",
        "ADAPTER_NAME": "probe",
        "ADAPTER_BASE_URL": "http://probe:8000",
        "ADAPTER_KIND": "adapter",
        "ADAPTER_HEARTBEAT_S": "0.01",
    }
    for adapter in ("vendor-adapter", "wifi-adapter", "synthetic-adapter"):
        mod = _load(ROOT / f"services/{adapter}/app/register.py", f"{adapter}_register")
        posted = asyncio.run(_announce_once(mod, env))
        assert posted, f"{adapter} never announced itself to the engine"
        assert posted["url"] == "http://engine:8000/adapters"
        body = posted["body"]
        assert body["name"] == "probe"
        assert body["baseUrl"] == "http://probe:8000"
        unknown = set(body) - accepted
        assert not unknown, f"{adapter} announces fields the engine drops: {sorted(unknown)}"


# --- the gateway reads what the engine writes -----------------------------


def _reads(path: Path, func: str) -> set[str]:
    """Keys a single function pulls out of a JSON body it did not build."""
    src = (ROOT / path).read_text()
    body = re.search(rf"def {func}\(.*?(?=\n@|\nclass |\nasync def |\ndef |\Z)", src, re.S).group(0)
    return set(re.findall(r'\.get\("([a-zA-Z_]+)"', body))


def test_gateway_reads_the_adapter_fields_the_engine_reports():
    """`GET /adapters`: the engine reports, the gateway routes diagnostics."""
    engine = ROOT / "services/positioning-engine/app/adapters/http.py"
    registry = ROOT / "services/positioning-engine/app/registry.py"
    router = ROOT / "services/positioning-engine/app/routers/adapters.py"
    emitted = _names(engine, r'^            "([a-zA-Z]+)":')
    emitted |= _names(registry, r"^                ([a-zA-Z]+)=")
    # The envelope the router wraps the list in.
    emitted |= _names(router, r'return \{"([a-zA-Z]+)": registry')
    read = _reads("services/camara-gateway/app/routers/diagnostics.py", "_adapter_base_url")
    missing = read - emitted
    assert not missing, f"the gateway reads adapter fields the engine never reports: {sorted(missing)}"


def test_gateway_reads_the_device_fields_the_engine_reports():
    """`GET /devices`: the engine aggregates, the gateway offers onboarding."""
    engine = (ROOT / "services/positioning-engine/app/routers/devices.py").read_text()
    emitted = set(re.findall(r'_COPY_FIELDS = \(([^)]*)\)', engine)[0].replace('"', "").split(", "))
    emitted |= set(re.findall(r'entry\["([a-zA-Z]+)"\]', engine))
    emitted |= {"id", "source"}
    read = _reads("services/camara-gateway/app/routers/assets.py", "discoverable")
    missing = read - emitted
    assert not missing, f"the gateway reads device fields the engine never reports: {sorted(missing)}"


# The profile declares `verticalAccuracy`, and the gateway reads it from the
# engine body, but no engine path produces it yet: the fusion has no vertical
# error estimate. Listed here so the pin below stays meaningful and the gap
# stays visible instead of reading as a typo.
_DECLARED_NOT_YET_PRODUCED = {"vertical_accuracy_m"}


def test_gateway_reads_the_position_fields_the_engine_produces():
    """`GET /position/{id}`: the engine's northbound body, parsed once."""
    models = (ROOT / "services/positioning-engine/app/models.py").read_text()
    block = re.search(r"class EnginePosition\(BaseModel\):(.*)", models, re.S).group(1)
    emitted = set(re.findall(r"^    ([a-zA-Z_]+):", block, re.M))
    body = re.search(r"def _fetch_position\(.*?(?=\n\n\nasync def |\n\n\ndef )",
                     (ROOT / "services/camara-gateway/app/position.py").read_text(), re.S).group(0)
    read = set(re.findall(r'd\.get\("([a-zA-Z_]+)"', body)) | set(re.findall(r'd\["([a-zA-Z_]+)"\]', body))
    missing = read - emitted - _DECLARED_NOT_YET_PRODUCED
    assert not missing, f"the gateway reads position fields the engine never produces: {sorted(missing)}"
