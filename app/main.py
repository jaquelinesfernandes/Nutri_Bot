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
    """Sliding-expiration de sessão: renova o cookie quando restar ≤ RENEW_DAYS.

    Estratégia:
    - Cookie e JWT têm duração de jwt_expire_days (padrão: 365 dias).
    - O middleware SÓ emite novo token quando restam ≤ RENEW_DAYS dias
      (padrão: 30 dias), evitando Set-Cookie desnecessário em toda visita.
    - Resultado: usuário que abre o painel ao menos uma vez a cada ~335 dias
      nunca precisa fazer login novamente.
    - Rotas de API, webhook e static são ignoradas.
    """

    RENEW_DAYS = 30  # renova quando restar ≤ 30 dias de vida no token

    _SKIP_PREFIXES = (
        "/api/", "/webhook/", "/static/",
        "/health", "/ping", "/scheduler/",
        "/docs", "/redoc", "/openapi",
    )

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        path = request.url.path
        if any(path.startswith(p) for p in self._SKIP_PREFIXES):
            return response

        token = request.cookies.get("access_token")
        if not token:
            return response

        try:
            import uuid
            from datetime import datetime, timezone

            from jose import JWTError
            from jose import jwt as _jwt

            payload = _jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
            exp = payload.get("exp", 0)
            sub = payload.get("sub")
            if not sub:
                return response

            remaining = exp - datetime.now(timezone.utc).timestamp()
            # Ainda tem tempo de sobra — não renova agora
            if remaining > self.RENEW_DAYS * 86_400:
                return response

            # Perto de expirar (≤ 30 dias) — emite novo JWT com prazo cheio
            from app.utils.jwt import create_access_token
            new_token = create_access_token(uuid.UUID(sub))
            response.set_cookie(
                key="access_token",
                value=new_token,
                httponly=True,
                secure=settings.app_env == "production",
                samesite="lax",
                max_age=settings.jwt_expire_days * 86_400,
                path="/",
            )
        except Exception:
            pass  # token inválido/expirado já — não renova

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
