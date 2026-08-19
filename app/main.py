import logging
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from sentry_sdk.integrations.fastapi import FastApiIntegration

from app.config import settings

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────
    if settings.sentry_dsn and "..." not in settings.sentry_dsn:
        try:
            sentry_sdk.init(dsn=settings.sentry_dsn, integrations=[FastApiIntegration()])
            logger.info("Sentry inicializado")
        except Exception as e:
            logger.warning(f"Sentry DSN inválido, monitoramento desabilitado: {e}")

    from app.services.nutrition import nutrition_service
    nutrition_service.load_data()
    logger.info("Base nutricional carregada em memória")

    from app.services.scheduler import start_scheduler
    scheduler = await start_scheduler()
    app.state.scheduler = scheduler  # expõe para o /health e /scheduler/status
    logger.info("Scheduler iniciado")

    yield

    # ── Shutdown ─────────────────────────────────────────────
    scheduler.shutdown(wait=False)
    logger.info("Scheduler encerrado")


app = FastAPI(
    title="NutriBot API",
    version="1.0.0",
    docs_url="/docs" if settings.app_env != "production" else None,
    lifespan=lifespan,
)

from app.routers import (  # noqa: E402
    auth,
    dashboard,
    health,
    meals,
    reports,
    users,
    webhook_payment,
    webhook_telegram,
    webhook_whatsapp,
)

# ── Webhooks + saúde ──
app.include_router(health.router)
app.include_router(webhook_telegram.router)
app.include_router(webhook_whatsapp.router)
app.include_router(webhook_payment.router)

# ── API REST ──
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(meals.router)
app.include_router(reports.router)

# ── Plataforma web (Jinja2) ──
app.include_router(dashboard.router)
