from fastapi import APIRouter, Request

router = APIRouter(tags=["adapters"])


@router.get("/adapters")
async def list_adapters(request: Request):
    """Snapshot of every configured adapter's health.

    Operator-facing diagnostic. Reports the cooldown state managed by
    `HttpAdapter` so the demo (and any monitoring) can surface "wittra:
    degraded" without polling the adapter directly.
    """
    adapters = request.app.state.adapters
    return {
        "adapters": [
            a.status() for a in adapters.values()
            if hasattr(a, "status")
        ]
    }
