from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.auth import router as auth_router
from app.api.routes.voice import router as voice_router
from app.core.config import get_settings
from app.core.logging import configure_logging

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate settings eagerly on startup so misconfiguration fails fast.
    get_settings()
    yield


app = FastAPI(title="AI Voice Agent", version="1.0.0", lifespan=lifespan)
app.include_router(voice_router)
app.include_router(auth_router)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}
