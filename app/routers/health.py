from fastapi import APIRouter
from sqlalchemy import text

from app.config import settings
from app.db.session import AsyncSessionLocal

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    db_status = "disconnected"
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            db_status = "connected"
    except Exception:
        pass

    return {
        "status": "ok" if db_status == "connected" else "degraded",
        "version": "1.0.0",
        "db": db_status,
        "maintenance_mode": settings.maintenance_mode,
    }


@router.get("/ping")
async def ping():
    return "pong"
