from fastapi import APIRouter, Request, Response

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    # Liveness: the process is up. Independent of business config, so a
    # misconfigured pod stays alive (and keeps serving /contract) instead of
    # crash-looping.
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request, response: Response):
    # Readiness: business config loaded successfully. Point the k8s
    # readinessProbe here so a pod with a bad bindings / blueprint file is
    # kept out of rotation while still answering /health and /contract.
    ok = getattr(request.app.state, "ready", True)
    if not ok:
        response.status_code = 503
        return {"status": "not-ready", "error": getattr(request.app.state, "config_error", None)}
    return {"status": "ready"}
