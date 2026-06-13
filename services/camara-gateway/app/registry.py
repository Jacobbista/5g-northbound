"""Device registry: maps a CAMARA identifier (phoneNumber) to an internal device id.

Source of truth: device_registry_file (JSON) when set; falls back to the
device_registry env (flat phoneNumber->deviceId JSON map) for back-compat.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .config import get_settings

log = logging.getLogger(__name__)


@dataclass
class RegisteredDevice:
    phoneNumber: str
    deviceId: str
    label: str
    # True when the device is wired to a synthetic / demo-only data source
    # (mock-positioning, mock-wittra, …). The UI surfaces this as a "MOCK"
    # badge so operators don't mistake a fixture for a real device.
    simulated: bool = False


def load_devices() -> list[RegisteredDevice]:
    settings = get_settings()
    path = settings.device_registry_file
    if path:
        try:
            data = json.loads(Path(path).read_text())
            return [
                RegisteredDevice(
                    phoneNumber=d["phoneNumber"],
                    deviceId=d["deviceId"],
                    label=d.get("label", d["deviceId"]),
                    simulated=bool(d.get("simulated", False)),
                )
                for d in data.get("devices", [])
            ]
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            log.warning("device_registry_file %s unreadable (%s); using env", path, exc)

    try:
        flat = json.loads(settings.device_registry)
    except json.JSONDecodeError:
        flat = {}
    return [
        RegisteredDevice(phoneNumber=phone, deviceId=device_id, label=device_id)
        for phone, device_id in flat.items()
    ]


def phone_to_device_id() -> dict[str, str]:
    return {d.phoneNumber: d.deviceId for d in load_devices()}
