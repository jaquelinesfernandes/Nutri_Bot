"""
Painel administrativo — /admin

Autenticação própria, separada do painel do paciente:
  - Senha via ADMIN_PASSWORD (env var)
  - JWT com type='admin', TTL=2h, cookie httpOnly 'admin_session'
  - Toda ação registrada em admin_logs (tabela criada via DDL em main.py)
"""
from __future__ import annotations

import csv
import io
import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Cookie, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_db
from app.models.meal_log import MealLog
from app.models.payment_subscription import PaymentSubscription
from app.models.user import User
from app.models.water_log import WaterLog

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

_ADMIN_COOKIE = "admin_session"
_ADMIN_TTL_H  = 2
_ALGORITHM    = "HS256"

# ── Rate limiter para login ────────────────────────────────────────────────────
_login_attempts: dict[str, list[float]] = defaultdict(list)
_LOGIN_MAX    = 5
_LOGIN_WINDOW = 300  # segundos


def _check_rate_limit(ip: str) -> tuple[bool, int]:
    """Retorna (permitido, segundos_de_espera)."""
    now = time.time()
    recent = [t for t in _login_attempts[ip] if now - t < _LOGIN_WINDOW]
    _login_attempts[ip] = recent
    if len(recent) >= _LOGIN_MAX:
        wait = int(_LOGIN_WINDOW - (now - min(recent))) + 1
        return False, wait
    _login_attempts[ip].append(now)
    return True, 0


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


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "?"


async def _log_action(
    db: AsyncSession,
    action: str,
    target_user_id=None,
    detail: dict | None = None,
    *,
    ip: str | None = None,
) -> None:
    """Registra ação admin na tabela admin_logs."""
    try:
        import json
        detail_full = dict(detail or {})
        if ip:
            detail_full["ip"] = ip
        await db.execute(
            text(
                "INSERT INTO admin_logs (action, target_user_id, detail) "
                "VALUES (:action, :uid, :detail::jsonb)"
            ),
            {
                "action": action,
                "uid": str(target_user_id) if target_user_id else None,
                "detail": json.dumps(detail_full),
            },
        )
        await db.commit()
    except Exception as exc:
        logger.warning("[Admin] falha ao registrar log: %s", exc)


# ── Login / Logout ─────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
async def admin_login_page(
    request: Request,
    admin_session: str | None = Cookie(default=None),
):
    if _verify_admin_token(admin_session):
        return RedirectResponse("/admin", 302)
    # Cookie existe mas é inválido = sessão expirou
    expired = admin_session is not None
    return templates.TemplateResponse(
        request=request, name="admin_login.html",
        context={"error": "Sua sessão expirou. Faça login novamente." if expired else None},
    )


