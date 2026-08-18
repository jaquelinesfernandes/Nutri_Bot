from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from sqlalchemy import text

from app.config import settings
from app.db.session import AsyncSessionLocal

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request):
    # ── DB ────────────────────────────────────────────────────
    db_status = "disconnected"
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            db_status = "connected"
    except Exception:
        pass

    # ── Scheduler ────────────────────────────────────────────
    scheduler = getattr(request.app.state, "scheduler", None)
    scheduler_status = "running" if (scheduler and scheduler.running) else "not_started"

    return {
        "status": "ok" if db_status == "connected" else "degraded",
        "version": "1.0.0",
        "db": db_status,
        "scheduler": scheduler_status,
        "maintenance_mode": settings.maintenance_mode,
    }


@router.get("/ping")
async def ping():
    return "pong"


@router.get("/scheduler/status")
async def scheduler_status(request: Request):
    """
    Mostra o próximo disparo de cada job agendado (horário de Brasília).
    Útil para confirmar que o timezone está correto após deploy.
    """
    scheduler = getattr(request.app.state, "scheduler", None)
    if not scheduler or not scheduler.running:
        return {"running": False, "jobs": []}

    SP_TZ = ZoneInfo("America/Sao_Paulo")
    now_brt = datetime.now(SP_TZ)

    jobs = []
    for job in scheduler.get_jobs():
        next_run_utc = job.next_run_time  # APScheduler retorna timezone-aware
        if next_run_utc:
            next_run_brt = next_run_utc.astimezone(SP_TZ)
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run_brt": next_run_brt.strftime("%Y-%m-%d %H:%M:%S %Z"),
                "next_run_utc": next_run_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
                "in_minutes": round((next_run_utc - datetime.now(SP_TZ)).total_seconds() / 60),
            })
        else:
            jobs.append({"id": job.id, "name": job.name, "next_run_brt": None})

    return {
        "running": True,
        "now_brt": now_brt.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "jobs": sorted(jobs, key=lambda j: j.get("next_run_brt") or ""),
    }
