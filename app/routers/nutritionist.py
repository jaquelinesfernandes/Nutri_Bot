"""Painel B2B Nutricionistas — Sprint B2B-1 + B2B-2.

Rotas HTML (Jinja2):
  GET  /nutricionista/cadastro              — tela de cadastro
  GET  /nutricionista/                      — painel (requer plano 'nutritionist')
  GET  /nutricionista/paciente/{id}         — perfil do paciente (B2B-2)

Rotas API:
  POST /api/nutricionista/register          — cria conta nutricionista (trial 30d)
  POST /api/nutricionista/convite           — gera convite para paciente
  PATCH /api/nutricionista/convite/{token}  — aceita/recusa convite (chamado pelo bot)
  PATCH /api/nutricionista/revogar/{id}     — revogação LGPD (chamado pelo bot)
  GET  /api/nutricionista/pacientes         — lista pacientes ativos (JSON)
  POST /api/nutricionista/paciente/{id}/nota — adiciona nota clínica (B2B-2)
  GET  /api/nutricionista/paciente/{id}/pdf  — download PDF do paciente (B2B-2)

Autenticação: cookie JWT reutilizado do sistema existente.
O login em /auth/login-form já redireciona para /nutricionista/ quando plan='nutritionist'.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.clinical_note import ClinicalNote
from app.models.nutritionist_patient import NutritionistPatient
from app.models.user import User
from app.utils.jwt import create_access_token, get_current_user_optional

router = APIRouter(tags=["nutritionist"])

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Regex CRN — aceita formatos: CRN-3 12345/P, CRN3 12345, CRN-10 123456/N, etc.
_CRN_RE = re.compile(r"^CRN-?\d{1,2}\s?\d{4,6}(/[PTN])?$", re.IGNORECASE)

_TRIAL_DAYS = 30
_INVITE_EXPIRY_DAYS = 7
_MAX_PATIENTS = 30


# ── Helpers ────────────────────────────────────────────────────────────────────

def _require_nutritionist(user: User | None) -> User:
    """Garante que o usuário está logado e tem plano nutritionist ativo."""
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Não autenticado")
    if not user.is_nutritionist:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito ao plano Nutricionista",
        )
    return user


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


# ── HTML — Cadastro ────────────────────────────────────────────────────────────

@router.get("/nutricionista/cadastro", response_class=HTMLResponse)
async def cadastro_page(request: Request):
    """Tela de cadastro de nutricionista — trial 30 dias sem cartão."""
    return templates.TemplateResponse(
        request=request, name="nutricionista_cadastro.html", context={}
    )


# ── Landing page do convite ────────────────────────────────────────────────────

@router.get("/convite/{token}", response_class=HTMLResponse)
async def landing_convite(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Página de destino do link de convite.

    Valida o token, exibe informações do convite e um botão que abre o Telegram
    com o deep link /start convite_TOKEN.
    Acessível sem autenticação — é o link enviado à paciente.
    """
    from app.config import settings

    result = await db.execute(
        select(NutritionistPatient).where(NutritionistPatient.invite_token == token)
    )
    link = result.scalar_one_or_none()

    bot_username = settings.telegram_bot_username or "Minha_nutri_bot"
    tg_url = f"https://t.me/{bot_username}?start=convite_{token}"

    if not link:
        state = "invalid"
        nutri_name = ""
    elif link.status == "expired" or (
        link.expires_at and datetime.now(ZoneInfo("UTC")) > link.expires_at
    ):
        state = "expired"
        nutri_name = ""
    elif link.status in ("active", "declined", "revoked"):
        state = "used"
        nutri_name = link.patient_name or ""
    else:
        # pending — válido
        state = "valid"
        # Busca nome da nutricionista
        if link.nutritionist_id:
            nutri_result = await db.execute(
                select(User).where(User.id == link.nutritionist_id)
            )
            nutri = nutri_result.scalar_one_or_none()
            nutri_name = nutri.first_name if nutri else "sua nutricionista"
        else:
            nutri_name = "sua nutricionista"

    # Inline HTML — sem template externo para manter simples
    pages = {
        "valid": f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Convite NutriBot</title>
<style>
  body{{margin:0;font-family:'Segoe UI',system-ui,sans-serif;
    background:#F5F7F9;display:flex;align-items:center;justify-content:center;
    min-height:100vh;padding:24px;box-sizing:border-box;}}
  .card{{background:#fff;border-radius:20px;padding:36px 32px;max-width:400px;
    width:100%;text-align:center;box-shadow:0 4px 32px rgba(0,0,0,.08);}}
  .icon{{font-size:3rem;margin-bottom:16px;}}
  h1{{font-size:1.4rem;color:#1C2B3A;margin:0 0 10px;line-height:1.3;}}
  p{{font-size:14.5px;color:#3D5168;line-height:1.6;margin:0 0 24px;}}
  .btn{{display:inline-block;background:#229ED9;color:#fff;
    border-radius:12px;padding:14px 28px;font-size:15px;font-weight:700;
    text-decoration:none;width:100%;box-sizing:border-box;transition:opacity .2s;}}
  .btn:hover{{opacity:.88;}}
  .note{{font-size:12px;color:#6B7E95;margin-top:16px;}}
</style>
</head>
<body>
<div class="card">
  <div class="icon">🥗</div>
  <h1>{nutri_name} quer acompanhar sua alimentação</h1>
  <p>Você foi convidada para receber acompanhamento nutricional personalizado pelo NutriBot.<br>
     Para aceitar ou recusar, abra o bot no Telegram.</p>
  <a class="btn" href="{tg_url}">Abrir no Telegram</a>
  <p class="note">Ao abrir o Telegram, o bot vai explicar o que será compartilhado e pedir sua confirmação.</p>
</div>
</body>
</html>""",

        "expired": """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Convite expirado</title>
<style>
  body{{margin:0;font-family:'Segoe UI',system-ui,sans-serif;
    background:#F5F7F9;display:flex;align-items:center;justify-content:center;
    min-height:100vh;padding:24px;box-sizing:border-box;}}
  .card{{background:#fff;border-radius:20px;padding:36px 32px;max-width:400px;
    width:100%;text-align:center;box-shadow:0 4px 32px rgba(0,0,0,.08);}}
  h1{{font-size:1.4rem;color:#1C2B3A;margin:16px 0 10px;}}
  p{{font-size:14.5px;color:#3D5168;line-height:1.6;margin:0;}}
</style>
</head>
<body>
<div class="card">
  <div style="font-size:3rem">⏰</div>
  <h1>Convite expirado</h1>
  <p>Este link de convite expirou (válido por 7 dias).<br>
     Peça à sua nutricionista que gere um novo convite.</p>
</div>
</body>
</html>""",

        "used": """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Convite já utilizado</title>
<style>
  body{{margin:0;font-family:'Segoe UI',system-ui,sans-serif;
    background:#F5F7F9;display:flex;align-items:center;justify-content:center;
    min-height:100vh;padding:24px;box-sizing:border-box;}}
  .card{{background:#fff;border-radius:20px;padding:36px 32px;max-width:400px;
    width:100%;text-align:center;box-shadow:0 4px 32px rgba(0,0,0,.08);}}
  h1{{font-size:1.4rem;color:#1C2B3A;margin:16px 0 10px;}}
  p{{font-size:14.5px;color:#3D5168;line-height:1.6;margin:0;}}
</style>
</head>
<body>
<div class="card">
  <div style="font-size:3rem">✅</div>
  <h1>Convite já utilizado</h1>
  <p>Este convite já foi respondido anteriormente.<br>
     Se precisar de ajuda, fale com sua nutricionista.</p>
</div>
</body>
</html>""",

        "invalid": """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Convite inválido</title>
<style>
  body{{margin:0;font-family:'Segoe UI',system-ui,sans-serif;
    background:#F5F7F9;display:flex;align-items:center;justify-content:center;
    min-height:100vh;padding:24px;box-sizing:border-box;}}
  .card{{background:#fff;border-radius:20px;padding:36px 32px;max-width:400px;
    width:100%;text-align:center;box-shadow:0 4px 32px rgba(0,0,0,.08);}}
  h1{{font-size:1.4rem;color:#1C2B3A;margin:16px 0 10px;}}
  p{{font-size:14.5px;color:#3D5168;line-height:1.6;margin:0;}}
</style>
</head>
<body>
<div class="card">
  <div style="font-size:3rem">❌</div>
  <h1>Link inválido</h1>
  <p>Este link de convite não é válido ou já foi removido.<br>
     Verifique com sua nutricionista se o link está correto.</p>
</div>
</body>
</html>""",
    }

    html = pages[state]
    status_code = 200 if state == "valid" else (410 if state == "expired" else 404)
    return HTMLResponse(content=html, status_code=status_code)


# ── API — Registro ─────────────────────────────────────────────────────────────

@router.post("/api/nutricionista/register")
async def register_nutritionist(
    request: Request,
    name: str = Form(...),
    crn: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    cpf_cnpj: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Cria conta de nutricionista com trial 30 dias sem cartão.

    Validações:
    - CRN no formato correto (regex — sem consulta CFN no MVP)
    - E-mail único
    - Senha mínima 8 chars
    - CPF/CNPJ não vazio (para NFS-e no B2B-3)
    """
    from app.config import settings as cfg
    from app.utils.rate_limiter import rate_limiter

    client_ip = request.client.host if request.client else "unknown"
    if not await rate_limiter.is_allowed(
        f"nutri_register:{client_ip}", max_requests=5, window_seconds=3600
    ):
        return templates.TemplateResponse(
            request=request,
            name="nutricionista_cadastro.html",
            context={"error": "Muitas tentativas. Aguarde uma hora e tente novamente."},
            status_code=429,
        )

    # Validações
    errors: list[str] = []
    crn_clean = crn.strip().upper()
    if not _CRN_RE.match(crn_clean):
        errors.append("CRN inválido. Use o formato: CRN-3 12345/P")
    if len(password) < 8:
        errors.append("Senha deve ter ao menos 8 caracteres")
    if not cpf_cnpj.strip():
        errors.append("CPF ou CNPJ é obrigatório para emissão de NFS-e")

    if errors:
        return templates.TemplateResponse(
            request=request,
            name="nutricionista_cadastro.html",
            context={"error": " | ".join(errors), "form": {"name": name, "crn": crn, "email": email}},
            status_code=422,
        )

    # E-mail duplicado
    existing = await db.execute(select(User).where(User.email == email.strip().lower()))
    if existing.scalar_one_or_none():
        return templates.TemplateResponse(
            request=request,
            name="nutricionista_cadastro.html",
            context={"error": "E-mail já cadastrado.", "form": {"name": name, "crn": crn}},
            status_code=400,
        )

    trial_end = datetime.now(ZoneInfo("UTC")) + timedelta(days=_TRIAL_DAYS)
    user = User(
        channel_id=f"web:{email.strip().lower()}",
        channel_type="web",
        email=email.strip().lower(),
        password_hash=pwd_context.hash(password),
        first_name=name.strip(),
        plan="nutritionist",
        trial_ends_at=trial_end,
        onboarding_complete=True,
        # CRN e CPF/CNPJ guardados no state_data (sem campo dedicado no MVP)
        state_data={"crn": crn_clean, "cpf_cnpj": cpf_cnpj.strip()},
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id)
    return _cookie_response("/nutricionista/", token, cfg.app_env == "production")


# ── HTML — Painel ──────────────────────────────────────────────────────────────

@router.get("/nutricionista/", response_class=HTMLResponse)
async def painel_nutricionista(
    request: Request,
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Dashboard do nutricionista — lista de pacientes + métricas resumo."""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    if not user.is_nutritionist:
        return RedirectResponse(url="/dashboard", status_code=302)

    # Busca todos os vínculos desta nutricionista
    result = await db.execute(
        select(NutritionistPatient)
        .where(NutritionistPatient.nutritionist_id == user.id)
        .order_by(NutritionistPatient.invited_at.desc())
    )
    links = result.scalars().all()

    active_links = [lk for lk in links if lk.status == "active"]
    pending_links = [lk for lk in links if lk.status == "pending"]

    # Para cada ativo, busca dados do paciente (último registro, média kcal)
    from datetime import timedelta as _td
    from app.models.meal_log import MealLog

    tz = ZoneInfo("America/Sao_Paulo")
    now = datetime.now(tz)
    cutoff_inactive = now - _td(days=3)

    patients_data: list[dict] = []
    for lk in active_links:
        if lk.patient_id is None:
            continue
        pat_result = await db.execute(select(User).where(User.id == lk.patient_id))
        patient = pat_result.scalar_one_or_none()
        if not patient or patient.deleted_at:
            continue

        # Último registro
        last_result = await db.execute(
            select(MealLog)
            .where(MealLog.user_id == lk.patient_id, MealLog.confirmed.is_(True))
            .order_by(MealLog.logged_at.desc())
            .limit(1)
        )
        last_meal = last_result.scalar_one_or_none()
        last_logged_at = last_meal.logged_at if last_meal else None

        # Média kcal últimos 7 dias
        week_start = now - _td(days=7)
        week_result = await db.execute(
            select(MealLog).where(
                MealLog.user_id == lk.patient_id,
                MealLog.confirmed.is_(True),
                MealLog.logged_at >= week_start,
            )
        )
        week_meals = week_result.scalars().all()
        avg_kcal = round(sum(m.total_calories_kcal for m in week_meals) / 7, 0) if week_meals else None

        # Inactive flag: sem registro há mais de 3 dias
        is_inactive = (
            last_logged_at is None
            or last_logged_at.astimezone(tz) < cutoff_inactive
        )

        patients_data.append({
            "link": lk,
            "patient": patient,
            "last_logged_at": last_logged_at,
            "avg_kcal": avg_kcal,
            "is_inactive": is_inactive,
        })

    # Trial: dias restantes
    trial_days_left: int | None = None
    if user.trial_ends_at:
        delta = user.trial_ends_at.replace(tzinfo=None) - datetime.utcnow()
        trial_days_left = max(0, delta.days)

    return templates.TemplateResponse(
        request=request,
        name="nutricionista_painel.html",
        context={
            "user": user,
            "active": "nutricionista",
            "patients_data": patients_data,
            "pending_links": pending_links,
            "active_count": len(active_links),
            "inactive_count": sum(1 for p in patients_data if p["is_inactive"]),
            "pending_count": len(pending_links),
            "trial_days_left": trial_days_left,
            "max_patients": _MAX_PATIENTS,
        },
    )


# ── API — Gerar convite ────────────────────────────────────────────────────────

@router.post("/api/nutricionista/convite")
async def gerar_convite(
    request: Request,
    patient_name: str = Form(...),
    patient_phone: str = Form(default=""),
    patient_telegram: str = Form(default=""),
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Gera token de convite e retorna o deep link para a nutricionista enviar ao paciente.

    Cenário A (paciente novo) — a nutricionista informa o telefone/Telegram e
    copia o link gerado para enviar manualmente (enquanto template Meta não estiver aprovado).
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Não autenticado")
    if not user.is_nutritionist:
        raise HTTPException(status_code=403, detail="Acesso restrito ao plano Nutricionista")

    # Verifica limite de pacientes
    count_result = await db.execute(
        select(NutritionistPatient).where(
            NutritionistPatient.nutritionist_id == user.id,
            NutritionistPatient.status == "active",
        )
    )
    active_count = len(count_result.scalars().all())
    if active_count >= _MAX_PATIENTS:
        raise HTTPException(
            status_code=422,
            detail=f"Limite de {_MAX_PATIENTS} pacientes atingido para o plano atual.",
        )

    if not patient_phone.strip() and not patient_telegram.strip():
        raise HTTPException(
            status_code=422, detail="Informe WhatsApp ou @username do Telegram do paciente."
        )

    token = secrets.token_urlsafe(48)[:64]
    expires = datetime.now(ZoneInfo("UTC")) + timedelta(days=_INVITE_EXPIRY_DAYS)

    link_record = NutritionistPatient(
        nutritionist_id=user.id,
        patient_phone=patient_phone.strip() or None,
        patient_name=patient_name.strip(),
        invite_token=token,
        status="pending",
        expires_at=expires,
    )
    db.add(link_record)
    await db.commit()
    await db.refresh(link_record)

    from app.config import settings
    base = (settings.app_url or "https://nutri-bot-ot0p.onrender.com").rstrip("/")
    invite_url = f"{base}/convite/{token}"

    return JSONResponse({
        "invite_url": invite_url,
        "expires_at": expires.isoformat(),
        "patient_name": patient_name.strip(),
    })


# ── API — Aceitar/recusar convite (chamado pelo bot) ──────────────────────────

@router.patch("/api/nutricionista/convite/{token}")
async def responder_convite(
    token: str,
    aceitar: bool,
    patient_user_id: str,
    include_history: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Endpoint interno chamado pela ConversationService quando o paciente responde SIM/NÃO.

    Não requer cookie JWT — é chamado server-side pelo bot webhook.
    Validação: o token deve existir, estar pending e não ter expirado.
    """
    import uuid as _uuid

    result = await db.execute(
        select(NutritionistPatient).where(NutritionistPatient.invite_token == token)
    )
    link = result.scalar_one_or_none()

    if not link:
        raise HTTPException(status_code=404, detail="Convite não encontrado")
    if link.status != "pending":
        raise HTTPException(status_code=409, detail=f"Convite já processado: {link.status}")
    if datetime.utcnow() > link.expires_at.replace(tzinfo=None):
        link.status = "expired"
        await db.commit()
        raise HTTPException(status_code=410, detail="Convite expirado")

    try:
        patient_uuid = _uuid.UUID(patient_user_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="patient_user_id inválido")

    now_utc = datetime.now(ZoneInfo("UTC"))

    if aceitar:
        link.patient_id = patient_uuid
        link.status = "active"
        link.consented_at = now_utc  # LGPD: registra timestamp do consentimento explícito
    else:
        link.status = "declined"

    await db.commit()
    return {"status": link.status, "consented_at": link.consented_at.isoformat() if link.consented_at else None}


# ── API — Revogar acesso (chamado pelo bot via /privacidade) ──────────────────

@router.patch("/api/nutricionista/revogar/{link_id}")
async def revogar_acesso(
    link_id: str,
    patient_user_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Revoga o acesso de uma nutricionista pelo paciente (LGPD — direito de revogação).

    Chamado pela ConversationService quando o paciente confirma a revogação.
    """
    import uuid as _uuid

    try:
        link_uuid = _uuid.UUID(link_id)
        patient_uuid = _uuid.UUID(patient_user_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="IDs inválidos")

    result = await db.execute(
        select(NutritionistPatient).where(
            NutritionistPatient.id == link_uuid,
            NutritionistPatient.patient_id == patient_uuid,
        )
    )
    link = result.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Vínculo não encontrado")
    if link.status != "active":
        raise HTTPException(status_code=409, detail="Vínculo não está ativo")

    link.status = "revoked"
    link.revoked_at = datetime.now(ZoneInfo("UTC"))
    await db.commit()
    return {"status": "revoked"}


# ── API — Lista pacientes (JSON para uso futuro / B2B-2) ─────────────────────

@router.get("/api/nutricionista/pacientes")
async def listar_pacientes(
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Lista pacientes ativos da nutricionista (JSON)."""
    nutri = _require_nutritionist(user)

    result = await db.execute(
        select(NutritionistPatient).where(
            NutritionistPatient.nutritionist_id == nutri.id,
            NutritionistPatient.status == "active",
        )
    )
    links = result.scalars().all()

    patients = []
    for lk in links:
        if not lk.patient_id:
            continue
        pat_result = await db.execute(select(User).where(User.id == lk.patient_id))
        patient = pat_result.scalar_one_or_none()
        if patient and not patient.deleted_at:
            patients.append({
                "link_id": str(lk.id),
                "patient_id": str(patient.id),
                "name": patient.first_name or "Paciente",
                "consented_at": lk.consented_at.isoformat() if lk.consented_at else None,
            })

    return {"patients": patients, "total": len(patients)}


# ── B2B-2: Perfil do paciente ─────────────────────────────────────────────────

@router.get("/nutricionista/paciente/{patient_id}", response_class=HTMLResponse)
async def perfil_paciente(
    patient_id: str,
    request: Request,
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Perfil completo do paciente: gráfico 30 dias, registros diários, notas clínicas."""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    if not user.is_nutritionist:
        return RedirectResponse(url="/dashboard", status_code=302)

    import uuid as _uuid
    try:
        pid = _uuid.UUID(patient_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="ID inválido")

    # Verifica vínculo ativo
    link_result = await db.execute(
        select(NutritionistPatient).where(
            NutritionistPatient.nutritionist_id == user.id,
            NutritionistPatient.patient_id == pid,
            NutritionistPatient.status == "active",
        )
    )
    link = link_result.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=403, detail="Sem acesso a este paciente")

    pat_result = await db.execute(select(User).where(User.id == pid))
    patient = pat_result.scalar_one_or_none()
    if not patient or patient.deleted_at:
        raise HTTPException(status_code=404, detail="Paciente não encontrado")

    from datetime import timedelta as _td
    from app.models.meal_log import MealLog
    from sqlalchemy.orm import selectinload

    tz = ZoneInfo("America/Sao_Paulo")
    now = datetime.now(tz)
    today = now.date()

    # ── Gráfico kcal — últimos 30 dias ────────────────────────────────────────
    chart_labels: list[str] = []
    chart_kcal: list[float] = []
    for i in range(29, -1, -1):
        d = today - _td(days=i)
        ds = datetime(d.year, d.month, d.day, 0, 0, tzinfo=tz)
        de = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=tz)
        r = await db.execute(
            select(MealLog).where(
                MealLog.user_id == pid,
                MealLog.confirmed.is_(True),
                MealLog.logged_at >= ds,
                MealLog.logged_at <= de,
            )
        )
        day_meals = r.scalars().all()
        chart_labels.append(d.strftime("%d/%m"))
        chart_kcal.append(round(sum(m.total_calories_kcal for m in day_meals), 1))

    # ── Registros por dia — últimos 30 dias ───────────────────────────────────
    period_start = datetime(
        (today - _td(days=29)).year,
        (today - _td(days=29)).month,
        (today - _td(days=29)).day,
        0, 0, tzinfo=tz,
    )
    all_logs_result = await db.execute(
        select(MealLog)
        .options(selectinload(MealLog.food_items))
        .where(
            MealLog.user_id == pid,
            MealLog.confirmed.is_(True),
            MealLog.logged_at >= period_start,
        )
        .order_by(MealLog.logged_at.desc())
    )
    all_logs = all_logs_result.scalars().all()

    # Agrupa por data
    from collections import defaultdict
    days_map: dict = defaultdict(list)
    for log in all_logs:
        d = log.logged_at.astimezone(tz).date()
        days_map[d].append(log)
    days_sorted = sorted(days_map.keys(), reverse=True)

    _MEAL_LABELS = {
        "breakfast": "☀️ Café",
        "morning_snack": "🍌 Lanche manhã",
        "lunch": "🍽️ Almoço",
        "afternoon_snack": "🍊 Lanche tarde",
        "dinner": "🌙 Jantar",
        "snack": "🍎 Lanche",
        "other": "🍴 Outro",
    }

    # ── Notas clínicas — mais recentes primeiro ────────────────────────────────
    notes_result = await db.execute(
        select(ClinicalNote)
        .where(
            ClinicalNote.nutritionist_id == user.id,
            ClinicalNote.patient_id == pid,
        )
        .order_by(ClinicalNote.consultation_date.desc())
    )
    notes = notes_result.scalars().all()

    # ── Resumo 7 dias ─────────────────────────────────────────────────────────
    week_kcal = sum(chart_kcal[-7:])
    days_with_data = sum(1 for v in chart_kcal[-7:] if v > 0)
    avg_kcal_7d = round(week_kcal / days_with_data) if days_with_data else 0

    return templates.TemplateResponse(
        request=request,
        name="nutricionista_paciente.html",
        context={
            "user": user,
            "patient": patient,
            "link": link,
            "chart_labels": chart_labels,
            "chart_kcal": chart_kcal,
            "days_sorted": days_sorted,
            "days_map": dict(days_map),
            "meal_labels": _MEAL_LABELS,
            "notes": notes,
            "avg_kcal_7d": avg_kcal_7d,
            "days_with_data_7d": days_with_data,
            "goal_kcal": patient.daily_calorie_goal,
        },
    )


# ── B2B-2: Adicionar nota clínica ────────────────────────────────────────────

@router.post("/api/nutricionista/paciente/{patient_id}/nota")
async def adicionar_nota(
    patient_id: str,
    note_text: str = Form(...),
    consultation_date: str = Form(...),
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Adiciona nota clínica vinculada a uma data de consulta.
    Escrita exclusiva da nutricionista — o paciente não vê esta nota.
    """
    nutri = _require_nutritionist(user)

    import uuid as _uuid
    from datetime import date as _date

    try:
        pid = _uuid.UUID(patient_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="ID inválido")

    try:
        consult_date = _date.fromisoformat(consultation_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="Data inválida (use YYYY-MM-DD)")

    if consult_date > _date.today():
        raise HTTPException(status_code=422, detail="Data de consulta não pode ser futura")

    if not note_text.strip():
        raise HTTPException(status_code=422, detail="Nota não pode estar vazia")

    # Verifica vínculo ativo
    link_result = await db.execute(
        select(NutritionistPatient).where(
            NutritionistPatient.nutritionist_id == nutri.id,
            NutritionistPatient.patient_id == pid,
            NutritionistPatient.status == "active",
        )
    )
    if not link_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Sem vínculo ativo com este paciente")

    note = ClinicalNote(
        nutritionist_id=nutri.id,
        patient_id=pid,
        note_text=note_text.strip(),
        consultation_date=consult_date,
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)

    return JSONResponse({
        "id": str(note.id),
        "consultation_date": note.consultation_date.isoformat(),
        "note_text": note.note_text,
        "created_at": note.created_at.isoformat(),
    }, status_code=201)


# ── B2B-2: Download PDF do paciente ──────────────────────────────────────────

@router.get("/api/nutricionista/paciente/{patient_id}/pdf")
async def baixar_pdf_paciente(
    patient_id: str,
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Gera e retorna o PDF dos últimos 30 dias do paciente.

    Reutiliza report_service.generate_report() existente.
    O PDF não é salvo no banco (save=False) — geração sob demanda.
    """
    from datetime import date as _date, timedelta as _td
    from fastapi.responses import Response as _Response
    from app.services.report import report_service

    nutri = _require_nutritionist(user)

    import uuid as _uuid
    try:
        pid = _uuid.UUID(patient_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="ID inválido")

    # Verifica vínculo ativo
    link_result = await db.execute(
        select(NutritionistPatient).where(
            NutritionistPatient.nutritionist_id == nutri.id,
            NutritionistPatient.patient_id == pid,
            NutritionistPatient.status == "active",
        )
    )
    if not link_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Sem vínculo ativo com este paciente")

    pat_result = await db.execute(select(User).where(User.id == pid))
    patient = pat_result.scalar_one_or_none()
    if not patient or patient.deleted_at:
        raise HTTPException(status_code=404, detail="Paciente não encontrado")

    end_date = _date.today()
    start_date = end_date - _td(days=29)

    try:
        file_bytes, ext = await report_service.generate_report(
            user=patient,
            start_date=start_date,
            end_date=end_date + _td(days=1),
            period_type="monthly",
            db=db,
            save=False,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao gerar PDF: {e}")

    media_type = "application/pdf" if ext == "pdf" else "text/html"
    fname = f"nutribot_{patient.first_name or 'paciente'}_{end_date.strftime('%Y-%m-%d')}.{ext}"
    return _Response(
        content=file_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
