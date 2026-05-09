from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text

from ..config import get_settings
from ..core.logging_config import setup_logging
from ..core.rate_limit import limiter, too_many_requests_handler
from ..db.base import get_engine
from .v1 import admin as admin_router
from .v1 import auth as auth_router
from .v1 import credentials as credentials_router
from .v1 import exams as exams_router
from .v1 import files as files_router
from .v1 import grades as grades_router
from .v1 import push as push_router
from .v1 import schedule as schedule_router
from .v1 import session as session_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging("api")
    settings = get_settings()
    app.state.redis = redis.from_url(settings.redis_url, decode_responses=True)
    app.state.engine = get_engine()
    try:
        yield
    finally:
        await app.state.redis.aclose()
        await app.state.engine.dispose()


app = FastAPI(title="UNEC Cabinet API", version="0.1.0", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, too_many_requests_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router, prefix="/v1")
app.include_router(credentials_router.router, prefix="/v1")
app.include_router(session_router.router, prefix="/v1")
app.include_router(schedule_router.router, prefix="/v1")
app.include_router(grades_router.router, prefix="/v1")
app.include_router(exams_router.router, prefix="/v1")
app.include_router(files_router.router, prefix="/v1")
app.include_router(push_router.router, prefix="/v1")
app.include_router(admin_router.router, prefix="/v1")


logger = logging.getLogger(__name__)


@app.get("/health")
async def health() -> dict:
    """Public liveness probe.

    Returns only boolean health flags — never echoes exception details
    or connection strings, since this endpoint is reachable from the
    public internet.
    """
    db_ok = False
    redis_ok = False
    db_error: str | None = None
    redis_error: str | None = None

    try:
        async with app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:  # noqa: BLE001
        db_error = "unavailable"
        logger.exception("health: db check failed")
        del exc

    try:
        await app.state.redis.ping()
        redis_ok = True
    except Exception as exc:  # noqa: BLE001
        redis_error = "unavailable"
        logger.exception("health: redis check failed")
        del exc

    return {
        "status": "ok" if db_ok and redis_ok else "degraded",
        "db": {"ok": db_ok, "error": db_error},
        "redis": {"ok": redis_ok, "error": redis_error},
    }
