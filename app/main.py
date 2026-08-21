import logging
from contextlib import asynccontextmanager
from pathlib import Path

import sentry_sdk
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from sentry_sdk.integrations.fastapi import FastApiIntegration
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adiciona headers de segurança HTTP em todas as respostas."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if settings.app_env == "production":
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


class SlidingSessionMiddleware(BaseHTTPMiddleware):
    """Renova o cookie de sessão a cada visita ao painel (sliding expiration).

    Rotas de API, webhook e static são ignoradas — só renova em páginas HTML
    do dashboard, garantindo que o usuário vinculado nunca seja deslogado
    enquanto usar o painel pelo menos uma vez no período de jwt_expire_days.
    """

    # Prefixos que NÃO devem acionar a renovação (não são páginas do painel)
    _SKIP_PREFIXES = (
        "/api/", "/webhook/", "/static/",
        "/health", "/ping", "/scheduler/",
        "/docs", "/redoc", "/openapi",
    )

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # Só renova em rotas de página HTML
        path = request.url.path
        if any(path.startswith(p) for p in self._SKIP_PREFIXES):
            return response

        token = request.cookies.get("access_token")
        if not token:
            return response

        from app.utils.jwt import create_access_token, decode_token

        user_id = decode_token(token)
        if user_id is None:
            return response  # token inválido/expirado — não renova

        # Emite novo JWT com expiração reiniciada a partir de agora
        new_token = create_access_token(user_id)
        response.set_cookie(
            key="access_token",
            value=new_token,
            httponly=True,
            secure=settings.app_env == "production",
            samesite="lax",
            max_age=settings.jwt_expire_days * 86_400,
            path="/",
        )
        return response


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
    redoc_url="/redoc" if settings.app_env != "production" else None,
    lifespan=lifespan,
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(SlidingSessionMiddleware)

# ── Arquivos estáticos (PWA: manifest, icons, sw.js) ──────────────────────
_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

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
