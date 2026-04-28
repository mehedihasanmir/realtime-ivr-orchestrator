from fastapi import FastAPI

from app.api.routes.voice import router as voice_router
from app.core.config import get_settings
from app.core.logging import configure_logging

configure_logging()

app = FastAPI(title="AI Voice Agent", version="1.0.0")
app.include_router(voice_router)


@app.on_event("startup")
async def startup() -> None:
    get_settings()


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}
