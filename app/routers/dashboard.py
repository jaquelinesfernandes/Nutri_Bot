"""Rotas HTML da plataforma web — server-rendered com Jinja2."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.models.meal_log import MealLog
from app.models.user import User
from app.models.weekly_report import WeeklyReport
from app.utils.jwt import create_access_token, decode_token, get_current_user_optional

router = APIRouter(tags=["dashboard"])

# Caminho absoluto — funciona em qualquer working directory (local e Docker)
_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_MEAL_LABELS = {
    "breakfast": "☀️ Café da manhã",
    "morning_snack": "🍌 Lanche da manhã",
    "lunch": "🍽️ Almoço",
    "afternoon_snack": "🍊 Lanche da tarde",
    "dinner": "🌙 Jantar",
    "snack": "🍎 Lanche",
    "other": "🍴 Refeição",
}


def _cookie_response(url: str, token: str, secure: bool) -> RedirectResponse:
    from app.config import settings
    resp = RedirectResponse(url=url, status_code=302)
    resp.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=settings.jwt_expire_days * 86_400,
        path="/",
    )
    return resp


# ── Raiz ──────────────────────────────────────────────────────────────────────

@router.get("/", response_class=RedirectResponse)
async def root():
    return RedirectResponse(url="/login", status_code=302)


# ── Auth (formulários HTML) ────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")


@router.post("/auth/login-form", response_class=HTMLResponse)
async def login_form(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    from app.config import settings as cfg
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user or not user.password_hash or not pwd_context.verify(password, user.password_hash):
        return templates.TemplateResponse(
            request=request, name="login.html",
            context={"error": "E-mail ou senha incorretos"},
            status_code=401,
        )
    token = create_access_token(user.id)
    # Se usuário web puro (não vinculou Telegram), passa pelo onboarding de vinculação
    next_url = "/dashboard" if user.channel_type == "telegram" else "/vincular-telegram"
    return _cookie_response(next_url, token, cfg.app_env == "production")


@router.get("/cadastro", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse(request=request, name="register.html")


@router.post("/auth/register-form", response_class=HTMLResponse)
async def register_form(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    daily_calorie_goal: int | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    from app.config import settings as cfg
    if len(password) < 6:
        return templates.TemplateResponse(
            request=request, name="register.html",
            context={"error": "Senha deve ter ao menos 6 caracteres"},
            status_code=422,
        )
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        return templates.TemplateResponse(
            request=request, name="register.html",
            context={"error": "E-mail já cadastrado"},
            status_code=400,
        )
    user = User(
        channel_id=f"web:{email}",
        channel_type="web",
        email=email,
        password_hash=pwd_context.hash(password),
        first_name=name.strip(),
        daily_calorie_goal=daily_calorie_goal,
        onboarding_complete=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    token = create_access_token(user.id)
    # Novo cadastro: sempre passa pelo onboarding de vinculação Telegram
    return _cookie_response("/vincular-telegram", token, cfg.app_env == "production")


@router.post("/api/auth/logout")
async def logout_web():
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie("access_token", path="/")
    return resp


# ── Páginas protegidas ─────────────────────────────────────────────────────────

def _require_auth(request: Request, user: User | None) -> RedirectResponse | None:
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    return None


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    if user is None:
        return RedirectResponse(url="/login", status_code=302)

    tz = ZoneInfo(user.timezone or "America/Sao_Paulo")
    now = datetime.now(tz)
    today = now.date()

    # Refeições de hoje
    from datetime import timedelta
    day_start = datetime(today.year, today.month, today.day, 0, 0, tzinfo=tz)
    day_end = datetime(today.year, today.month, today.day, 23, 59, 59, tzinfo=tz)
    result = await db.execute(
        select(MealLog)
        .options(selectinload(MealLog.food_items))
        .where(MealLog.user_id == user.id, MealLog.confirmed == True,  # noqa: E712
               MealLog.logged_at >= day_start, MealLog.logged_at <= day_end)
        .order_by(MealLog.logged_at)
    )
    meals = list(result.scalars().all())

    total_kcal = sum(m.total_calories_kcal for m in meals)
    total_prot = sum(m.total_protein_g for m in meals)
    total_carb = sum(m.total_carb_g for m in meals)
    total_fat  = sum(m.total_fat_g for m in meals)
    goal_kcal = user.daily_calorie_goal
    pct_kcal = (total_kcal / goal_kcal * 100) if goal_kcal else 0
    pct_prot = (total_prot / (goal_kcal * 0.06) * 100) if goal_kcal else 0  # ~6% meta prot

    # Dados dos últimos 7 dias para gráfico
    week_data = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        ds = datetime(d.year, d.month, d.day, 0, 0, tzinfo=tz)
        de = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=tz)
        r2 = await db.execute(
            select(MealLog).where(
                MealLog.user_id == user.id, MealLog.confirmed == True,  # noqa: E712
                MealLog.logged_at >= ds, MealLog.logged_at <= de,
            )
        )
        day_meals = list(r2.scalars().all())
        week_data.append({
            "label": d.strftime("%a %d/%m"),
            "kcal": round(sum(m.total_calories_kcal for m in day_meals), 1),
        })

    br_weekdays = {"Mon":"Seg","Tue":"Ter","Wed":"Qua","Thu":"Qui","Fri":"Sex","Sat":"Sáb","Sun":"Dom"}
    week_labels = [br_weekdays.get(w["label"][:3], w["label"][:3]) + " " + w["label"][4:] for w in week_data]

    months_pt = ["","jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"]
    today_label = f"{today.day} de {months_pt[today.month]} de {today.year}"

    return templates.TemplateResponse(
        request=request, name="dashboard.html",
        context={
            "user": user, "active": "dashboard",
            "meals": meals, "meal_labels": _MEAL_LABELS,
            "total_kcal": total_kcal, "total_prot": total_prot,
            "total_carb": total_carb, "total_fat": total_fat,
            "goal_kcal": goal_kcal, "pct_kcal": pct_kcal, "pct_prot": pct_prot,
            "week_labels": week_labels,
            "week_kcal": [w["kcal"] for w in week_data],
            "now_hour": now.hour, "today_label": today_label,
        }
    )


@router.get("/historico", response_class=HTMLResponse)
async def historico(
    request: Request,
    date: str | None = None,
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    if user is None:
        return RedirectResponse(url="/login", status_code=302)

    tz = ZoneInfo(user.timezone or "America/Sao_Paulo")
    today = datetime.now(tz).date()
    try:
        target = date_module_date.fromisoformat(date) if date else today
    except (ValueError, TypeError):
        target = today

    day_start = datetime(target.year, target.month, target.day, 0, 0, tzinfo=tz)
    day_end = datetime(target.year, target.month, target.day, 23, 59, 59, tzinfo=tz)
    result = await db.execute(
        select(MealLog)
        .options(selectinload(MealLog.food_items))
        .where(MealLog.user_id == user.id, MealLog.confirmed == True,  # noqa: E712
               MealLog.logged_at >= day_start, MealLog.logged_at <= day_end)
        .order_by(MealLog.logged_at)
    )
    meals = list(result.scalars().all())

    from app.schemas.meal import DailyBalance, MealLogRead
    balance = None
    if meals:
        balance = DailyBalance(
            date=target.isoformat(),
            total_calories_kcal=sum(m.total_calories_kcal for m in meals),
            total_protein_g=sum(m.total_protein_g for m in meals),
            total_carb_g=sum(m.total_carb_g for m in meals),
            total_fat_g=sum(m.total_fat_g for m in meals),
            goal_calories=user.daily_calorie_goal,
            remaining_calories=None,
            meals=[MealLogRead.model_validate(m) for m in meals],
        )

    return templates.TemplateResponse(
        request=request, name="historico.html",
        context={
            "user": user, "active": "historico",
            "selected_date": target.isoformat(),
            "balance": balance, "meal_labels": _MEAL_LABELS,
        }
    )


@router.get("/relatorios", response_class=HTMLResponse)
async def relatorios(
    request: Request,
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    if user is None:
        return RedirectResponse(url="/login", status_code=302)

    from app.config import settings
    from datetime import timedelta as _td

    result = await db.execute(
        select(WeeklyReport)
        .where(WeeklyReport.user_id == user.id)
        .order_by(WeeklyReport.week_start_date.desc())
        .limit(20)
    )
    reports_raw = result.scalars().all()

    _months_short = ["","jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"]
    _months_long  = ["","Janeiro","Fevereiro","Março","Abril","Maio","Junho",
                     "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]

    def _fmt_period(r: WeeklyReport) -> str:
        s = r.week_start_date
        if r.period_type == "weekly":
            e = r.period_end_date or (s + _td(days=6))
            return f"{s.day:02d}/{_months_short[s.month]} a {e.day:02d}/{_months_short[e.month]}/{e.year}"
        if r.period_type == "monthly":
            return f"{_months_long[s.month]} {s.year}"
        if r.period_type == "quarterly":
            e = r.period_end_date or (s + _td(days=89))
            return f"{_months_long[s.month]} – {_months_long[e.month]} {e.year}"
        return s.strftime("%d/%m/%Y")

    _type_labels = {
        "weekly": "Semanal", "monthly": "Mensal",
        "quarterly": "Trimestral", "custom": "Personalizado",
    }

    reports = [
        {
            "id": r.id,
            "week_start_date": r.week_start_date.isoformat(),
            "period_end_date": r.period_end_date.isoformat() if r.period_end_date else None,
            "period_type": r.period_type,
            "period_label": _type_labels.get(r.period_type, r.period_type),
            "period_range": _fmt_period(r),
            "generated_at": r.generated_at.strftime("%d/%m/%Y às %H:%M"),
            "delivered_at": r.delivered_at.strftime("%d/%m/%Y") if r.delivered_at else None,
            "has_pdf": bool(r.pdf_storage_path),
        }
        for r in reports_raw
    ]
    return templates.TemplateResponse(
        request=request, name="relatorios.html",
        context={
            "user": user, "active": "relatorios",
            "reports": reports, "is_premium": user.is_premium or settings.reports_open_beta,
        },
    )


@router.get("/configuracoes", response_class=HTMLResponse)
async def configuracoes(
    request: Request,
    success: str | None = None,
    error: str | None = None,
    user: User | None = Depends(get_current_user_optional),
):
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(
        request=request, name="configuracoes.html",
        context={"user": user, "active": "configuracoes", "success": success, "error": error},
    )


@router.post("/configuracoes/salvar")
async def configuracoes_salvar(
    request: Request,
    name: str = Form(default=""),
    daily_calorie_goal: int | None = Form(default=None),
    goal_type: str = Form(default=""),
    timezone: str = Form(default="America/Sao_Paulo"),
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    if name.strip():
        user.first_name = name.strip()
    if daily_calorie_goal:
        user.daily_calorie_goal = daily_calorie_goal
    if goal_type:
        user.goal_type = goal_type or None
    user.timezone = timezone
    await db.commit()
    return RedirectResponse(url="/configuracoes?success=Configurações+salvas", status_code=302)


@router.post("/configuracoes/vincular-telegram")
async def vincular_telegram(
    request: Request,
    link_code: str = Form(...),
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Vincula a conta web ao usuário Telegram via código temporário.

    Estratégia segura para async SQLAlchemy:
    - Limpa email/channel_id do usuário web ANTES de copiá-los para o Telegram
      (evita violação da constraint UNIQUE em memória na mesma transação)
    - Usa bulk UPDATE via Core (synchronize_session=False) para remapear refeições
    - Soft-delete no usuário web (evita cascade lazy-load que quebra em async)
    - Emite novo JWT apontando para a conta Telegram unificada
    """
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo

    from sqlalchemy import delete as sa_delete
    from sqlalchemy import update as sa_update

    from app.config import settings as cfg
    from app.models.meal_log import MealLog
    from app.models.meal_window import MealWindow
    from app.models.water_log import WaterLog
    from app.models.weekly_report import WeeklyReport

    if user is None:
        return RedirectResponse(url="/login", status_code=302)

    code = link_code.strip().upper()
    if not code:
        return RedirectResponse(url="/configuracoes?error=Código+inválido", status_code=302)

    # Busca usuário Telegram com esse token ainda válido
    now_utc = _dt.now(ZoneInfo("UTC"))
    result = await db.execute(
        select(User).where(
            User.web_link_token == code,
            User.web_link_token_expires_at > now_utc,
            User.channel_type == "telegram",
        )
    )
    tg_user = result.scalar_one_or_none()

    if tg_user is None:
        return RedirectResponse(
            url="/configuracoes?error=Código+inválido+ou+expirado.+Use+/vincular+no+Telegram+para+gerar+um+novo.",
            status_code=302,
        )

    if tg_user.id == user.id:
        return RedirectResponse(
            url="/configuracoes?error=Esta+conta+Telegram+já+está+vinculada.",
            status_code=302,
        )

    web_user_id = user.id
    tg_user_id = tg_user.id

    # Guarda os valores antes de limpar
    old_email = user.email
    old_password_hash = user.password_hash
    old_calorie_goal = user.daily_calorie_goal
    old_goal_type = user.goal_type

    # ── Passo 1: libera constraints UNIQUE no usuário web ──────────────────────
    # (email e channel_id são UNIQUE — precisam ser limpos ANTES de serem
    #  atribuídos ao tg_user na mesma transação)
    user.email = None
    user.password_hash = None
    user.channel_id = f"merged:{web_user_id}"  # libera "web:{email}" para reutilização
    user.deleted_at = now_utc
    await db.flush()  # aplica só esses UPDATEs; não commita ainda

    # ── Passo 2: transfere credenciais e config para o usuário Telegram ────────
    tg_user.email = old_email
    tg_user.password_hash = old_password_hash
    if not tg_user.daily_calorie_goal and old_calorie_goal:
        tg_user.daily_calorie_goal = old_calorie_goal
    if not tg_user.goal_type and old_goal_type:
        tg_user.goal_type = old_goal_type
    tg_user.web_link_token = None
    tg_user.web_link_token_expires_at = None
    await db.flush()

    # ── Passo 3: remapeia registros do usuário web → Telegram (bulk SQL) ──────
    # synchronize_session=False → não tenta atualizar objetos em memória
    for Model in (MealLog, WeeklyReport, MealWindow, WaterLog):
        await db.execute(
            sa_update(Model)
            .where(Model.user_id == web_user_id)
            .values(user_id=tg_user_id)
            .execution_options(synchronize_session=False)
        )

    # ── Passo 4: hard-delete via SQL (evita lazy-load de cascade em async) ─────
    # PaymentSubscription não é remapeada — cancela junto com a conta web
    await db.execute(
        sa_delete(User).where(User.id == web_user_id)
    )

    await db.commit()

    # ── Passo 5: novo JWT apontando para a conta Telegram unificada ───────────
    token = create_access_token(tg_user_id)
    return _cookie_response(
        "/configuracoes?success=Telegram+vinculado+com+sucesso!+Historico+unificado.",
        token,
        cfg.app_env == "production",
    )


