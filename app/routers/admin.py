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
from app.models.nutritionist_patient import NutritionistPatient
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
    db: AsyncSession = Depends(get_db),
):
    ip = _client_ip(request)

    # ── Rate limit ──
    allowed, wait = _check_rate_limit(ip)
    if not allowed:
        # ① Loga tentativas bloqueadas por rate-limit
        await _log_action(db, "login_blocked_rate_limit", None,
                          {"ip": ip, "wait_s": wait})
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
        # ① Loga senha incorreta em admin_logs
        await _log_action(db, "login_failed", None, {"ip": ip})
        logger.warning("[Admin] login inválido — IP: %s", ip)
        return templates.TemplateResponse(
            request=request, name="admin_login.html",
            context={"error": "Senha incorreta."},
            status_code=401,
        )

    # ① Loga login bem-sucedido
    await _log_action(db, "login_success", None, {"ip": ip})
    token = _issue_admin_token()
    response = RedirectResponse("/admin", status_code=302)
    _set_admin_cookie(response, token)
    logger.info("[Admin] login bem-sucedido — IP: %s", ip)
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

    # ③ Funil de onboarding
    onboarding_total = total_users
    onboarding_complete = (await db.execute(
        select(func.count()).select_from(User)
        .where(User.deleted_at.is_(None), User.onboarding_complete.is_(True))
    )).scalar() or 0
    onboarding_in_progress = (await db.execute(
        select(func.count()).select_from(User)
        .where(User.deleted_at.is_(None), User.onboarding_complete.is_(False),
               User.onboarding_step > 0)
    )).scalar() or 0
    onboarding_not_started = (await db.execute(
        select(func.count()).select_from(User)
        .where(User.deleted_at.is_(None), User.onboarding_complete.is_(False),
               User.onboarding_step == 0)
    )).scalar() or 0

    # Passos por etapa (para funil detalhado)
    step_rows = (await db.execute(
        select(User.onboarding_step, func.count().label("n"))
        .where(User.deleted_at.is_(None), User.onboarding_complete.is_(False))
        .group_by(User.onboarding_step)
        .order_by(User.onboarding_step)
    )).all()
    onboarding_by_step = {r.onboarding_step: r.n for r in step_rows}

    # ── B2B: Nutricionistas ──
    nutri_total = (await db.execute(
        select(func.count()).select_from(User)
        .where(User.deleted_at.is_(None), User.plan == "nutritionist")
    )).scalar() or 0

    nutri_trial_expiring = (await db.execute(
        select(func.count()).select_from(User)
        .where(
            User.deleted_at.is_(None),
            User.plan == "nutritionist",
            User.trial_ends_at.isnot(None),
            User.trial_ends_at > now_utc,
            User.trial_ends_at < now_utc + timedelta(days=7),
        )
    )).scalar() or 0

    nutri_patients_active = (await db.execute(
        select(func.count()).select_from(NutritionistPatient)
        .where(NutritionistPatient.status == "active")
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
            # ③ onboarding
            "onboarding_complete": onboarding_complete,
            "onboarding_in_progress": onboarding_in_progress,
            "onboarding_not_started": onboarding_not_started,
            "onboarding_total": onboarding_total,
            "onboarding_by_step": onboarding_by_step,
            # B2B
            "nutri_total": nutri_total,
            "nutri_trial_expiring": nutri_trial_expiring,
            "nutri_patients_active": nutri_patients_active,
            # outros
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

    # ── Pacientes (só carrega quando é nutricionista) ──
    patients: list = []
    if user.plan == "nutritionist":
        patient_rows = (await db.execute(
            select(NutritionistPatient, User)
            .outerjoin(User, NutritionistPatient.patient_id == User.id)
            .where(NutritionistPatient.nutritionist_id == uid)
            .order_by(NutritionistPatient.invited_at.desc())
        )).all()
        patients = patient_rows

    return templates.TemplateResponse(
        request=request, name="admin_usuario.html",
        context={
            "u": user,
            "meal_count": meal_count,
            "water_count": water_count,
            "last_meal": last_meal,
            "subscriptions": subscriptions,
            "plan_history": plan_history,
            "patients": patients,
        },
    )


# ── Painel B2C ────────────────────────────────────────────────────────────────

@router.get("/b2c", response_class=HTMLResponse)
async def admin_b2c(
    request: Request,
    seg: str = "",        # new | engaged | dormant | at_risk | expiring | eligible
    q: str = "",
    plan_f: str = "",
    page: int = 1,
    admin_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Painel de usuários B2C: plano free/premium sem vínculo ativo com nutricionista."""
    if not _verify_admin_token(admin_session):
        return RedirectResponse("/admin/login", 302)

    now_utc     = datetime.now(timezone.utc)
    seven_ago   = now_utc - timedelta(days=7)
    fourteen_ago = now_utc - timedelta(days=14)
    thirty_ago  = now_utc - timedelta(days=30)
    per_page    = 50
    offset      = (page - 1) * per_page

    # ── Subqueries auxiliares ─────────────────────────────────────────────────

    # Pacientes ativos de nutricionistas (excluídos da visão B2C)
    active_patient_sq = (
        select(NutritionistPatient.patient_id)
        .where(NutritionistPatient.status == "active",
               NutritionistPatient.patient_id.isnot(None))
    )

    # Filtro base B2C
    b2c_where = [
        User.deleted_at.is_(None),
        User.plan.in_(["free", "premium"]),
        User.id.not_in(active_patient_sq),
    ]

    # Usuários com pelo menos uma refeição
    has_meal_sq = select(MealLog.user_id.distinct())
    # Usuários com refeição nos últimos 7 dias
    meal_7d_sq  = select(MealLog.user_id.distinct()).where(MealLog.logged_at > seven_ago)
    # Usuários com refeição nos últimos 14 dias
    meal_14d_sq = select(MealLog.user_id.distinct()).where(MealLog.logged_at > fourteen_ago)

    # Stats de refeições por usuário (para a tabela)
    meal_stats_sq = (
        select(
            MealLog.user_id,
            func.count().label("meal_count"),
            func.max(MealLog.logged_at).label("last_meal"),
        )
        .group_by(MealLog.user_id)
        .subquery("ms")
    )

    # ── Tiles ─────────────────────────────────────────────────────────────────
    total_b2c = (await db.execute(
        select(func.count()).select_from(User).where(*b2c_where)
    )).scalar() or 0

    total_free = (await db.execute(
        select(func.count()).select_from(User).where(*b2c_where, User.plan == "free")
    )).scalar() or 0

    total_premium = (await db.execute(
        select(func.count()).select_from(User).where(*b2c_where, User.plan == "premium")
    )).scalar() or 0

    expiring_7d = (await db.execute(
        select(func.count()).select_from(User).where(
            *b2c_where,
            User.plan == "premium",
            User.plan_expires_at.isnot(None),
            User.plan_expires_at > now_utc,
            User.plan_expires_at < now_utc + timedelta(days=7),
        )
    )).scalar() or 0

    # ── Segmentos ─────────────────────────────────────────────────────────────
    seg_new = (await db.execute(
        select(func.count()).select_from(User).where(*b2c_where,
                                                     User.created_at > seven_ago)
    )).scalar() or 0

    seg_engaged = (await db.execute(
        select(func.count()).select_from(User)
        .where(*b2c_where, User.id.in_(meal_7d_sq))
    )).scalar() or 0

    seg_dormant = (await db.execute(
        select(func.count()).select_from(User)
        .where(*b2c_where, User.id.not_in(has_meal_sq))
    )).scalar() or 0

    seg_at_risk = (await db.execute(
        select(func.count()).select_from(User)
        .where(*b2c_where,
               User.id.in_(has_meal_sq),
               User.id.not_in(meal_14d_sq))
    )).scalar() or 0

    # Elegíveis para upgrade: free, onboarding completo, cadastro > 7d, nunca premium
    seg_eligible = (await db.execute(
        select(func.count()).select_from(User)
        .where(*b2c_where,
               User.plan == "free",
               User.onboarding_complete.is_(True),
               User.created_at < seven_ago)
    )).scalar() or 0

    # ── Engajamento ──────────────────────────────────────────────────────────
    new_7d = seg_new

    # Média de refeições/semana dos usuários engajados (últimos 7d)
    avg_meals_row = (await db.execute(
        text(
            "SELECT ROUND(AVG(cnt),1) FROM ("
            "  SELECT COUNT(*) AS cnt FROM meal_logs ml"
            "  JOIN users u ON u.id = ml.user_id"
            "  WHERE ml.logged_at > :since AND u.plan IN ('free','premium')"
            "    AND u.deleted_at IS NULL"
            "  GROUP BY ml.user_id"
            ") sub"
        ),
        {"since": seven_ago},
    )).scalar()
    avg_meals_week = float(avg_meals_row or 0)

    onboarding_complete_b2c = (await db.execute(
        select(func.count()).select_from(User)
        .where(*b2c_where, User.onboarding_complete.is_(True))
    )).scalar() or 0

    # ── Conversão free → premium ──────────────────────────────────────────────
    upgrades_30d = (await db.execute(
        text(
            "SELECT COUNT(*) FROM admin_logs "
            "WHERE action='change_plan' AND created_at > :since "
            "AND (detail->>'new')='premium'"
        ),
        {"since": thirty_ago},
    )).scalar() or 0

    conversion_rate = (
        round(total_premium / (total_free + total_premium) * 100, 1)
        if (total_free + total_premium) > 0 else 0.0
    )

    # ── Lista paginada com filtro de segmento ─────────────────────────────────
    list_q = (
        select(User, meal_stats_sq.c.meal_count, meal_stats_sq.c.last_meal)
        .outerjoin(meal_stats_sq, meal_stats_sq.c.user_id == User.id)
        .where(*b2c_where)
    )

    if q:
        like = f"%{q}%"
        list_q = list_q.where(
            User.first_name.ilike(like) |
            User.channel_id.ilike(like) |
            User.email.ilike(like)
        )
    if plan_f:
        list_q = list_q.where(User.plan == plan_f)

    if seg == "new":
        list_q = list_q.where(User.created_at > seven_ago)
    elif seg == "engaged":
        list_q = list_q.where(User.id.in_(meal_7d_sq))
    elif seg == "dormant":
        list_q = list_q.where(User.id.not_in(has_meal_sq))
    elif seg == "at_risk":
        list_q = list_q.where(User.id.in_(has_meal_sq), User.id.not_in(meal_14d_sq))
    elif seg == "expiring":
        list_q = list_q.where(
            User.plan == "premium",
            User.plan_expires_at.isnot(None),
            User.plan_expires_at > now_utc,
            User.plan_expires_at < now_utc + timedelta(days=7),
        )
    elif seg == "eligible":
        list_q = list_q.where(
            User.plan == "free",
            User.onboarding_complete.is_(True),
            User.created_at < seven_ago,
        )

    total_filtered = (await db.execute(
        select(func.count()).select_from(list_q.subquery())
    )).scalar() or 0

    rows = (await db.execute(
        list_q.order_by(User.last_active_at.desc().nullslast())
        .offset(offset).limit(per_page)
    )).all()

    total_pages = max(1, (total_filtered + per_page - 1) // per_page)

    return templates.TemplateResponse(
        request=request, name="admin_b2c.html",
        context={
            # tiles
            "total_b2c": total_b2c,
            "total_free": total_free,
            "total_premium": total_premium,
            "expiring_7d": expiring_7d,
            # segmentos
            "seg_new": seg_new,
            "seg_engaged": seg_engaged,
            "seg_dormant": seg_dormant,
            "seg_at_risk": seg_at_risk,
            "seg_eligible": seg_eligible,
            # engajamento
            "new_7d": new_7d,
            "avg_meals_week": avg_meals_week,
            "onboarding_complete_b2c": onboarding_complete_b2c,
            # conversão
            "upgrades_30d": upgrades_30d,
            "conversion_rate": conversion_rate,
            "seg_eligible": seg_eligible,
            # lista
            "rows": rows,
            "total_filtered": total_filtered,
            "total_pages": total_pages,
            "page": page,
            "per_page": per_page,
            "seg": seg,
            "q": q,
            "plan_f": plan_f,
            "now_utc": now_utc,
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


# ── API JSON: vínculo manual paciente ↔ nutricionista ─────────────────────────

@router.post("/api/nutricionistas/{nutri_id}/vincular-paciente")
async def admin_link_patient(
    request: Request,
    nutri_id: str,
    patient_id: str = Form(...),
    admin_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Cria vínculo ativo entre nutricionista e paciente sem passar pelo convite."""
    if not _verify_admin_token(admin_session):
        raise HTTPException(403, "Não autorizado")

    import secrets
    import uuid as _uuid

    try:
        nutri_uid   = _uuid.UUID(nutri_id)
        patient_uid = _uuid.UUID(patient_id)
    except ValueError:
        raise HTTPException(422, "UUID inválido")

    if nutri_uid == patient_uid:
        raise HTTPException(422, "Nutricionista não pode ser vinculada a si mesma")

    # Verifica que ambos existem
    nutri = (await db.execute(
        select(User).where(User.id == nutri_uid, User.plan == "nutritionist", User.deleted_at.is_(None))
    )).scalar_one_or_none()
    if not nutri:
        raise HTTPException(404, "Nutricionista não encontrada ou plano incorreto")

    patient = (await db.execute(
        select(User).where(User.id == patient_uid, User.deleted_at.is_(None))
    )).scalar_one_or_none()
    if not patient:
        raise HTTPException(404, "Paciente não encontrado")

    # Verifica vínculo ativo ou pendente já existente
    existing = (await db.execute(
        select(NutritionistPatient)
        .where(
            NutritionistPatient.nutritionist_id == nutri_uid,
            NutritionistPatient.patient_id == patient_uid,
            NutritionistPatient.status.in_(["active", "pending"]),
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(409, f"Vínculo já existe com status '{existing.status}'")

    now_utc = datetime.now(timezone.utc)
    link = NutritionistPatient(
        nutritionist_id=nutri_uid,
        patient_id=patient_uid,
        patient_name=patient.first_name,
        invite_token=secrets.token_urlsafe(32),
        status="active",
        invited_at=now_utc,
        expires_at=now_utc + timedelta(days=3650),   # 10 anos — vínculo manual
        consented_at=now_utc,                        # admin bypass — responsabilidade do admin
    )
    db.add(link)
    await db.commit()

    await _log_action(
        db, "link_patient_manual", nutri_uid,
        {
            "patient_id": str(patient_uid),
            "patient_name": patient.first_name or "",
            "nutri_name": nutri.first_name or "",
        },
        ip=_client_ip(request),
    )
    logger.info(
        "[Admin] vínculo manual: nutri=%s → paciente=%s",
        nutri.channel_id, patient.channel_id,
    )
    return JSONResponse({
        "ok": True,
        "link_id": str(link.id),
        "patient_name": patient.first_name or "(sem nome)",
        "patient_channel": patient.channel_id,
    })


@router.post("/api/nutricionistas/{nutri_id}/desvincular-paciente/{link_id}")
async def admin_unlink_patient(
    request: Request,
    nutri_id: str,
    link_id: str,
    admin_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Revoga vínculo paciente (altera status para 'revoked')."""
    if not _verify_admin_token(admin_session):
        raise HTTPException(403, "Não autorizado")

    import uuid as _uuid
    try:
        nutri_uid = _uuid.UUID(nutri_id)
        link_uuid = _uuid.UUID(link_id)
    except ValueError:
        raise HTTPException(422, "UUID inválido")

    link = (await db.execute(
        select(NutritionistPatient)
        .where(
            NutritionistPatient.id == link_uuid,
            NutritionistPatient.nutritionist_id == nutri_uid,
        )
    )).scalar_one_or_none()
    if not link:
        raise HTTPException(404, "Vínculo não encontrado")
    if link.status == "revoked":
        raise HTTPException(409, "Vínculo já está revogado")

    old_status = link.status
    link.status = "revoked"
    link.revoked_at = datetime.now(timezone.utc)
    await db.commit()

    await _log_action(
        db, "unlink_patient_admin", nutri_uid,
        {
            "link_id": str(link_uuid),
            "patient_id": str(link.patient_id) if link.patient_id else None,
            "old_status": old_status,
        },
        ip=_client_ip(request),
    )
    return JSONResponse({"ok": True, "old_status": old_status})


@router.post("/api/nutricionistas/{nutri_id}/reenviar-convite/{link_id}")
async def admin_resend_invite(
    request: Request,
    nutri_id: str,
    link_id: str,
    admin_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Regenera token e reativa prazo (7 dias) para um convite expirado ou recusado."""
    if not _verify_admin_token(admin_session):
        raise HTTPException(403, "Não autorizado")

    import secrets
    import uuid as _uuid

    try:
        nutri_uid = _uuid.UUID(nutri_id)
        link_uuid = _uuid.UUID(link_id)
    except ValueError:
        raise HTTPException(422, "UUID inválido")

    link = (await db.execute(
        select(NutritionistPatient)
        .where(
            NutritionistPatient.id == link_uuid,
            NutritionistPatient.nutritionist_id == nutri_uid,
        )
    )).scalar_one_or_none()
    if not link:
        raise HTTPException(404, "Vínculo não encontrado")
    if link.status in ("active", "pending"):
        raise HTTPException(409, f"Convite já está com status '{link.status}' — não é necessário reenviar")

    now_utc = datetime.now(timezone.utc)
    old_status = link.status
    link.status = "pending"
    link.invite_token = secrets.token_urlsafe(32)
    link.invited_at = now_utc
    link.expires_at = now_utc + timedelta(days=7)
    link.consented_at = None
    link.revoked_at = None
    await db.commit()

    await _log_action(
        db, "resend_invite", nutri_uid,
        {
            "link_id": str(link_uuid),
            "patient_id": str(link.patient_id) if link.patient_id else None,
            "old_status": old_status,
        },
        ip=_client_ip(request),
    )
    logger.info("[Admin] convite regenerado: link=%s (era %s)", link_uuid, old_status)
    return JSONResponse({"ok": True, "new_status": "pending", "old_status": old_status})


@router.post("/api/nutricionistas/{nutri_id}/excluir-link/{link_id}")
async def admin_delete_link(
    request: Request,
    nutri_id: str,
    link_id: str,
    admin_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Remove permanentemente um vínculo expirado, recusado ou revogado."""
    if not _verify_admin_token(admin_session):
        raise HTTPException(403, "Não autorizado")

    import uuid as _uuid

    try:
        nutri_uid = _uuid.UUID(nutri_id)
        link_uuid = _uuid.UUID(link_id)
    except ValueError:
        raise HTTPException(422, "UUID inválido")

    link = (await db.execute(
        select(NutritionistPatient)
        .where(
            NutritionistPatient.id == link_uuid,
            NutritionistPatient.nutritionist_id == nutri_uid,
        )
    )).scalar_one_or_none()
    if not link:
        raise HTTPException(404, "Vínculo não encontrado")
    if link.status in ("active", "pending"):
        raise HTTPException(409, "Não é possível excluir um vínculo ativo ou pendente — revogue primeiro")

    old_status = link.status
    patient_id_str = str(link.patient_id) if link.patient_id else None
    await db.delete(link)
    await db.commit()

    await _log_action(
        db, "delete_link", nutri_uid,
        {
            "link_id": str(link_uuid),
            "patient_id": patient_id_str,
            "old_status": old_status,
        },
        ip=_client_ip(request),
    )
    logger.info("[Admin] vínculo excluído: link=%s (era %s)", link_uuid, old_status)
    return JSONResponse({"ok": True, "deleted": str(link_uuid)})


# ── ② Painel de Nutricionistas ────────────────────────────────────────────────

@router.get("/nutricionistas", response_class=HTMLResponse)
async def admin_nutricionistas(
    request: Request,
    status_filter: str = "",   # "" | "trial" | "active" | "expired"
    page: int = 1,
    admin_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    if not _verify_admin_token(admin_session):
        return RedirectResponse("/admin/login", 302)

    now_utc = datetime.now(timezone.utc)
    per_page = 50
    offset = (page - 1) * per_page

    # Base: todos os usuários com plano nutritionist
    base_q = select(User).where(
        User.deleted_at.is_(None),
        User.plan == "nutritionist",
    )

    if status_filter == "trial":
        base_q = base_q.where(User.trial_ends_at.isnot(None), User.trial_ends_at > now_utc)
    elif status_filter == "active":
        base_q = base_q.where(
            User.trial_ends_at.is_(None) |
            (User.trial_ends_at < now_utc),
        )
    elif status_filter == "expired":
        base_q = base_q.where(
            User.plan_expires_at.isnot(None),
            User.plan_expires_at < now_utc,
        )
    elif status_filter == "expiring":
        base_q = base_q.where(
            User.trial_ends_at.isnot(None),
            User.trial_ends_at > now_utc,
            User.trial_ends_at < now_utc + timedelta(days=7),
        )

    total = (await db.execute(
        select(func.count()).select_from(base_q.subquery())
    )).scalar() or 0

    nutris = (await db.execute(
        base_q.order_by(User.created_at.desc()).offset(offset).limit(per_page)
    )).scalars().all()

    # Para cada nutricionista, contar pacientes ativos e totais
    nutri_ids = [n.id for n in nutris]
    patient_counts: dict = {}
    if nutri_ids:
        counts_rows = (await db.execute(
            select(
                NutritionistPatient.nutritionist_id,
                NutritionistPatient.status,
                func.count().label("n"),
            )
            .where(NutritionistPatient.nutritionist_id.in_(nutri_ids))
            .group_by(NutritionistPatient.nutritionist_id, NutritionistPatient.status)
        )).all()
        for r in counts_rows:
            nid = str(r.nutritionist_id)
            if nid not in patient_counts:
                patient_counts[nid] = {"active": 0, "total": 0, "pending": 0}
            patient_counts[nid]["total"] += r.n
            if r.status == "active":
                patient_counts[nid]["active"] += r.n
            elif r.status == "pending":
                patient_counts[nid]["pending"] += r.n

    # Tiles / totais gerais
    tile_total = (await db.execute(
        select(func.count()).select_from(User)
        .where(User.deleted_at.is_(None), User.plan == "nutritionist")
    )).scalar() or 0

    tile_trial = (await db.execute(
        select(func.count()).select_from(User)
        .where(User.deleted_at.is_(None), User.plan == "nutritionist",
               User.trial_ends_at.isnot(None), User.trial_ends_at > now_utc)
    )).scalar() or 0

    tile_expiring = (await db.execute(
        select(func.count()).select_from(User)
        .where(User.deleted_at.is_(None), User.plan == "nutritionist",
               User.trial_ends_at.isnot(None), User.trial_ends_at > now_utc,
               User.trial_ends_at < now_utc + timedelta(days=7))
    )).scalar() or 0

    tile_patients_active = (await db.execute(
        select(func.count()).select_from(NutritionistPatient)
        .where(NutritionistPatient.status == "active")
    )).scalar() or 0

    total_pages = max(1, (total + per_page - 1) // per_page)

    return templates.TemplateResponse(
        request=request, name="admin_nutricionistas.html",
        context={
            "nutris": nutris,
            "patient_counts": patient_counts,
            "total": total,
            "status_filter": status_filter,
            "page": page,
            "total_pages": total_pages,
            "per_page": per_page,
            "now_utc": now_utc,
            "tiles": {
                "total": tile_total,
                "trial": tile_trial,
                "expiring": tile_expiring,
                "patients_active": tile_patients_active,
            },
        },
    )


# ── API JSON: busca de usuários (para autocomplete) ──────────────────────────
# ATENÇÃO: rota GET sem path param — deve vir ANTES de qualquer /{user_id}

@router.get("/api/usuarios/buscar")
async def admin_buscar_usuarios(
    q: str = "",
    exclude_nutri_id: str = "",   # exclui já-vinculados a esta nutricionista
    admin_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Retorna até 20 usuários que batem com q (nome, e-mail ou channel_id)."""
    if not _verify_admin_token(admin_session):
        raise HTTPException(403, "Não autorizado")

    if len(q) < 2:
        return JSONResponse([])

    like = f"%{q}%"
    stmt = (
        select(User.id, User.first_name, User.email, User.channel_type, User.channel_id, User.plan)
        .where(
            User.deleted_at.is_(None),
            User.first_name.ilike(like) | User.channel_id.ilike(like) | User.email.ilike(like),
        )
        .order_by(User.first_name)
        .limit(20)
    )

    rows = (await db.execute(stmt)).mappings().all()

    # Se foi passado nutri_id, exclui quem já está vinculado (ativo ou pendente)
    excluded_ids: set[str] = set()
    if exclude_nutri_id:
        import uuid as _uuid
        try:
            nutri_uid = _uuid.UUID(exclude_nutri_id)
            links = (await db.execute(
                select(NutritionistPatient.patient_id)
                .where(
                    NutritionistPatient.nutritionist_id == nutri_uid,
                    NutritionistPatient.status.in_(["active", "pending"]),
                    NutritionistPatient.patient_id.isnot(None),
                )
            )).scalars().all()
            excluded_ids = {str(pid) for pid in links}
            excluded_ids.add(exclude_nutri_id)   # não vincular a si mesmo
        except ValueError:
            pass

    result = [
        {
            "id": str(r.id),
            "name": r.first_name or "(sem nome)",
            "email": r.email or "",
            "channel_type": r.channel_type,
            "channel_id": r.channel_id,
            "plan": r.plan,
        }
        for r in rows
        if str(r.id) not in excluded_ids
    ]
    return JSONResponse(result)


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


# ── ⑤ Bulk-fix planos expirados ───────────────────────────────────────────────

@router.post("/api/bulk-fix-planos")
async def admin_bulk_fix_plans(
    request: Request,
    admin_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Reverte para free todos os usuários com plan != free e plan_expires_at < now."""
    if not _verify_admin_token(admin_session):
        raise HTTPException(403, "Não autorizado")

    now_utc = datetime.now(timezone.utc)

    # Busca os afetados primeiro para logar
    stale_users = (await db.execute(
        select(User)
        .where(
            User.deleted_at.is_(None),
            User.plan != "free",
            User.plan_expires_at.isnot(None),
            User.plan_expires_at < now_utc,
        )
    )).scalars().all()

    count = len(stale_users)
    if count == 0:
        return JSONResponse({"ok": True, "fixed": 0, "message": "Nenhum plano a corrigir."})

    for user in stale_users:
        old_plan = user.plan
        user.plan = "free"
        user.plan_expires_at = None
        await _log_action(db, "bulk_fix_plan", user.id,
                          {"old": old_plan, "reason": "expired"},
                          ip=_client_ip(request))

    await db.commit()
    logger.info("[Admin] bulk-fix: %d planos expirados revertidos para free", count)
    return JSONResponse({"ok": True, "fixed": count,
                         "message": f"{count} plano(s) revertido(s) para free."})


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

    # ④ Feature flags (leitura ao vivo do config)
    feature_flags = {
        "maintenance_mode": settings.maintenance_mode,
        "reports_open_beta": settings.reports_open_beta,
        "free_tier_max_logs_per_day": settings.free_tier_max_logs_per_day,
        "free_tier_history_days": settings.free_tier_history_days,
        "rate_limit_messages_per_minute": settings.rate_limit_messages_per_minute,
        "rate_limit_photos_per_hour": settings.rate_limit_photos_per_hour,
        "audio_provider": settings.audio_provider,
        "whisper_model_size": settings.whisper_model_size,
        "app_env": settings.app_env,
    }

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
            "feature_flags": feature_flags,
        },
    )


# ── Logs de auditoria ─────────────────────────────────────────────────────────

@router.get("/logs", response_class=HTMLResponse)
async def admin_logs_page(
    request: Request,
    page: int = 1,
    action_filter: str = "",
    admin_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    if not _verify_admin_token(admin_session):
        return RedirectResponse("/admin/login", 302)

    per_page = 50
    offset = (page - 1) * per_page

    if action_filter:
        total = (await db.execute(
            text("SELECT COUNT(*) FROM admin_logs WHERE action = :a"),
            {"a": action_filter},
        )).scalar() or 0
        rows = (await db.execute(
            text(
                "SELECT id, created_at, action, target_user_id, detail "
                "FROM admin_logs WHERE action = :a "
                "ORDER BY created_at DESC LIMIT :lim OFFSET :off"
            ),
            {"a": action_filter, "lim": per_page, "off": offset},
        )).mappings().all()
    else:
        total = (await db.execute(text("SELECT COUNT(*) FROM admin_logs"))).scalar() or 0
        rows = (await db.execute(
            text(
                "SELECT id, created_at, action, target_user_id, detail "
                "FROM admin_logs ORDER BY created_at DESC LIMIT :lim OFFSET :off"
            ),
            {"lim": per_page, "off": offset},
        )).mappings().all()

    # Tipos de ação distintos para o filtro
    action_types = (await db.execute(
        text("SELECT DISTINCT action FROM admin_logs ORDER BY action")
    )).scalars().all()

    total_pages = max(1, (total + per_page - 1) // per_page)

    return templates.TemplateResponse(
        request=request, name="admin_logs.html",
        context={
            "rows": rows,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "per_page": per_page,
            "action_filter": action_filter,
            "action_types": action_types,
        },
    )
