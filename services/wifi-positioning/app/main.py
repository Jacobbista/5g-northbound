import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from .assemble import load_wifi_config, persist_calibration
from .calibration import CalibrationStore
from .config import settings
from .models import CalibrationSample
from .routers import calibration as calibration_router
from .routers import health, ingest, measurement
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    bindings_path = Path(settings.wifi_config_path)
    blueprint_path = Path(settings.layout_path) if settings.layout_path else None

    def _reload() -> "WifiConfig":  # noqa: F821
        return load_wifi_config(
            bindings_path=bindings_path,
            blueprint_path=blueprint_path,
        )

    wifi_cfg = _reload()
    app.state.wifi_config = wifi_cfg
    app.state.adapter = WifiAdapter(wifi_cfg)

    samples = _load_persisted_samples(bindings_path)
    store = CalibrationStore(samples=samples)
    app.state.calibration = store
    app.state.adapter.on_ingest = store.on_ingest

    # Closures over the resolved paths so the calibration router does not
    # need to know about config / settings plumbing.
    app.state.reload_wifi_config = _reload
    app.state.persist_calibration = lambda overrides, samples: persist_calibration(
        bindings_path, overrides, samples
    )

    # Auto-persist samples after every capture / delete / clear so the
    # operator cannot lose survey data between runs. Path-loss overrides
    # are NOT touched here; they are written only on explicit apply.
    def _persist_samples_only(current_samples):
        try:
            persist_calibration(bindings_path, overrides={}, samples=current_samples)
        except Exception as exc:
            log.warning("auto-persist of calibration samples failed: %s", exc)

    store.on_samples_changed = _persist_samples_only

    log.info(
        "wifi-positioning: %d routers, room %g x %g m, algo=%s, calibration samples=%d",
        len(wifi_cfg.routers), wifi_cfg.room_w, wifi_cfg.room_h, wifi_cfg.algorithm,
        len(samples),
    )
    yield


app = FastAPI(title="WiFi Positioning Adapter", lifespan=lifespan)
app.include_router(health.router)
app.include_router(ingest.router)
app.include_router(measurement.router)
app.include_router(calibration_router.router)
