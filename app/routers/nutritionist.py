"""Painel B2B Nutricionistas — Sprint B2B-1 + B2B-2 + Fase 3 (RF-PAINEL-01 a 11).

Rotas HTML (Jinja2):
  GET  /nutricionista/cadastro              — tela de cadastro
  GET  /nutricionista/                      — painel (requer plano 'nutritionist')
  GET  /nutricionista/paciente/{id}         — perfil do paciente (B2B-2)

Rotas API:
  POST   /api/nutricionista/register                    — cria conta nutricionista (trial 30d)
  POST   /api/nutricionista/convite                     — gera convite para paciente
  PATCH  /api/nutricionista/convite/{token}             — aceita/recusa convite (chamado pelo bot)
  PATCH  /api/nutricionista/convite/{id}/renovar        — RF-PAINEL-07: renova convite expirado
  PATCH  /api/nutricionista/revogar/{id}                — revogação LGPD (chamado pelo bot)
  DELETE /api/nutricionista/convite/{id}                — exclui convite expirado
  GET    /api/nutricionista/pacientes                   — lista pacientes ativos (JSON)
  GET    /api/nutricionista/pacientes/csv               — RF-PAINEL-09: exporta CSV
  POST   /api/nutricionista/paciente/{id}/nota          — adiciona nota clínica (B2B-2)
  GET    /api/nutricionista/paciente/{id}/pdf?days=N    — RF-PAINEL-08: PDF com período customizável
  PATCH  /api/nutricionista/paciente/{id}/alerta-config — RF-PAINEL-11: configura limiar de alerta

Autenticação: cookie JWT reutilizado do sistema existente.
O login em /auth/login-form já redireciona para /nutricionista/ quando plan='nutritionist'.
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
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

# ── Mapa objetivo → rótulo PT-BR ─────────────────────────────────────────────
_GOAL_LABELS: dict[str, tuple[str, str]] = {
    "perder_peso":   ("🎯", "Perder peso"),
    "ganhar_massa":  ("💪", "Ganhar massa muscular"),
    "manter":        ("⚖️", "Manter o peso"),
}


async def _gerar_analise_ia(
    patient_name: str,
    goal_type: str | None,
    goal_label: str,
    avg_kcal: int,
    goal_kcal: int,
    avg_prot: float,
    avg_carb: float,
    avg_fat: float,
    avg_fiber: float,
    days_with_data: int,
    total_days: int,
    days_on_goal: int,
    notes_texts: list[str],
) -> dict:
    """Gera análise clínica via Claude: positivos, negativos e sugestões.

    Retorna dict com chaves positivos / negativos / sugestoes (listas de str).
    Em caso de falha (API indisponível, timeout) retorna dicionário vazio para não
    bloquear a geração do PDF.
    """
    import json as _json

    try:
        import anthropic as _anthropic
        from app.config import settings as _settings

        adh_pct = int(days_with_data / total_days * 100) if total_days else 0
        goal_pct = int(days_on_goal / days_with_data * 100) if days_with_data else 0

        notas_txt = ""
        if notes_texts:
            notas_txt = "\n".join(f"- {n}" for n in notes_texts[:5])
            notas_txt = f"\nANOTAÇÕES CLÍNICAS DA NUTRICIONISTA:\n{notas_txt}"

        prompt = (
            f"Analise os dados nutricionais de {patient_name} nos últimos 30 dias e gere "
            f"uma avaliação clínica estruturada em português brasileiro.\n\n"
            f"OBJETIVO DO PACIENTE: {goal_label or 'não informado'}\n"
            f"DADOS DO PERÍODO:\n"
            f"- Média calórica: {avg_kcal} kcal/dia (meta: {goal_kcal} kcal)\n"
            f"- Proteínas: {avg_prot}g/dia\n"
            f"- Carboidratos: {avg_carb}g/dia\n"
            f"- Gorduras: {avg_fat}g/dia\n"
            f"- Fibras: {avg_fiber}g/dia (DRI: 25g)\n"
            f"- Dias com registro: {days_with_data}/{total_days} ({adh_pct}% aderência)\n"
            f"- Dias dentro da meta calórica (±15%): {days_on_goal} ({goal_pct}%)"
            f"{notas_txt}\n\n"
            "Gere exatamente:\n"
            "- 2 a 3 PONTOS POSITIVOS (campo 'positivos'): conquistas concretas, baseadas nos números.\n"
            "- 2 a 3 PONTOS DE ATENÇÃO (campo 'negativos'): o que precisa melhorar, sem ser punitivo.\n"
            "- 2 a 3 SUGESTÕES (campo 'sugestoes'): ações práticas e específicas alinhadas ao objetivo "
            f"'{goal_label}'. Cite alimentos, hábitos ou ajustes concretos.\n\n"
            "Se existirem anotações clínicas, considere-as nas sugestões.\n"
            "Responda SOMENTE com JSON válido, sem markdown nem texto extra.\n"
            'SCHEMA: {"positivos":["string"],"negativos":["string"],"sugestoes":["string"]}'
        )

        client = _anthropic.AsyncAnthropic(api_key=_settings.anthropic_api_key)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=900,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # Remove markdown fences se presentes
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = _json.loads(raw)
        return {
            "positivos":  [str(s) for s in data.get("positivos", [])],
            "negativos":  [str(s) for s in data.get("negativos", [])],
            "sugestoes":  [str(s) for s in data.get("sugestoes", [])],
        }
    except Exception as exc:
        logger.warning("[PDF-NUTRI] Análise IA falhou (%s) — PDF sem análise IA", exc)
        return {}

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

    bot_username = settings.telegram_bot_username or "NutriBotOficialBot"
    if not settings.telegram_bot_username:
        logger.warning("[CONVITE] TELEGRAM_BOT_USERNAME não configurado — usando fallback")
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

@router.get("/api/nutricionista/debug/columns")
async def debug_columns(
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """Retorna colunas reais de nutritionist_patients no banco.
    Rota temporária de diagnóstico — requer login de nutricionista."""
    from sqlalchemy import text as _text
    import traceback as _tb
    if user is None:
        return JSONResponse({"error": "não autenticado"}, status_code=401)
    try:
        r = await db.execute(_text(
            "SELECT column_name, data_type, column_default "
            "FROM information_schema.columns "
            "WHERE table_name='nutritionist_patients' "
            "ORDER BY ordinal_position"
        ))
        cols = [dict(row._mapping) for row in r.all()]
        v = await db.execute(_text("SELECT version_num FROM alembic_version"))
        ver = [row[0] for row in v.all()]
        return JSONResponse({"columns": cols, "alembic_version": ver})
    except Exception as exc:
        return JSONResponse({"error": str(exc), "trace": _tb.format_exc()}, status_code=500)


@router.get("/nutricionista/", response_class=HTMLResponse)
async def painel_nutricionista(
    request: Request,
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Dashboard do nutricionista — lista de pacientes + métricas resumo."""
    import traceback as _tb
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    if not user.is_nutritionist:
        return RedirectResponse(url="/dashboard", status_code=302)

    try:
        return await _painel_nutricionista_inner(request, user, db)
    except Exception as exc:
        logger.error("PAINEL /nutricionista/ ERRO: %s\n%s", exc, _tb.format_exc())
        # Mostra erro detalhado para a nutricionista autenticada (não exposto publicamente)
        return HTMLResponse(
            f"<h2>Erro interno no painel</h2>"
            f"<p>Por favor copie a mensagem abaixo e envie ao suporte:</p>"
            f"<pre style='background:#f3f4f6;padding:16px;border-radius:8px;"
            f"font-size:13px;overflow:auto;max-height:80vh'>"
            f"TIPO: {type(exc).__name__}\n"
            f"MENSAGEM: {exc}\n\n"
            f"TRACEBACK:\n{_tb.format_exc()}"
            f"</pre>",
            status_code=500,
        )


