from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    # Liveness.
    return {"status": "ok"}


@router.get("/ready")
async def ready():
    # Readiness (standard across adapters): the mock synthesises its own data
    # and self-heals the layout frame in the background, so it is always ready
    # to answer once the process is up.
    return {"status": "ready"}
