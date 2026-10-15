import pytest

from app.config import (
    DEFAULT_ADAPTER_TIMEOUT_S,
    DEFAULT_API_KEY_HEADER,
    adapter_budget,
    adapter_options,
)


def test_adapter_options_defaults_when_no_env(monkeypatch):
    # Use a unique name unlikely to collide with anything set in the env.
    name = "z_nonexistent_adapter_xyz"
    for var in ("API_KEY", "API_KEY_HEADER", "TIMEOUT"):
        monkeypatch.delenv(f"ADAPTER_{name.upper()}_{var}", raising=False)
    opts = adapter_options(name)
    assert opts["timeout"] is None
    assert opts["headers"] is None


def test_adapter_options_reads_api_key(monkeypatch):
    monkeypatch.setenv("ADAPTER_WITTRA_API_KEY", "secret-token")
    opts = adapter_options("wittra")
    assert opts["headers"] == {DEFAULT_API_KEY_HEADER: "secret-token"}


def test_adapter_options_custom_header_name(monkeypatch):
    monkeypatch.setenv("ADAPTER_WITTRA_API_KEY", "abc")
    monkeypatch.setenv("ADAPTER_WITTRA_API_KEY_HEADER", "Authorization")
    opts = adapter_options("wittra")
    assert opts["headers"] == {"Authorization": "abc"}


def test_adapter_options_timeout_override(monkeypatch):
    monkeypatch.setenv("ADAPTER_WITTRA_TIMEOUT", "4.5")
    opts = adapter_options("wittra")
    assert opts["timeout"] == 4.5


def test_adapter_options_invalid_timeout_falls_back(monkeypatch):
    monkeypatch.setenv("ADAPTER_WITTRA_TIMEOUT", "not-a-number")
    opts = adapter_options("wittra")
    assert opts["timeout"] is None


def test_adapter_options_name_normalised(monkeypatch):
    # Hyphens and case in the adapter name map to ADAPTER_WIFI_BACKEND_*
    monkeypatch.setenv("ADAPTER_WIFI_BACKEND_API_KEY", "k")
    opts = adapter_options("wifi-backend")
    assert opts["headers"] == {DEFAULT_API_KEY_HEADER: "k"}


def test_adapter_options_ignores_other_adapters(monkeypatch):
    monkeypatch.setenv("ADAPTER_WITTRA_API_KEY", "wittra-secret")
    opts = adapter_options("wifi")
    assert opts["headers"] is None


@pytest.mark.parametrize("env, declared, budget", [
    (None, None, DEFAULT_ADAPTER_TIMEOUT_S),
    (None, 3.0, 3.0),
    ("2.0", 3.0, 2.0),
])
def test_the_budget_toward_an_adapter_follows_its_declaration_unless_configured(monkeypatch, env, declared, budget):
    """A vendor adapter declares a budget covering its call to the cloud, so
    the engine does not give up while the adapter still waits."""
    if env is None:
        monkeypatch.delenv("ADAPTER_SLOWSRC_TIMEOUT", raising=False)
    else:
        monkeypatch.setenv("ADAPTER_SLOWSRC_TIMEOUT", env)
    caps = {} if declared is None else {"responseTimeout": declared}
    assert adapter_budget("slowsrc", caps) == budget
