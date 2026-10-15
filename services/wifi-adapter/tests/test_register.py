"""The adapter announces its own instance and deregisters only that one, so a
stopping pod never removes the pod that replaced it."""

import json

import httpx
import pytest
import respx

from app import register


class _Stop(Exception):
    pass


@respx.mock
async def test_announcement_and_deregistration_name_this_instance(monkeypatch):
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine")
    monkeypatch.setenv("ADAPTER_NAME", "src")
    monkeypatch.setenv("ADAPTER_BASE_URL", "http://src:8080")
    post = respx.post("http://engine/adapters").mock(return_value=httpx.Response(200, json={}))
    delete = respx.delete("http://engine/adapters/src").mock(return_value=httpx.Response(200, json={}))

    async def stop(_):
        raise _Stop

    monkeypatch.setattr(register.asyncio, "sleep", stop)
    with pytest.raises(_Stop):
        await register.heartbeat_loop()
    await register.deregister()

    assert json.loads(post.calls.last.request.content)["instance"] == register.INSTANCE
    assert delete.calls.last.request.url.params["instance"] == register.INSTANCE
