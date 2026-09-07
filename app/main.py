import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes.admin import router as admin_router
from app.api.routes.public import router as public_router
from app.api.routes.voice import router as voice_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db import init_db
from app.services.reminders import reminder_loop

configure_logging()

_STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate settings eagerly on startup so misconfiguration fails fast.
    settings = get_settings()
    init_db()
    reminder_task = asyncio.create_task(reminder_loop(settings))
    try:
        yield
    finally:
        reminder_task.cancel()
        await asyncio.gather(reminder_task, return_exceptions=True)


app = FastAPI(title="AI Voice Agent", version="2.0.0", lifespan=lifespan)
app.include_router(voice_router)
app.include_router(admin_router)
app.include_router(public_router)
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/")
async def index() -> RedirectResponse:
    return RedirectResponse(url="/admin")


@app.get("/admin")
async def admin_dashboard() -> FileResponse:
    return FileResponse(_STATIC_DIR / "admin" / "index.html")


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}