async def _painel_nutricionista_inner(
    request: Request,
    user: User,
    db: AsyncSession,
) -> HTMLResponse:
    """Lógica interna do painel — separada para captura de erros na rota pai."""
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
    # cutoff_inactive é calculado por paciente usando lk.inactivity_alert_days (RF-PAINEL-11)

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

        # Média kcal + dias únicos últimos 7 dias (para dashboard engajamento)
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
        week_dates = {m.logged_at.astimezone(tz).date() for m in week_meals}
        days_with_data_7d = len(week_dates)

        # RF-PAINEL-05 — Aderência 30 dias + streak
        month_start = now - _td(days=29)
        month_result = await db.execute(
            select(MealLog.logged_at).where(
                MealLog.user_id == lk.patient_id,
                MealLog.confirmed.is_(True),
                MealLog.logged_at >= month_start,
            )
        )
        month_dates = {row[0].astimezone(tz).date() for row in month_result.all()}
        adh_30d = round(len(month_dates) / 30 * 100)
        streak = 0
        _chk = now.date()
        while _chk in month_dates and streak <= 30:
            streak += 1
            _chk -= _td(days=1)

        # Inactive flag: usa limiar configurado por paciente (RF-PAINEL-11), padrão 3 dias
        _alert_days = getattr(lk, "inactivity_alert_days", 3) or 3
        cutoff_inactive = now - _td(days=_alert_days)
        is_inactive = (
            last_logged_at is None
            or last_logged_at.astimezone(tz) < cutoff_inactive
        )

        patients_data.append({
            "link": lk,
            "patient": patient,
            "last_logged_at": last_logged_at,
            "avg_kcal": avg_kcal,
            "days_with_data_7d": days_with_data_7d,
            "week_dates": week_dates,        # RF-PAINEL-06
            "adh_30d": adh_30d,             # RF-PAINEL-05
            "streak": streak,               # RF-PAINEL-05
            "is_inactive": is_inactive,
        })

    # RF-PAINEL-06 — Engajamento diário: quantos pacientes registraram cada dia (últimos 7)
    _labels_pt = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    daily_engagement = []
    total_patients = len(patients_data)
    for _i in range(6, -1, -1):
        _day = now.date() - _td(days=_i)
        _count = sum(1 for p in patients_data if _day in p["week_dates"])
        daily_engagement.append({
            "label": _labels_pt[_day.weekday()],
            "date": _day.strftime("%d/%m"),
            "count": _count,
            "total": total_patients,
            "pct": round(_count / total_patients * 100) if total_patients else 0,
        })

    from app.config import settings as _settings
    _base = (_settings.app_url or "https://nutri-bot-ot0p.onrender.com").rstrip("/")

    return templates.TemplateResponse(
        request=request,
        name="nutricionista_painel.html",
        context={
            "user": user,
            "active": "nutricionista",
            "patients_data": patients_data,
            "pending_links": pending_links,
            "expired_links": [lk for lk in links if lk.status == "expired"],
            "declined_links": [lk for lk in links if lk.status == "declined"],
            "revoked_links":  [lk for lk in links if lk.status == "revoked"],
            "active_count": len(active_links),
            "inactive_count": sum(1 for p in patients_data if p["is_inactive"]),
            "pending_count": len(pending_links),
            "max_patients": _MAX_PATIENTS,
            "base_url": _base,
            "daily_engagement": daily_engagement,  # RF-PAINEL-06
            # now_utc (naive) usado no template para calcular "X dias atrás"
            "now_utc": datetime.utcnow(),
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


# ── Meta e Objetivo do Paciente ──────────────────────────────────────────────

_VALID_GOAL_TYPES = {"perder_peso", "ganhar_massa", "manter", ""}

@router.patch("/api/nutricionista/paciente/{patient_id}/meta")
async def configurar_meta_paciente(
    patient_id: str,
    goal_type: str = Form(default=""),
    daily_calorie_goal: int | None = Form(default=None),
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Nutricionista define/ajusta objetivo e meta calórica do paciente.

    - goal_type: perder_peso | ganhar_massa | manter | "" (limpa)
    - daily_calorie_goal: inteiro 800–5000 kcal ou omitido (não altera)

    A alteração é gravada diretamente em users.goal_type e
    users.daily_calorie_goal, refletindo imediatamente nos gráficos,
    relatório PDF e análise de IA.
    """
    nutri = _require_nutritionist(user)

    import uuid as _uuid
    try:
        pid = _uuid.UUID(patient_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="ID inválido")

    if goal_type not in _VALID_GOAL_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"goal_type inválido. Use: {', '.join(sorted(_VALID_GOAL_TYPES - {''}))}"
        )

    if daily_calorie_goal is not None and not (800 <= daily_calorie_goal <= 5000):
        raise HTTPException(
            status_code=422, detail="daily_calorie_goal deve estar entre 800 e 5000"
        )

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

    if goal_type != "" or goal_type == "":
        # Sempre atualiza goal_type (inclusive para limpar com "")
        patient.goal_type = goal_type or None

    if daily_calorie_goal is not None:
        patient.daily_calorie_goal = daily_calorie_goal

    await db.commit()
    logger.info(
        "[META-PACIENTE] nutri=%s paciente=%s goal_type=%r kcal=%s",
        nutri.id, pid, goal_type, daily_calorie_goal,
    )
    return JSONResponse({
        "ok": True,
        "goal_type": patient.goal_type,
        "daily_calorie_goal": patient.daily_calorie_goal,
    })


# ── B2B-2: Download PDF do paciente (enriquecido) ────────────────────────────

@router.get("/api/nutricionista/paciente/{patient_id}/pdf")
async def baixar_pdf_paciente(
    patient_id: str,
    days: int = Query(30, ge=7, le=90, description="Período do relatório em dias (7–90, padrão 30)"),
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Gera PDF clínico do paciente para o período solicitado (RF-PAINEL-08).

    Query param:
      ?days=N  — período em dias (7–90, padrão 30)

    Usa template dedicado (data/report_nutri_template.html) com:
    - Resumo executivo (kcal, aderência, meta)
    - Macronutrientes (média proteína/carb/gordura)
    - Calendário de aderência N dias
    - Top alimentos consumidos
    - Notas clínicas da nutricionista
    - Histórico diário detalhado (kcal + macros por refeição)
    """
    import uuid as _uuid
    from collections import Counter, defaultdict
    from datetime import date as _date, timedelta as _td
    from pathlib import Path as _Path

    from fastapi.responses import Response as _Response
    from jinja2 import Environment, FileSystemLoader
    from sqlalchemy.orm import selectinload

    from app.models.meal_log import MealLog

    nutri = _require_nutritionist(user)

    try:
        pid = _uuid.UUID(patient_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="ID inválido")

    # ── Verifica vínculo ativo ────────────────────────────────────────────────
    link_result = await db.execute(
        select(NutritionistPatient).where(
            NutritionistPatient.nutritionist_id == nutri.id,
            NutritionistPatient.patient_id == pid,
            NutritionistPatient.status == "active",
        )
    )
    link = link_result.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=403, detail="Sem vínculo ativo com este paciente")

    pat_result = await db.execute(select(User).where(User.id == pid))
    patient = pat_result.scalar_one_or_none()
    if not patient or patient.deleted_at:
        raise HTTPException(status_code=404, detail="Paciente não encontrado")

    tz = ZoneInfo("America/Sao_Paulo")
    today = datetime.now(tz).date()
    end_date = today
    start_date = today - _td(days=days - 1)   # RF-PAINEL-08: respeita ?days=N
    total_days = days

    # ── Busca todos os registros dos últimos 30 dias ──────────────────────────
    period_start = datetime(start_date.year, start_date.month, start_date.day, 0, 0, tzinfo=tz)
    period_end   = datetime(end_date.year,  end_date.month,  end_date.day,  23, 59, 59, tzinfo=tz)

    all_logs_result = await db.execute(
        select(MealLog)
        .options(selectinload(MealLog.food_items))
        .where(
            MealLog.user_id == pid,
            MealLog.confirmed.is_(True),
            MealLog.logged_at >= period_start,
            MealLog.logged_at <= period_end,
        )
        .order_by(MealLog.logged_at.asc())
    )
    all_logs = all_logs_result.scalars().all()

    # ── Agrupa por data ───────────────────────────────────────────────────────
    days_map: dict = defaultdict(list)
    for log in all_logs:
        d = log.logged_at.astimezone(tz).date()
        days_map[d].append(log)
    days_sorted = sorted(days_map.keys(), reverse=True)

    # ── Calendário de 30 dias (para grid visual) ──────────────────────────────
    chart_days = []
    for i in range(total_days):
        d = start_date + _td(days=i)
        logs_day = days_map.get(d, [])
        day_kcal = round(sum(m.total_calories_kcal for m in logs_day), 0) if logs_day else 0.0
        chart_days.append({"label": d.strftime("%d/%m"), "day_num": d.day, "kcal": day_kcal})

    # ── Métricas agregadas ────────────────────────────────────────────────────
    days_with_data = sum(1 for item in chart_days if item["kcal"] > 0)
    goal_kcal = patient.daily_calorie_goal or 2000

    all_kcal  = [m.total_calories_kcal              for m in all_logs]
    all_prot  = [m.total_protein_g                 for m in all_logs]
    all_carb  = [m.total_carb_g                    for m in all_logs]
    all_fat   = [m.total_fat_g                     for m in all_logs]
    all_fiber = [getattr(m, "total_fiber_g", 0.0)  for m in all_logs]

    avg_kcal_30d  = round(sum(all_kcal)  / days_with_data)    if days_with_data else 0
    avg_prot_30d  = round(sum(all_prot)  / days_with_data, 1) if days_with_data else 0.0
    avg_carb_30d  = round(sum(all_carb)  / days_with_data, 1) if days_with_data else 0.0
    avg_fat_30d   = round(sum(all_fat)   / days_with_data, 1) if days_with_data else 0.0
    avg_fiber_30d = round(sum(all_fiber) / days_with_data, 1) if days_with_data else 0.0
    goal_fiber = 25  # DRI: 25 g/dia

    days_on_goal = sum(
        1 for item in chart_days
        if item["kcal"] > 0 and goal_kcal * 0.85 <= item["kcal"] <= goal_kcal * 1.15
    )

    # Metas de macros estimadas a partir da meta calórica (referência geral)
    # P 25% · C 50% · G 25% (perfil default)
    goal_prot = round(goal_kcal * 0.25 / 4)   # kcal → g (4 kcal/g)
    goal_carb = round(goal_kcal * 0.50 / 4)
    goal_fat  = round(goal_kcal * 0.25 / 9)   # kcal → g (9 kcal/g)

    # ── Top alimentos ─────────────────────────────────────────────────────────
    food_counter: Counter = Counter()
    food_kcal_sum: dict[str, float] = defaultdict(float)
    for log in all_logs:
        for fi in log.food_items:
            name = (fi.name or "").strip().lower()
            if name:
                food_counter[name] += 1
                food_kcal_sum[name] += fi.calories_kcal or 0.0

    top_raw = food_counter.most_common(10)
    max_count = top_raw[0][1] if top_raw else 1
    top_foods = [
        {
            "name": name.capitalize(),
            "count": cnt,
            "avg_kcal": round(food_kcal_sum[name] / cnt, 0) if cnt else 0,
            "freq_pct": int(cnt / max_count * 100),
        }
        for name, cnt in top_raw
    ]

    # ── Notas clínicas ────────────────────────────────────────────────────────
    notes_result = await db.execute(
        select(ClinicalNote)
        .where(
            ClinicalNote.nutritionist_id == nutri.id,
            ClinicalNote.patient_id == pid,
        )
        .order_by(ClinicalNote.consultation_date.desc())
    )
    notes = notes_result.scalars().all()

    # ── Resumo semanal — macros por semana (4 semanas × 7 dias) ──────────────
    weekly_breakdown = []
    for week_i in range(4):
        wstart = start_date + _td(days=week_i * 7)
        wend   = min(wstart + _td(days=7), end_date + _td(days=1))
        week_logs = [
            l for l in all_logs
            if wstart <= l.logged_at.astimezone(tz).date() < wend
        ]
        week_days = len({l.logged_at.astimezone(tz).date() for l in week_logs})
        if week_days:
            w_kcal  = round(sum(l.total_calories_kcal              for l in week_logs) / week_days)
            w_prot  = round(sum(l.total_protein_g                  for l in week_logs) / week_days, 1)
            w_carb  = round(sum(l.total_carb_g                     for l in week_logs) / week_days, 1)
            w_fat   = round(sum(l.total_fat_g                      for l in week_logs) / week_days, 1)
            w_fiber = round(sum(getattr(l, "total_fiber_g", 0.0)   for l in week_logs) / week_days, 1)
            macro_kcal = w_prot * 4 + w_carb * 4 + w_fat * 9
            pct_prot = round(w_prot * 4 / macro_kcal * 100) if macro_kcal else 0
            pct_carb = round(w_carb * 4 / macro_kcal * 100) if macro_kcal else 0
            pct_fat  = round(w_fat  * 9 / macro_kcal * 100) if macro_kcal else 0
        else:
            w_kcal = w_prot = w_carb = w_fat = w_fiber = 0
            pct_prot = pct_carb = pct_fat = 0
        wend_display = min(wstart + _td(days=6), end_date)
        weekly_breakdown.append({
            "label":     f"Sem. {week_i + 1} ({wstart.strftime('%d/%m')}–{wend_display.strftime('%d/%m')})",
            "days":      week_days,
            "avg_kcal":  w_kcal,
            "avg_prot":  w_prot,
            "avg_carb":  w_carb,
            "avg_fat":   w_fat,
            "avg_fiber": w_fiber,
            "pct_prot":  pct_prot,
            "pct_carb":  pct_carb,
            "pct_fat":   pct_fat,
        })

    # ── Objetivo do paciente ──────────────────────────────────────────────────
    _goal_icon, _goal_label = _GOAL_LABELS.get(
        patient.goal_type or "", ("📋", "Não informado")
    )

    # ── Análise de IA ─────────────────────────────────────────────────────────
    notes_texts = [n.note_text for n in notes]
    ai_analysis = await _gerar_analise_ia(
        patient_name=patient.first_name or link.patient_name or "Paciente",
        goal_type=patient.goal_type,
        goal_label=_goal_label,
        avg_kcal=avg_kcal_30d,
        goal_kcal=goal_kcal,
        avg_prot=avg_prot_30d,
        avg_carb=avg_carb_30d,
        avg_fat=avg_fat_30d,
        avg_fiber=avg_fiber_30d,
        days_with_data=days_with_data,
        total_days=total_days,
        days_on_goal=days_on_goal,
        notes_texts=notes_texts,
    )

    # ── Renderiza template HTML ───────────────────────────────────────────────
    template_dir = _Path(__file__).parent.parent.parent / "data"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=False)
    tmpl = env.get_template("report_nutri_template.html")

    html_content = tmpl.render(
        patient_name=patient.first_name or link.patient_name or "Paciente",
        nutritionist_name=nutri.first_name or nutri.email or "Nutricionista",
        period_label=f"{start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}",
        generated_at=datetime.now(tz).strftime("%d/%m/%Y %H:%M"),
        total_days=total_days,
        days_with_data=days_with_data,
        days_on_goal=days_on_goal,
        avg_kcal_30d=avg_kcal_30d,
        avg_prot_30d=avg_prot_30d,
        avg_carb_30d=avg_carb_30d,
        avg_fat_30d=avg_fat_30d,
        avg_fiber_30d=avg_fiber_30d,
        goal_fiber=goal_fiber,
        goal_kcal=goal_kcal,
        goal_prot=goal_prot,
        goal_carb=goal_carb,
        goal_fat=goal_fat,
        goal_type=patient.goal_type or "",
        goal_label=_goal_label,
        goal_icon=_goal_icon,
        ai_analysis=ai_analysis,
        chart_days=chart_days,
        top_foods=top_foods,
        notes=notes,
        weekly_breakdown=weekly_breakdown,
    )

    # ── Gera PDF com WeasyPrint ───────────────────────────────────────────────
    try:
        import weasyprint as _wp  # type: ignore
        pdf_bytes = _wp.HTML(string=html_content, base_url=str(template_dir)).write_pdf()
        media_type = "application/pdf"
        ext = "pdf"
        file_bytes = pdf_bytes
    except Exception as wp_err:
        logger.warning("[PDF-NUTRI] WeasyPrint falhou (%s) — entregando HTML", wp_err)
        media_type = "text/html; charset=utf-8"
        ext = "html"
        file_bytes = html_content.encode()

    fname_safe = (patient.first_name or "paciente").replace(" ", "_").lower()
    fname = f"nutribot_relatorio_{fname_safe}_{end_date.strftime('%Y-%m-%d')}.{ext}"
    from fastapi.responses import Response as _Response
    return _Response(
        content=file_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ── RF-PAINEL-07: PATCH renovar convite expirado ──────────────────────────────

@router.patch("/api/nutricionista/convite/{link_id}/renovar")
async def renovar_convite_expirado(
    link_id: str,
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Renova um convite expirado: gera novo token e estende a validade por 7 dias.

    Status volta para 'pending'; todos os outros campos (nome, telefone) são preservados.
    Apenas o nutricionista dono do convite pode renová-lo.
    """
    nutri = _require_nutritionist(user)

    result = await db.execute(
        select(NutritionistPatient).where(NutritionistPatient.id == link_id)
    )
    link = result.scalar_one_or_none()

    if link is None:
        raise HTTPException(status_code=404, detail="Convite não encontrado.")
    if str(link.nutritionist_id) != str(nutri.id):
        raise HTTPException(status_code=403, detail="Sem permissão para renovar este convite.")
    if link.status != "expired":
        raise HTTPException(
            status_code=422,
            detail=f"Apenas convites expirados podem ser renovados (status atual: '{link.status}').",
        )

    link.invite_token = secrets.token_urlsafe(32)
    link.status = "pending"
    link.invited_at = datetime.utcnow()
    link.expires_at = datetime.utcnow() + timedelta(days=7)
    await db.commit()

    from app.config import settings as _settings
    _base = (_settings.app_url or "https://nutri-bot-ot0p.onrender.com").rstrip("/")
    invite_url = f"{_base}/convite/{link.invite_token}"

    logger.info(
        "[CONVITE] Nutricionista %s renovou convite %s (%s) → novo token",
        nutri.id, link_id, link.patient_name,
    )
    return JSONResponse({"ok": True, "invite_url": invite_url, "message": "Convite renovado com sucesso."})


# ── DELETE convite expirado ────────────────────────────────────────────────────

@router.delete("/api/nutricionista/convite/{link_id}")
async def excluir_convite_expirado(
    link_id: str,
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Remove um convite expirado (status='expired') do banco de dados.

    Apenas o nutricionista dono do convite pode excluí-lo, e somente
    se o convite estiver com status 'expired'.
    """
    nutri = _require_nutritionist(user)

    result = await db.execute(
        select(NutritionistPatient).where(NutritionistPatient.id == link_id)
    )
    link = result.scalar_one_or_none()

    if link is None:
        raise HTTPException(status_code=404, detail="Convite não encontrado.")

    if str(link.nutritionist_id) != str(nutri.id):
        raise HTTPException(status_code=403, detail="Sem permissão para excluir este convite.")

    if link.status != "expired":
        raise HTTPException(
            status_code=400,
            detail=f"Apenas convites expirados podem ser excluídos (status atual: '{link.status}').",
        )

    await db.delete(link)
    await db.commit()

    logger.info("[CONVITE] Nutricionista %s excluiu convite expirado %s (%s)", nutri.id, link_id, link.patient_name)
    return JSONResponse({"ok": True, "message": "Convite excluído com sucesso."})


# ── RF-PAINEL-09: GET exportar lista de pacientes (CSV) ───────────────────────

@router.get("/api/nutricionista/pacientes/csv")
async def exportar_pacientes_csv(
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Exporta lista de pacientes ativos com métricas de aderência em CSV (UTF-8 BOM).

    Colunas: nome, telefone, objetivo, data_vinculo, aderencia_7d_pct,
             aderencia_30d_pct, streak, ultima_refeicao, media_kcal_7d
    """
    import csv
    import io
    from datetime import date as _date
    from fastapi.responses import StreamingResponse

    from app.models.meal_log import MealLog

    nutri = _require_nutritionist(user)
    tz = ZoneInfo("America/Sao_Paulo")
    now = datetime.now(tz)

    result = await db.execute(
        select(NutritionistPatient).where(
            NutritionistPatient.nutritionist_id == nutri.id,
            NutritionistPatient.status == "active",
        )
    )
    active_links = result.scalars().all()

    rows = []
    for lk in active_links:
        if not lk.patient_id:
            continue
        pat_result = await db.execute(select(User).where(User.id == lk.patient_id))
        patient = pat_result.scalar_one_or_none()
        if not patient or patient.deleted_at:
            continue

        # Último registro
        last_res = await db.execute(
            select(MealLog).where(MealLog.user_id == lk.patient_id, MealLog.confirmed.is_(True))
            .order_by(MealLog.logged_at.desc()).limit(1)
        )
        last_meal = last_res.scalar_one_or_none()

        # Kcal 7d
        week_start = now - timedelta(days=7)
        w_res = await db.execute(
            select(MealLog).where(
                MealLog.user_id == lk.patient_id, MealLog.confirmed.is_(True),
                MealLog.logged_at >= week_start,
            )
        )
        week_meals = w_res.scalars().all()
        week_dates = {m.logged_at.astimezone(tz).date() for m in week_meals}
        adh_7d = round(len(week_dates) / 7 * 100)
        avg_kcal = round(sum(m.total_calories_kcal for m in week_meals) / 7, 0) if week_meals else 0

        # Aderência 30d + streak
        month_start = now - timedelta(days=29)
        m_res = await db.execute(
            select(MealLog.logged_at).where(
                MealLog.user_id == lk.patient_id, MealLog.confirmed.is_(True),
                MealLog.logged_at >= month_start,
            )
        )
        month_dates = {row[0].astimezone(tz).date() for row in m_res.all()}
        adh_30d = round(len(month_dates) / 30 * 100)
        streak = 0
        _c = now.date()
        while _c in month_dates and streak <= 30:
            streak += 1; _c -= timedelta(days=1)

        _GOAL_MAP = {"perder_peso": "Perder peso", "ganhar_massa": "Ganhar massa muscular", "manter": "Manter o peso"}
        rows.append({
            "nome": patient.first_name or "",
            "telefone": lk.patient_phone or "",
            "objetivo": _GOAL_MAP.get(patient.goal_type or "", ""),
            "data_vinculo": lk.consented_at.strftime("%d/%m/%Y") if lk.consented_at else "",
            "aderencia_7d_pct": adh_7d,
            "aderencia_30d_pct": adh_30d,
            "streak_dias": streak,
            "ultima_refeicao": last_meal.logged_at.astimezone(tz).strftime("%d/%m/%Y %H:%M") if last_meal else "",
            "media_kcal_7d": int(avg_kcal),
        })

    buf = io.StringIO()
    buf.write("﻿")  # UTF-8 BOM para Excel
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else [], extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)

    filename = f"pacientes_{now.strftime('%Y-%m-%d')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── RF-PAINEL-11: PATCH alertas configuráveis por paciente ────────────────────

@router.patch("/api/nutricionista/paciente/{patient_id}/alerta-config")
async def configurar_alerta_paciente(
    patient_id: str,
    inactivity_alert_days: int = Form(default=3, ge=1, le=30),
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Configura o limiar de inatividade (dias) para alerta no dashboard do nutricionista.

    Campo armazenado em NutritionistPatient.inactivity_alert_days (default 3).
    Requer migration Alembic para adicionar a coluna quando ativado.
    """
    import uuid as _uuid
    nutri = _require_nutritionist(user)
    try:
        pid = _uuid.UUID(patient_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="ID inválido")

    result = await db.execute(
        select(NutritionistPatient).where(
            NutritionistPatient.nutritionist_id == nutri.id,
            NutritionistPatient.patient_id == pid,
            NutritionistPatient.status == "active",
        )
    )
    link = result.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=403, detail="Sem vínculo ativo com este paciente")

    link.inactivity_alert_days = inactivity_alert_days
    await db.commit()

    logger.info(
        "[ALERTA-CONFIG] Nutricionista %s configurou limiar de inatividade: %s dias (paciente %s)",
        nutri.id, inactivity_alert_days, patient_id,
    )
    return JSONResponse({"ok": True, "inactivity_alert_days": inactivity_alert_days})
