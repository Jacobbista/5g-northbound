import json
import time
from pathlib import Path

import httpx
import pytest
import respx
import yaml
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwk, jwt
from jsonschema import Draft7Validator, RefResolver

KID = "test-key-1"
CERTS_URL = "http://kc.test/auth/realms/5g-testbed/protocol/openid-connect/certs"

_SPEC_DIR = Path(__file__).resolve().parents[1] / "spec"


@pytest.fixture(scope="session")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def private_pem(rsa_key):
    from cryptography.hazmat.primitives import serialization

    return rsa_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


@pytest.fixture(scope="session")
def jwks(rsa_key):
    from cryptography.hazmat.primitives import serialization

    pub_pem = rsa_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    key = jwk.construct(pub_pem, "RS256").to_dict()
    key["kid"] = KID
    key["alg"] = "RS256"
    key["use"] = "sig"
    return {"keys": [key]}


@pytest.fixture
def make_token(private_pem):
    def _make(roles=None, exp_offset=3600, org=None):
        now = int(time.time())
        claims = {
            "iat": now,
            "exp": now + exp_offset,
            "azp": "camara-gateway",
            "realm_access": {"roles": roles or []},
        }
        if org is not None:
            claims["org"] = org
        return jwt.encode(claims, private_pem, algorithm="RS256", headers={"kid": KID})

    return _make


# Asset Identity Map used by the gateway tests. asset_id -> positioning_id,
# matching the engine /position/{positioning_id} mocks in the suite.
_TEST_ASSETS = {
    "version": 2,
    "assets": [
        {"asset_id": "tool-880", "positioning_id": "wifi-asset-01", "kind": "tool",
         "source": "wifi", "org": "fiskarheden", "label": "WiFi asset 01"},
        {"asset_id": "forklift-7", "positioning_id": "mock-demo-01", "kind": "forklift",
         "source": "mock", "org": "fiskarheden", "label": "Mock demo 01", "simulated": True},
        {"asset_id": "pkg-4471", "positioning_id": "wittra-tag-01", "kind": "pallet",
         "source": "wittra", "org": "fiskarheden", "label": "Wittra tag 01", "simulated": True},
    ],
}


@pytest.fixture
def settings_env(monkeypatch, tmp_path):
    monkeypatch.setenv("KEYCLOAK_URL", "http://kc.test/auth")
    monkeypatch.setenv("KEYCLOAK_REALM", "5g-testbed")
    monkeypatch.setenv("SKIP_AUTH", "false")
    monkeypatch.delenv("POSITIONING_ENGINE_URL", raising=False)  # -> mock
    # Asset registry: seed a writable store (no mounted-file path at runtime).
    store = tmp_path / "assets.json"
    store.write_text(json.dumps(_TEST_ASSETS))
    monkeypatch.setenv("ASSET_STORE_FILE", str(store))
    monkeypatch.setenv("ASSET_SEED_FILE", str(tmp_path / "noseed.json"))
    import app.auth as auth
    from app.config import get_settings

    get_settings.cache_clear()
    auth._jwks_cache = {}
    yield
    get_settings.cache_clear()
    auth._jwks_cache = {}


@pytest.fixture
def app(settings_env):
    from app.main import app as _app

    return _app


@pytest.fixture
async def respx_mock(app, jwks):
    with respx.mock(assert_all_called=False, assert_all_mocked=False) as mock:
        mock.get(CERTS_URL).mock(return_value=httpx.Response(200, json=jwks))
        yield mock


@pytest.fixture
async def client(app, respx_mock):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# --- CAMARA response schema validation ---


def _validator(spec_file: str, schema_name: str):
    spec = yaml.safe_load((_SPEC_DIR / spec_file).read_text())
    resolver = RefResolver.from_schema(spec)
    schema = {"$ref": f"#/components/schemas/{schema_name}"}
    return Draft7Validator(schema, resolver=resolver)


@pytest.fixture(scope="session")
def location_validator():
    return _validator("location-retrieval.yaml", "Location")


@pytest.fixture(scope="session")
def verify_validator():
    return _validator("location-verification.yaml", "VerifyLocationResponse")
