from fastapi import APIRouter, Request, Response

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request):
    # Liveness: the process is up, independent of whether a schema is loaded.
    state = request.app.state.store
    return {
        "status": "ok",
        "schema_loaded": state.schema is not None,
        "vendor": state.schema.vendor if state.schema else None,
    }


@router.get("/ready")
async def ready(request: Request, response: Response):
    # Readiness: this adapter can serve measurements, i.e. a vendor schema is
    # loaded. Point the k8s readinessProbe here (standard across adapters):
    # 200 when ready, 503 + {error} when degraded, so a schema-less pod is
    # kept out of rotation while still answering /health and /contract.
    if request.app.state.store.schema is None:
        response.status_code = 503
        return {"status": "not-ready", "error": "no vendor schema loaded"}
    return {"status": "ready"}
