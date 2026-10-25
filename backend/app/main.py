import asyncio
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import auth_router
from app.api.admin import admin_router
from app.api.routes import api_router
from app.core.security import authenticate_request
from app.core.config import settings
from app.db import get_db
from app.services.rate_limit import enforce_authenticated_rate_limit

app = FastAPI(
    title="AI Test Case Generator API",
    description="Backend API for enterprise AI-powered test case generation",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.auth_allowed_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(
    api_router,
    prefix="/api/v1",
    dependencies=[Depends(authenticate_request), Depends(enforce_authenticated_rate_limit)],
)
app.include_router(
    admin_router,
    prefix="/api/v1",
    dependencies=[Depends(authenticate_request), Depends(enforce_authenticated_rate_limit)],
)


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}


@app.get("/health/live", tags=["Health"])
async def liveness_check() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/health/ready", tags=["Health"])
async def readiness_check(db: AsyncSession = Depends(get_db)):
    attempts = max(1, settings.database_health_attempts)
    last_error = None
    for attempt in range(attempts):
        try:
            await db.execute(text("SELECT 1"))
            return {"status": "ready", "database": "healthy"}
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                await asyncio.sleep(max(0, settings.database_health_backoff_seconds))
    return JSONResponse(status_code=503, content={"status": "not_ready", "database": "unavailable", "retryable": True})
