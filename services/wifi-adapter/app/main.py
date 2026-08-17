import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI

from .assemble import load_wifi_config, persist_calibration
from .calibration import CalibrationStore
from .config import settings
from .obs import install_hop_logging
from .models import CalibrationSample
from . import register
from .routers import calibration as calibration_router
from .routers import bindings as bindings_router
from .routers import contract, devices, health, ingest, measurement
from .wifi import WifiAdapter

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def _load_persisted_samples(bindings_path: Path) -> list[CalibrationSample]:
    """Re-hydrate the calibration store from the bindings file on disk.
    Returns an empty list if the file has no `calibration_samples` block."""
    try:
        raw = json.loads(bindings_path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    out: list[CalibrationSample] = []
    for entry in raw.get("calibration_samples") or []:
        try:
            out.append(CalibrationSample.model_validate(entry))
        except Exception as exc:
            log.warning("dropping malformed calibration sample: %s", exc)
    return out


async def _fetch_blueprint() -> Optional[dict]:
    """Fetch the canonical blueprint from the engine (the authority), retrying
    a few times because the engine may still be booting (engine <-> adapter
    startup is mutually dependent). Returns None when the engine has no
    blueprint yet (404) or stays unreachable - the adapter then boots degraded
    and a later reload picks it up."""
    base = settings.positioning_engine_url
    url = f"{base.rstrip('/')}/blueprint"
    for attempt in range(1, settings.blueprint_fetch_attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
            if resp.status_code == 404:
                log.warning("engine has no blueprint yet (404); booting degraded")
                return None
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            if attempt < settings.blueprint_fetch_attempts:
                await asyncio.sleep(settings.blueprint_fetch_backoff_s)
                continue
            log.warning("engine /blueprint unreachable after %d tries (%s)", attempt, exc)
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Degraded boot: a missing blueprint / unreachable engine / malformed
    # bindings must not crash the process. On failure we mark the pod not-ready
    # (readiness gates real traffic) but keep liveness + /contract answering.
    bindings_path = Path(settings.wifi_config_path)
    # Offline fallback only; in the cluster the blueprint comes from the engine.
    blueprint_path = Path(settings.layout_path) if settings.layout_path else None
    app.state.ready = False
    app.state.config_error = None
    app.state.adapter = None
    app.state.wifi_config = None
    app.state.bindings_path = bindings_path

    # The calibration store depends only on the bindings file (persisted
    # samples), NOT on the blueprint, so wire it unconditionally and FIRST.
    # Capture / state must answer even while the blueprint is still loading,
    # otherwise a degraded boot leaves request.app.state.calibration unset and
    # every calibration route 500s with AttributeError.
    samples = _load_persisted_samples(bindings_path)
    store = CalibrationStore(samples=samples)
    app.state.calibration = store
    app.state.persist_calibration = lambda overrides, samples: persist_calibration(
        bindings_path, overrides, samples
    )

    # Auto-persist samples after every capture / delete / clear so the operator
    # cannot lose survey data between runs. Path-loss overrides are NOT touched
    # here; they are written only on explicit apply.
    def _persist_samples_only(current_samples):
        try:
            persist_calibration(bindings_path, overrides={}, samples=current_samples)
        except Exception as exc:
            log.warning("auto-persist of calibration samples failed: %s", exc)

    store.on_samples_changed = _persist_samples_only

    async def _load_config() -> None:
        """Fetch the blueprint from the engine and assemble the live wifi
        config. Raises until the engine has a blueprint (engine <-> adapter
        boot is mutually dependent); the self-heal loop keeps retrying."""
        blueprint = await _fetch_blueprint()

        def _reload() -> "WifiConfig":  # noqa: F821
            # Calibration reloads re-read the bindings file (tx_power, samples);
            # the blueprint geometry is the one fetched here.
            return load_wifi_config(
                bindings_path=bindings_path,
                blueprint_path=blueprint_path,
                blueprint=blueprint,
            )

        wifi_cfg = _reload()
        app.state.wifi_config = wifi_cfg
        app.state.adapter = WifiAdapter(wifi_cfg)
        app.state.adapter.on_ingest = store.on_ingest
        app.state.reload_wifi_config = _reload
        app.state.config_error = None
        app.state.ready = True
        log.info(
            "wifi-adapter: %d routers, room %g x %g m, algo=%s, calibration samples=%d",
            len(wifi_cfg.routers), wifi_cfg.room_w, wifi_cfg.room_h, wifi_cfg.algorithm,
            len(samples),
        )

    async def _self_heal() -> None:
        # Mirror the mock's self-heal: keep retrying the blueprint-dependent
        # config load so wifi recovers once the engine is up, without a restart.
        delay = max(settings.blueprint_fetch_backoff_s * 2, 5.0)
        while not app.state.ready:
            await asyncio.sleep(delay)
            try:
                await _load_config()
            except Exception as exc:
                app.state.config_error = str(exc)
                log.warning("wifi-adapter: config not ready yet, retrying (%s)", exc)

    # Fast path inline; if the engine is not ready, self-heal in the background.
    try:
        await _load_config()
    except Exception as exc:
        app.state.config_error = str(exc)
        log.error(
            "wifi-adapter: initial config load failed, self-healing in background: %s", exc
        )

    heal_task = asyncio.create_task(_self_heal()) if not app.state.ready else None
    # Announce ourselves to the engine's adapter registry + heartbeat.
    reg_task = asyncio.create_task(register.heartbeat_loop())
    yield
    reg_task.cancel()
    if heal_task is not None:
        heal_task.cancel()
    await register.deregister()


app = FastAPI(title="WiFi Positioning Adapter", lifespan=lifespan)
install_hop_logging(app, "wifi-adapter")
app.include_router(health.router)
app.include_router(contract.router)
app.include_router(ingest.router)
app.include_router(measurement.router)
app.include_router(devices.router)
app.include_router(calibration_router.router)
app.include_router(bindings_router.router)
