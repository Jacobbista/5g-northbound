from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request):
    state = request.app.state.store
    return {
        "status": "ok",
        "schema_loaded": state.schema is not None,
        "vendor": state.schema.vendor if state.schema else None,
    }