@router.post("/login")
async def admin_login(
    request: Request,
    password: str = Form(...),
):
    ip = _client_ip(request)

    # ── Rate limit ──
    allowed, wait = _check_rate_limit(ip)
    if not allowed:
        return templates.TemplateResponse(
            request=request, name="admin_login.html",
            context={"error": f"Muitas tentativas. Aguarde {wait}s."},
            status_code=429,
        )

    # ── Valida senha ──
    expected = settings.admin_password
    if not expected:
        return templates.TemplateResponse(
            request=request, name="admin_login.html",
            context={"error": "ADMIN_PASSWORD não configurado no servidor."},
            status_code=500,
        )

    if password != expected:
        logger.warning("[Admin] login inválido — IP: %s", ip)
        return templates.TemplateResponse(
            request=request, name="admin_login.html",
            context={"error": "Senha incorreta."},
            status_code=401,
        )

    token = _issue_admin_token()
    response = RedirectResponse("/admin", status_code=302)
    _set_admin_cookie(response, token)
    logger.info("[Admin] login bem-sucedido — IP: %s", ip)
    # Log assíncrono (sem db aqui — POST /login não injeta db por design)
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

    now_utc = datetime.now(timezone.utc)
    seven_ago  = now_utc - timedelta(days=7)
    thirty_ago = now_utc - timedelta(days=30)

    # ── Totais gerais ──
    total_users = (await db.execute(
        select(func.count()).select_from(User).where(User.deleted_at.is_(None))
    )).scalar() or 0

    rows_plan = (await db.execute(
        select(User.plan, func.count().label("n"))
        .where(User.deleted_at.is_(None))
        .group_by(User.plan)
    )).all()
    by_plan = {r.plan: r.n for r in rows_plan}

    rows_ch = (await db.execute(
        select(User.channel_type, func.count().label("n"))
        .where(User.deleted_at.is_(None))
        .group_by(User.channel_type)
    )).all()
    by_channel = {r.channel_type: r.n for r in rows_ch}

    new_7d = (await db.execute(
        select(func.count()).select_from(User)
        .where(User.created_at > seven_ago, User.deleted_at.is_(None))
    )).scalar() or 0

    active_7d = (await db.execute(
        select(func.count(MealLog.user_id.distinct()))
        .where(MealLog.logged_at > seven_ago)
    )).scalar() or 0

    total_meals = (await db.execute(
        select(func.count()).select_from(MealLog)
    )).scalar() or 0

    total_water = (await db.execute(
        select(func.count()).select_from(WaterLog)
    )).scalar() or 0

    # ── Assinaturas ──
    subs_active = (await db.execute(
        select(func.count()).select_from(PaymentSubscription)
        .where(PaymentSubscription.status == "active")
    )).scalar() or 0

    subs_past_due = (await db.execute(
        select(func.count()).select_from(PaymentSubscription)
        .where(PaymentSubscription.status == "past_due")
    )).scalar() or 0

    subs_canceled_30d = (await db.execute(
        select(func.count()).select_from(PaymentSubscription)
        .where(
            PaymentSubscription.status == "canceled",
            PaymentSubscription.canceled_at.isnot(None),
            PaymentSubscription.canceled_at > thirty_ago,
        )
    )).scalar() or 0

    # Planos expirados mas não revertidos para free (indica falha no webhook)
    plans_expired_stale = (await db.execute(
        select(func.count()).select_from(User)
        .where(
            User.deleted_at.is_(None),
            User.plan != "free",
            User.plan_expires_at.isnot(None),
            User.plan_expires_at < now_utc,
        )
    )).scalar() or 0

    # Expiram em até 7 dias (atenção proativa)
    expires_7d = (await db.execute(
        select(func.count()).select_from(User)
        .where(
            User.deleted_at.is_(None),
            User.plan != "free",
            User.plan_expires_at.isnot(None),
            User.plan_expires_at > now_utc,
            User.plan_expires_at < now_utc + timedelta(days=7),
        )
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

    recent_users = (await db.execute(
        select(User).where(User.deleted_at.is_(None))
        .order_by(User.created_at.desc()).limit(5)
    )).scalars().all()

    return templates.TemplateResponse(
        request=request, name="admin_dashboard.html",
        context={
            "total_users": total_users,
            "by_plan": by_plan,
            "by_channel": by_channel,
            "new_7d": new_7d,
            "active_7d": active_7d,
            "total_meals": total_meals,
            "total_water": total_water,
            "subs_active": subs_active,
            "subs_past_due": subs_past_due,
            "subs_canceled_30d": subs_canceled_30d,
            "plans_expired_stale": plans_expired_stale,
            "expires_7d": expires_7d,
            "scheduler_running": scheduler_running,
            "jobs": jobs,
            "recent_users": recent_users,
            "now": now_utc,
        },
    )


# ── Lista de Usuários ──────────────────────────────────────────────────────────

@router.get("/usuarios", response_class=HTMLResponse)
async def admin_usuarios(
    request: Request,
    q: str = "",
    plan: str = "",
    expires_in: int = 0,   # 0=todos, 7=expira em 7d, 30=expira em 30d
    include_deleted: int = 0,
    page: int = 1,
    admin_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    if not _verify_admin_token(admin_session):
        return RedirectResponse("/admin/login", 302)

    per_page = 50
    offset = (page - 1) * per_page
    now_utc = datetime.now(timezone.utc)

    base_q = select(User)
    if not include_deleted:
        base_q = base_q.where(User.deleted_at.is_(None))
    if q:
        like = f"%{q}%"
        base_q = base_q.where(
            User.first_name.ilike(like) |
            User.channel_id.ilike(like) |
            User.email.ilike(like)
        )
    if plan:
        base_q = base_q.where(User.plan == plan)
    if expires_in:
        base_q = base_q.where(
            User.plan_expires_at.isnot(None),
            User.plan_expires_at > now_utc,
            User.plan_expires_at < now_utc + timedelta(days=expires_in),
        )

    total = (await db.execute(
        select(func.count()).select_from(base_q.subquery())
    )).scalar() or 0

    users = (await db.execute(
        base_q.order_by(User.created_at.desc()).offset(offset).limit(per_page)
    )).scalars().all()

    total_pages = max(1, (total + per_page - 1) // per_page)

    return templates.TemplateResponse(
        request=request, name="admin_usuarios.html",
        context={
            "users": users,
            "total": total,
            "q": q,
            "plan_filter": plan,
            "expires_in": expires_in,
            "include_deleted": include_deleted,
            "page": page,
            "total_pages": total_pages,
            "per_page": per_page,
            "now_utc": now_utc,
        },
    )


# ── Export CSV ────────────────────────────────────────────────────────────────
# ATENÇÃO: deve ficar ANTES de /usuarios/{user_id} para não ser capturado

@router.get("/usuarios/export.csv")
async def admin_export_users(
    admin_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    if not _verify_admin_token(admin_session):
        raise HTTPException(403, "Não autorizado")

    users = (await db.execute(
        select(User).where(User.deleted_at.is_(None))
        .order_by(User.created_at.desc())
    )).scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "id", "nome", "email", "canal", "channel_id", "plano",
        "plan_expires_at", "cadastro", "ultimo_acesso",
        "onboarding", "alertas", "meta_kcal", "meta_agua_ml",
    ])
    for u in users:
        writer.writerow([
            str(u.id),
            u.first_name or "",
            u.email or "",
            u.channel_type,
            u.channel_id,
            u.plan,
            u.plan_expires_at.strftime("%Y-%m-%d") if u.plan_expires_at else "",
            u.created_at.strftime("%Y-%m-%d %H:%M") if u.created_at else "",
            u.last_active_at.strftime("%Y-%m-%d %H:%M") if u.last_active_at else "",
            "sim" if u.onboarding_complete else "não",
            "sim" if u.alerts_enabled else "não",
            u.daily_calorie_goal or "",
            u.daily_water_goal_ml or "",
        ])

    # BOM UTF-8 para abrir corretamente no Excel
    csv_bytes = "﻿".encode("utf-8") + buf.getvalue().encode("utf-8")
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=usuarios.csv"},
    )


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

    # ── Estatísticas ──
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

    # ── Histórico de assinaturas ──
    subscriptions = (await db.execute(
        select(PaymentSubscription)
        .where(PaymentSubscription.user_id == uid)
        .order_by(PaymentSubscription.created_at.desc())
    )).scalars().all()

    # ── Histórico de alterações de plano (admin_logs) ──
    plan_history = (await db.execute(
        text(
            "SELECT created_at, detail FROM admin_logs "
            "WHERE target_user_id = :uid AND action = 'change_plan' "
            "ORDER BY created_at DESC LIMIT 20"
        ),
        {"uid": str(uid)},
    )).mappings().all()

    return templates.TemplateResponse(
        request=request, name="admin_usuario.html",
        context={
            "u": user,
            "meal_count": meal_count,
            "water_count": water_count,
            "last_meal": last_meal,
            "subscriptions": subscriptions,
            "plan_history": plan_history,
        },
    )


# ── Lista de Assinaturas ──────────────────────────────────────────────────────

@router.get("/assinaturas", response_class=HTMLResponse)
async def admin_assinaturas(
    request: Request,
    status: str = "",
    page: int = 1,
    admin_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    if not _verify_admin_token(admin_session):
        return RedirectResponse("/admin/login", 302)

    per_page = 50
    offset = (page - 1) * per_page

    base_q = (
        select(PaymentSubscription, User)
        .join(User, PaymentSubscription.user_id == User.id)
    )
    if status:
        base_q = base_q.where(PaymentSubscription.status == status)

    total = (await db.execute(
        select(func.count()).select_from(base_q.subquery())
    )).scalar() or 0

    rows = (await db.execute(
        base_q.order_by(PaymentSubscription.created_at.desc())
        .offset(offset).limit(per_page)
    )).all()

    # Contadores por status para os tiles
    stats: dict[str, int] = {}
    for s in ("active", "past_due", "canceled"):
        stats[s] = (await db.execute(
            select(func.count()).select_from(PaymentSubscription)
            .where(PaymentSubscription.status == s)
        )).scalar() or 0

    total_pages = max(1, (total + per_page - 1) // per_page)

    return templates.TemplateResponse(
        request=request, name="admin_assinaturas.html",
        context={
            "rows": rows,
            "total": total,
            "status_filter": status,
            "stats": stats,
            "page": page,
            "total_pages": total_pages,
            "per_page": per_page,
        },
    )


# ── API JSON: ações sobre usuários ───────────────────────────────────────────

@router.post("/api/usuarios/{user_id}/plano")
async def admin_change_plan(
    request: Request,
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
                      {"old": old_plan, "new": new_plan, "expires_days": expires_days},
                      ip=_client_ip(request))
    logger.info("[Admin] plano %s → %s para user %s", old_plan, new_plan, user.channel_id)
    return JSONResponse({"ok": True, "plan": new_plan})


@router.post("/api/usuarios/{user_id}/limpar-estado")
async def admin_clear_state(
    request: Request,
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

    try:
        from app.services.conversation import conversation_service
        conversation_service._conv_state.pop(user.channel_id, None)
    except Exception as exc:
        logger.warning("[Admin] falha ao limpar estado em memória: %s", exc)

    await _log_action(db, "clear_state", user.id, {"old_state": old_state},
                      ip=_client_ip(request))
    logger.info("[Admin] estado %s → IDLE para user %s", old_state, user.channel_id)
    return JSONResponse({"ok": True, "old_state": old_state})


@router.post("/api/usuarios/{user_id}/deletar")
async def admin_delete_user(
    request: Request,
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

    user.deleted_at = now
    user.first_name = None
    user.email = None
    user.password_hash = None
    user.state_data = None
    user.lgpd_consent_at = None

    await db.execute(text("DELETE FROM meal_logs WHERE user_id = :uid"),   {"uid": str(user.id)})
    await db.execute(text("DELETE FROM water_logs WHERE user_id = :uid"),  {"uid": str(user.id)})
    await db.commit()

    try:
        from app.services.conversation import conversation_service
        conversation_service._conv_state.pop(channel_id, None)
    except Exception:
        pass

    await _log_action(db, "delete_user_lgpd", user.id,
                      {"channel_id": channel_id}, ip=_client_ip(request))
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
    await _log_action(db, "trigger_job", None, {"job_id": job_id}, ip=_client_ip(request))
    logger.info("[Admin] job '%s' acionado manualmente", job_id)
    return JSONResponse({"ok": True, "triggered": job_id})


# ── Health check visual ───────────────────────────────────────────────────────

@router.get("/health", response_class=HTMLResponse)
async def admin_health_page(
    request: Request,
    admin_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    if not _verify_admin_token(admin_session):
        return RedirectResponse("/admin/login", 302)

    import os as _os
    from zoneinfo import ZoneInfo

    db_ok = False
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    scheduler = getattr(request.app.state, "scheduler", None)
    scheduler_running = bool(scheduler and scheduler.running)
    SP = ZoneInfo("America/Sao_Paulo")
    jobs: list[dict] = []
    if scheduler_running:
        for j in scheduler.get_jobs():
            nxt = j.next_run_time
            jobs.append({
                "id": j.id,
                "name": j.name,
                "next": nxt.astimezone(SP).strftime("%d/%m %H:%M") if nxt else "—",
                "in_min": round((nxt - datetime.now(SP)).total_seconds() / 60) if nxt else None,
            })

    git_commit = _os.getenv("RENDER_GIT_COMMIT", "local")[:12]
    git_branch = _os.getenv("RENDER_GIT_BRANCH", "—")

    try:
        log_count = (await db.execute(text("SELECT COUNT(*) FROM admin_logs"))).scalar() or 0
    except Exception:
        log_count = "—"

    return templates.TemplateResponse(
        request=request, name="admin_health.html",
        context={
            "db_ok": db_ok,
            "scheduler_running": scheduler_running,
            "jobs": jobs,
            "git_commit": git_commit,
            "git_branch": git_branch,
            "log_count": log_count,
            "now": datetime.now(SP),
        },
    )


# ── Logs de auditoria ─────────────────────────────────────────────────────────

@router.get("/logs", response_class=HTMLResponse)
async def admin_logs_page(
    request: Request,
    page: int = 1,
    admin_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    if not _verify_admin_token(admin_session):
        return RedirectResponse("/admin/login", 302)

    per_page = 50
    offset = (page - 1) * per_page

    total = (await db.execute(text("SELECT COUNT(*) FROM admin_logs"))).scalar() or 0

    rows = (await db.execute(
        text(
            "SELECT id, created_at, action, target_user_id, detail "
            "FROM admin_logs ORDER BY created_at DESC LIMIT :lim OFFSET :off"
        ),
        {"lim": per_page, "off": offset},
    )).mappings().all()

    total_pages = max(1, (total + per_page - 1) // per_page)

    return templates.TemplateResponse(
        request=request, name="admin_logs.html",
        context={
            "rows": rows,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "per_page": per_page,
        },
    )