@router.get("/vincular-telegram", response_class=HTMLResponse)
async def vincular_telegram_page(
    request: Request,
    error: str | None = None,
    user: User | None = Depends(get_current_user_optional),
):
    """Tela de onboarding pós-login: vincular conta Telegram ao painel web."""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    # Se já é conta Telegram vinculada, vai direto ao dashboard
    if user.channel_type == "telegram":
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse(
        request=request, name="vincular_telegram.html",
        context={"user": user, "error": error},
    )


@router.post("/vincular-telegram/submit", response_class=HTMLResponse)
async def vincular_telegram_submit(
    request: Request,
    link_code: str = Form(...),
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Processa o código de vinculação na tela de onboarding; redireciona para /dashboard."""
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo
    from sqlalchemy import delete as sa_delete, update as sa_update
    from app.config import settings as cfg
    from app.models.meal_log import MealLog as _ML
    from app.models.meal_window import MealWindow as _MW
    from app.models.water_log import WaterLog as _WL
    from app.models.weekly_report import WeeklyReport as _WR

    if user is None:
        return RedirectResponse(url="/login", status_code=302)

    code = (link_code or "").strip().upper()
    if not code:
        return RedirectResponse(url="/vincular-telegram?error=Código+inválido", status_code=302)

    now_utc = _dt.now(ZoneInfo("UTC"))
    result = await db.execute(
        select(User).where(
            User.web_link_token == code,
            User.web_link_token_expires_at > now_utc,
            User.channel_type == "telegram",
        )
    )
    tg_user = result.scalar_one_or_none()

    if tg_user is None:
        return RedirectResponse(
            url="/vincular-telegram?error=Código+inválido+ou+expirado.+Use+/vincular+no+Telegram+para+gerar+novo.",
            status_code=302,
        )

    web_user_id = user.id
    tg_user_id = tg_user.id
    old_email = user.email
    old_password_hash = user.password_hash
    old_calorie_goal = user.daily_calorie_goal
    old_goal_type = user.goal_type

    # Libera constraints UNIQUE no usuário web
    user.email = None
    user.password_hash = None
    user.channel_id = f"merged:{web_user_id}"
    user.deleted_at = now_utc
    await db.flush()

    # Transfere credenciais para o usuário Telegram
    tg_user.email = old_email
    tg_user.password_hash = old_password_hash
    if not tg_user.daily_calorie_goal and old_calorie_goal:
        tg_user.daily_calorie_goal = old_calorie_goal
    if not tg_user.goal_type and old_goal_type:
        tg_user.goal_type = old_goal_type
    tg_user.web_link_token = None
    tg_user.web_link_token_expires_at = None
    await db.flush()

    for Model in (_ML, _WR, _MW, _WL):
        await db.execute(
            sa_update(Model)
            .where(Model.user_id == web_user_id)
            .values(user_id=tg_user_id)
            .execution_options(synchronize_session=False)
        )
    await db.execute(sa_delete(User).where(User.id == web_user_id))
    await db.commit()

    token = create_access_token(tg_user_id)
    return _cookie_response("/dashboard", token, cfg.app_env == "production")


# fix import name conflict
from datetime import date as date_module_date  # noqa: E402
