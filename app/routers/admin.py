"""
Painel administrativo — /admin

Autenticação própria, separada do painel do paciente:
  - Senha via ADMIN_PASSWORD (env var)
  - JWT com type='admin', TTL=2h, cookie httpOnly 'admin_session'
  - Toda ação registrada em admin_logs (tabela criada via DDL em main.py)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Cookie, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_db
from app.models.meal_log import MealLog
from app.models.user import User
from app.models.water_log import WaterLog

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

_ADMIN_COOKIE = "admin_session"
_ADMIN_TTL_H  = 2
_ALGORITHM    = "HS256"


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _issue_admin_token() -> str:
    payload = {
        "sub": "admin",
        "type": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=_ADMIN_TTL_H),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


def _verify_admin_token(token: str | None) -> bool:
    if not token:
        return False
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[_ALGORITHM])
        return payload.get("type") == "admin"
    except (JWTError, Exception):
        return False


def _set_admin_cookie(response, token: str) -> None:
    response.set_cookie(
        key=_ADMIN_COOKIE,
        value=token,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        max_age=_ADMIN_TTL_H * 3600,
        path="/admin",
    )


async def _require_admin_api(admin_session: str | None = Cookie(default=None)) -> None:
    """Dependência para rotas JSON — retorna 403 se não autenticado."""
    if not _verify_admin_token(admin_session):
        raise HTTPException(403, "Não autorizado")


async def _log_action(db: AsyncSession, action: str, target_user_id=None, detail: dict | None = None) -> None:
    """Registra ação admin na tabela admin_logs."""
    try:
        detail_json = detail or {}
        await db.execute(
            text(
                "INSERT INTO admin_logs (action, target_user_id, detail) "
                "VALUES (:action, :uid, :detail::jsonb)"
            ),
            {"action": action, "uid": str(target_user_id) if target_user_id else None,
             "detail": str(detail_json).replace("'", '"')},
        )
        await db.commit()
    except Exception as exc:
        logger.warning("[Admin] falha ao registrar log: %s", exc)


# ── Importação tardia para evitar circular ────────────────────────────────────
from fastapi import HTTPException  # noqa: E402 — após definição acima que o usa


# ── Login / Logout ─────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
async def admin_login_page(
    request: Request,
    admin_session: str | None = Cookie(default=None),
):
    if _verify_admin_token(admin_session):
        return RedirectResponse("/admin", 302)
    return templates.TemplateResponse("admin_login.html", {
        "request": request,
        "error": None,
    })


@router.post("/login")
async def admin_login(
    request: Request,
    password: str = Form(...),
):
    # Valida senha
    expected = settings.admin_password
    if not expected:
        return templates.TemplateResponse("admin_login.html", {
            "request": request,
            "error": "ADMIN_PASSWORD não configurado no servidor.",
        }, status_code=500)

    if password != expected:
        logger.warning("[Admin] tentativa de login com senha inválida (IP: %s)", request.client.host if request.client else "?")
        return templates.TemplateResponse("admin_login.html", {
            "request": request,
            "error": "Senha incorreta.",
        }, status_code=401)

    token = _issue_admin_token()
    response = RedirectResponse("/admin", status_code=302)
    _set_admin_cookie(response, token)
    logger.info("[Admin] login bem-sucedido (IP: %s)", request.client.host if request.client else "?")
    return response


@router.post("/logout")
async def admin_logout():
    response = RedirectResponse("/admin/login", status_code=302)
    response.delete_cookie(_ADMIN_COOKIE, path="/admin")
    return response


# ── Dashboard ──────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    admin_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    if not _verify_admin_token(admin_session):
        return RedirectResponse("/admin/login", 302)

    seven_ago = datetime.now(timezone.utc) - timedelta(days=7)

    # ── Totais gerais ──
    total_users = (await db.execute(
        select(func.count()).select_from(User).where(User.deleted_at.is_(None))
    )).scalar() or 0

    # Distribuição por plano
    rows_plan = (await db.execute(
        select(User.plan, func.count().label("n"))
        .where(User.deleted_at.is_(None))
        .group_by(User.plan)
    )).all()
    by_plan = {r.plan: r.n for r in rows_plan}

    # Distribuição por canal
    rows_ch = (await db.execute(
        select(User.channel_type, func.count().label("n"))
        .where(User.deleted_at.is_(None))
        .group_by(User.channel_type)
    )).all()
    by_channel = {r.channel_type: r.n for r in rows_ch}

    # Novos últimos 7 dias
    new_7d = (await db.execute(
        select(func.count()).select_from(User)
        .where(User.created_at > seven_ago, User.deleted_at.is_(None))
    )).scalar() or 0

    # Ativos últimos 7 dias (registraram ao menos uma refeição)
    active_7d = (await db.execute(
        select(func.count(MealLog.user_id.distinct()))
        .where(MealLog.logged_at > seven_ago)
    )).scalar() or 0

    # Total refeições registradas
    total_meals = (await db.execute(
        select(func.count()).select_from(MealLog)
    )).scalar() or 0

    # Total registros de água
    total_water = (await db.execute(
        select(func.count()).select_from(WaterLog)
    )).scalar() or 0

    # ── Scheduler ──
    scheduler = getattr(request.app.state, "scheduler", None)
    scheduler_running = bool(scheduler and scheduler.running)
    jobs: list[dict] = []
    if scheduler_running:
        from zoneinfo import ZoneInfo
        SP = ZoneInfo("America/Sao_Paulo")
        for j in scheduler.get_jobs():
            nxt = (j.next_run_time.astimezone(SP).strftime("%d/%m %H:%M")
                   if j.next_run_time else "—")
            jobs.append({"id": j.id, "name": j.name, "next": nxt})

    # ── Últimos 5 usuários cadastrados ──
    recent_users = (await db.execute(
        select(User).where(User.deleted_at.is_(None))
        .order_by(User.created_at.desc()).limit(5)
    )).scalars().all()

    return templates.TemplateResponse("admin_dashboard.html", {
        "request": request,
        "total_users": total_users,
        "by_plan": by_plan,
        "by_channel": by_channel,
        "new_7d": new_7d,
        "active_7d": active_7d,
        "total_meals": total_meals,
        "total_water": total_water,
        "scheduler_running": scheduler_running,
        "jobs": jobs,
        "recent_users": recent_users,
        "now": datetime.now(timezone.utc),
    })


# ── Lista de Usuários ──────────────────────────────────────────────────────────

@router.get("/usuarios", response_class=HTMLResponse)
async def admin_usuarios(
    request: Request,
    q: str = "",
    plan: str = "",
    page: int = 1,
    admin_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    if not _verify_admin_token(admin_session):
        return RedirectResponse("/admin/login", 302)

    per_page = 50
    offset = (page - 1) * per_page

    base_q = select(User).where(User.deleted_at.is_(None))
    if q:
        like = f"%{q}%"
        base_q = base_q.where(
            User.first_name.ilike(like) |
            User.channel_id.ilike(like) |
            User.email.ilike(like)
        )
    if plan:
        base_q = base_q.where(User.plan == plan)

    total = (await db.execute(
        select(func.count()).select_from(base_q.subquery())
    )).scalar() or 0

    users = (await db.execute(
        base_q.order_by(User.created_at.desc()).offset(offset).limit(per_page)
    )).scalars().all()

    total_pages = max(1, (total + per_page - 1) // per_page)

    return templates.TemplateResponse("admin_usuarios.html", {
        "request": request,
        "users": users,
        "total": total,
        "q": q,
        "plan_filter": plan,
        "page": page,
        "total_pages": total_pages,
        "per_page": per_page,
    })


# ── Detalhe do Usuário ────────────────────────────────────────────────────────

@router.get("/usuarios/{user_id}", response_class=HTMLResponse)
async def admin_usuario_detalhe(
    request: Request,
    user_id: str,
    admin_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    if not _verify_admin_token(admin_session):
        return RedirectResponse("/admin/login", 302)

    import uuid as _uuid
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(404, "ID inválido")

    user = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "Usuário não encontrado")

    # Estatísticas do usuário
    meal_count = (await db.execute(
        select(func.count()).select_from(MealLog).where(MealLog.user_id == uid)
    )).scalar() or 0

    water_count = (await db.execute(
        select(func.count()).select_from(WaterLog).where(WaterLog.user_id == uid)
    )).scalar() or 0

    last_meal = (await db.execute(
        select(MealLog.logged_at).where(MealLog.user_id == uid)
        .order_by(MealLog.logged_at.desc()).limit(1)
    )).scalar()

    return templates.TemplateResponse("admin_usuario.html", {
        "request": request,
        "u": user,
        "meal_count": meal_count,
        "water_count": water_count,
        "last_meal": last_meal,
    })


# ── API JSON: ações sobre usuários ───────────────────────────────────────────

@router.post("/api/usuarios/{user_id}/plano")
async def admin_change_plan(
    user_id: str,
    new_plan: str = Form(...),
    expires_days: int | None = Form(default=None),
    admin_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    if not _verify_admin_token(admin_session):
        raise HTTPException(403, "Não autorizado")

    import uuid as _uuid
    if new_plan not in ("free", "premium", "nutritionist"):
        raise HTTPException(422, "Plano inválido")

    user = (await db.execute(
        select(User).where(User.id == _uuid.UUID(user_id))
    )).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "Usuário não encontrado")

    old_plan = user.plan
    user.plan = new_plan
    user.plan_expires_at = (
        datetime.now(timezone.utc) + timedelta(days=expires_days)
        if expires_days else None
    )
    await db.commit()

    await _log_action(db, "change_plan", user.id,
                      {"old": old_plan, "new": new_plan, "expires_days": expires_days})
    logger.info("[Admin] plano %s → %s para user %s", old_plan, new_plan, user.channel_id)
    return JSONResponse({"ok": True, "plan": new_plan})


@router.post("/api/usuarios/{user_id}/limpar-estado")
async def admin_clear_state(
    user_id: str,
    admin_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    if not _verify_admin_token(admin_session):
        raise HTTPException(403, "Não autorizado")

    import uuid as _uuid
    user = (await db.execute(
        select(User).where(User.id == _uuid.UUID(user_id))
    )).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "Usuário não encontrado")

    old_state = user.conversation_state
    user.conversation_state = "IDLE"
    user.state_data = None
    user.state_expires_at = None
    await db.commit()

    # Limpa também o estado em memória do ConversationService
    try:
        from app.services.conversation import conversation_service
        conversation_service._conv_state.pop(user.channel_id, None)
    except Exception as exc:
        logger.warning("[Admin] falha ao limpar estado em memória: %s", exc)

    await _log_action(db, "clear_state", user.id, {"old_state": old_state})
    logger.info("[Admin] estado %s → IDLE para user %s", old_state, user.channel_id)
    return JSONResponse({"ok": True, "old_state": old_state})


@router.post("/api/usuarios/{user_id}/deletar")
async def admin_delete_user(
    user_id: str,
    confirm: str = Form(default=""),
    admin_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Anonimização LGPD: marca deleted_at, apaga PII e dados sensíveis."""
    if not _verify_admin_token(admin_session):
        raise HTTPException(403, "Não autorizado")
    if confirm != "CONFIRMAR":
        raise HTTPException(422, "Confirmação inválida — envie confirm=CONFIRMAR")

    import uuid as _uuid
    user = (await db.execute(
        select(User).where(User.id == _uuid.UUID(user_id))
    )).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "Usuário não encontrado")

    now = datetime.now(timezone.utc)
    channel_id = user.channel_id

    # Anonimização conforme Art. 18 LGPD — 72h
    user.deleted_at = now
    user.first_name = None
    user.email = None
    user.password_hash = None
    user.state_data = None
    user.lgpd_consent_at = None

    # Apaga refeições brutas (dados sensíveis de saúde)
    await db.execute(
        text("DELETE FROM meal_logs WHERE user_id = :uid"),
        {"uid": str(user.id)},
    )
    await db.execute(
        text("DELETE FROM water_logs WHERE user_id = :uid"),
        {"uid": str(user.id)},
    )
    await db.commit()

    # Limpa estado em memória
    try:
        from app.services.conversation import conversation_service
        conversation_service._conv_state.pop(channel_id, None)
    except Exception:
        pass

    await _log_action(db, "delete_user_lgpd", user.id, {"channel_id": channel_id})
    logger.warning("[Admin] usuário %s anonimizado (LGPD)", channel_id)
    return JSONResponse({"ok": True, "message": "Usuário anonimizado com sucesso."})


# ── API JSON: Scheduler ────────────────────────────────────────────────────────

@router.post("/api/scheduler/trigger/{job_id}")
async def admin_trigger_job(
    request: Request,
    job_id: str,
    admin_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    if not _verify_admin_token(admin_session):
        raise HTTPException(403, "Não autorizado")

    scheduler = getattr(request.app.state, "scheduler", None)
    if not scheduler or not scheduler.running:
        raise HTTPException(503, "Scheduler não está rodando")

    job = scheduler.get_job(job_id)
    if not job:
        valid = [j.id for j in scheduler.get_jobs()]
        raise HTTPException(404, f"Job '{job_id}' não encontrado. Válidos: {valid}")

    from zoneinfo import ZoneInfo
    job.modify(next_run_time=datetime.now(ZoneInfo("America/Sao_Paulo")))
    await _log_action(db, "trigger_job", None, {"job_id": job_id})
    logger.info("[Admin] job '%s' acionado manualmente", job_id)
    return JSONResponse({"ok": True, "triggered": job_id})
