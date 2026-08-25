# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NutriBot is a multicanal nutritional tracking chatbot (WhatsApp, Telegram) that lets users log meals via text, audio, or photo in natural language. It identifies foods, calculates calories and macronutrients using the TACO (Brazilian) and USDA databases, tracks meal schedules, sends proactive alerts, and delivers weekly PDF reports with AI-generated personalized suggestions.

The PRD (`docs/NutriBot_PRD_v2.1.md`) is the authoritative source for scope, priorities, and acceptance criteria.

## Current State (August 2026)

**All 6 sprints + Post-6 UX polish complete — in production on Render + Neon.**

- 290 tests passing · coverage 70% (threshold ≥ 55%)
- Deployed at: `https://nutri-bot-ot0p.onrender.com`
- Beta open: reports unlocked for all users via `REPORTS_OPEN_BETA=true`
- Sessions persist for 365 days with sliding-expiration renewal (no re-login needed)

## Real Architecture (differs from original PRD)

**Backend:** Python 3.13 · FastAPI (monolith)  
**AI primary:** Anthropic Claude — `claude-haiku-4-5-20251001` for NLP, `claude-sonnet-4-6` for Vision  
**AI secondary:** OpenAI Whisper — audio transcription only  
**Database:** PostgreSQL 16 · SQLAlchemy asyncio · asyncpg · Alembic — hosted on **Neon**  
**Alerts:** APScheduler AsyncIOScheduler · UptimeRobot keep-alive (Render free tier sleeps)  
**PDF reports:** WeasyPrint + Jinja2 (not Puppeteer)  
**Auth:** JWT (python-jose) + bcrypt (passlib) · httpOnly cookie  
**Channels:** Telegram Bot API · WhatsApp via **Evolution API** (not Z-API or Twilio)  
**Nutrition data:** TACO + USDA as local JSON — no external call at runtime  
**Payments:** MercadoPago SDK  
**Analytics:** PostHog  
**Monitoring:** Sentry SDK  
**Hosting:** Render (app) + Neon (PostgreSQL)  
**Scale path:** GCP Cloud Run + Cloud SQL São Paulo (documented in `docs/infra-arch-render-neon.md`)

## Development Commands

```powershell
# Activate venv
.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt -r requirements-dev.txt

# Run FastAPI dev server
uvicorn app.main:app --reload

# Run tests
pytest

# Run with coverage
pytest --cov=app --cov-report=term-missing

# Single test file
pytest tests/test_nutrition.py -v

# Apply DB migrations
alembic upgrade head

# Register Telegram webhook (after deploy)
python scripts/register_telegram_webhook.py https://nutri-bot-ot0p.onrender.com
```

## Environment Variables

### Required in all environments

```env
DATABASE_URL          # PostgreSQL — config.py auto-converts to asyncpg format
ANTHROPIC_API_KEY     # Claude — NLP + Vision (primary AI)
TELEGRAM_BOT_TOKEN    # Telegram bot token
JWT_SECRET            # 32+ chars: python -c "import secrets; print(secrets.token_hex(32))"
RAW_INPUT_ENCRYPTION_KEY  # 64 hex chars: same command above
APP_ENV               # development | production
```

### Required in production (app fails to start without these)

```env
JWT_SECRET                # Must differ from default "change-me-in-production-use-32-chars-min"
RAW_INPUT_ENCRYPTION_KEY  # Must differ from "0"*64 (LGPD — health data encryption)
TELEGRAM_WEBHOOK_SECRET   # Prevents fake webhook injection
```

### Optional / feature-specific

```env
OPENAI_API_KEY            # Whisper audio transcription (Sprint 2)
EVOLUTION_API_URL         # WhatsApp via Evolution API
EVOLUTION_API_KEY
EVOLUTION_WEBHOOK_SECRET
MERCADOPAGO_ACCESS_TOKEN  # Payments
MERCADOPAGO_WEBHOOK_SECRET
MERCADOPAGO_MONTHLY_PLAN_ID
MERCADOPAGO_ANNUAL_PLAN_ID
ADMIN_API_KEY             # Protects /scheduler/trigger and /scheduler/status
POSTHOG_API_KEY           # Analytics
SENTRY_DSN                # Error monitoring
APP_URL                   # Public URL (used in bot links)
REPORTS_OPEN_BETA         # true (default) = all users access reports; false = premium only
```

## Key Domain Constraints

- **Nutrition database priority:** TACO (Brazilian) > USDA. Always prefer TACO entries for Brazilian foods.
- **Language:** Portuguese (Brazilian), including gírias and regionalismos alimentares.
- **LGPD compliance:** Health data is classified as *dados sensíveis* (Art. 11). Explicit consent required on onboarding; support right-to-deletion within 72h. Raw meal input is encrypted at rest via `app/utils/crypto.py` (Fernet/AES-256).
- **MVP acceptance thresholds:** >80% text recognition accuracy on top-500 TACO foods; >75% photo identification; alerts delivered within 2 min in 99% of cases.
- **Scheduler reliability:** APScheduler uses `misfire_grace_time=3600` and `coalesce=True` so jobs fire up to 1h late after Render wakes from sleep.

## Project Structure

```
app/
  main.py                  # FastAPI app factory + SecurityHeadersMiddleware
  config.py                # Pydantic-settings — validates secrets at startup
  routers/
    health.py              # /health, /ping, /scheduler/status*, /scheduler/trigger*
    webhook_telegram.py    # POST /webhook/telegram (validates X-Telegram-Bot-Api-Secret-Token)
    webhook_whatsapp.py    # POST /webhook/whatsapp
    webhook_payment.py     # POST /webhook/payment (HMAC validation, required in prod)
    auth.py                # POST /api/auth/register|login|logout
    dashboard.py           # Jinja2 server-rendered web dashboard · GET /login · GET /esqueci-senha · POST /auth/esqueci-senha · GET /auth/magic
    meals.py               # REST API meals
    reports.py             # REST API reports
    users.py               # REST API user profile
  services/
    conversation.py        # Conversational state machine (~61 KB) — main bot logic
    ai_service.py          # Anthropic Claude integration (text, vision, audio)
    nutrition.py           # TACO + USDA lookup + RapidFuzz matching
    scheduler.py           # APScheduler jobs: meal alerts (5/day) + reports + reengagement
    report.py              # PDF generation (WeasyPrint)
    analytics.py           # PostHog event tracking
    notification.py        # Send messages via Telegram/WhatsApp
    payment.py             # MercadoPago webhook handler
  models/                  # SQLAlchemy ORM (9 tables)
    user.py                # plan: free|premium|nutritionist; is_premium property
    meal_log.py            # raw_input_encrypted (AES-256)
    food_item.py
    meal_window.py
    water_log.py
    weekly_report.py
    payment_subscription.py
    audit_log.py
  schemas/
    auth.py                # AuthResponse — token NOT in body (httpOnly cookie only)
    telegram.py
    whatsapp.py
    meal.py
    ai_response.py
  db/
    session.py             # AsyncSession factory (pool_size=3 for Neon free tier)
    base.py
  utils/
    crypto.py              # Fernet AES-256 encrypt/decrypt for health data
    jwt.py                 # JWT create/decode + FastAPI cookie deps
    rate_limiter.py        # In-memory rate limiter (per IP, per user)
    timezone.py            # BRT utilities
data/
  taco.json                # TACO nutritional table (Brazilian foods)
  usda.json                # USDA FoodData Central subset
  report_template.html     # Jinja2 template for PDF reports
migrations/versions/
  aa27ebf221d2_initial_schema.py
  b3c91f4e7d02_add_report_period_fields.py
scripts/
  register_telegram_webhook.py   # setWebhook with secret_token
  run_bot_polling.py             # Local dev polling mode
  check_db.py
  testar_relatorio.py
  testar_alerta.py
  expand_taco.py
tests/
  conftest.py
  test_nutrition.py
  test_conversation.py
  test_services.py
  test_sprint4.py
  test_sprint5.py
  test_webhooks.py
docs/
  NutriBot_PRD_v2.1.md          # Authoritative PRD
  architecture.md
  api-spec.md
  prompts.md
  fuzzy-match.md
  infra-arch-render-neon.md     # GCP migration plan (9 phases)
  infra-setup-render-neon.md    # Step-by-step Render + Neon setup
```

*Endpoints marked `*` require `X-Admin-Key: <ADMIN_API_KEY>` header when `ADMIN_API_KEY` is set.*

## Security Notes (post-audit 2026-08-20, updated 2026-08-25)

- **Startup validation:** `config.py` `_check_production_secrets()` blocks startup if insecure defaults are used in production.
- **JWT:** Stored in httpOnly cookie only — never returned in response body. Expires in 365 days; `SlidingSessionMiddleware` renews automatically when ≤ 30 days remain so the user never re-logs while actively using the dashboard.
- **Rate limiting:** `/api/auth/login` and `/dashboard/login` — 5 attempts/5min per IP (precise countdown in error message via `get_wait_seconds()`). `/api/auth/register` — 5/hour per IP.
- **Timing-attack protection:** `dummy_verify()` called even when user not found (prevents user enumeration via response time).
- **Password recovery:** `POST /auth/esqueci-senha` — anti-enumeration (always returns success), sends 30-min magic link via Telegram Bot API. No e-mail required.
- **Magic link auth:** `GET /auth/magic?t={token}` — 10-min JWT with `type='magic'`; once validated, sets a full 365-day session cookie and the token is invalidated by expiry.
- **Webhooks:** Telegram requires `TELEGRAM_WEBHOOK_SECRET`; MercadoPago requires HMAC signature in production.
- **Sensitive endpoints:** `/scheduler/trigger` and `/scheduler/status` require `X-Admin-Key` header.
- **Encryption:** Meal raw text encrypted with Fernet (AES-256) using `RAW_INPUT_ENCRYPTION_KEY`.
- **Link token:** Generated with `secrets.choice()` (cryptographically secure).
- **Date validation:** `POST /api/meals` rejects future dates (422); the dashboard datepicker also blocks them client-side (disabled button, greyed-out cells, modal guard).

## Sprint History

| Sprint | Focus | Status |
|--------|-------|--------|
| 1 | Infra · bots · registro de refeições por texto · TACO lookup | ✅ |
| 2 | Claude Vision (foto) · Whisper (áudio) · fluxo de confirmação | ✅ |
| 3 | Alertas por janela de refeição · meta de calorias | ✅ |
| 4 | Relatório PDF semanal · sugestões IA · histórico | ✅ |
| 5 | Onboarding · UX polish · dashboard web · beta fechado | ✅ |
| 6 | Deploy Render + Neon · UptimeRobot · auditoria segurança · beta aberto | ✅ |
| Post-6 | Registro retroativo sem limite · entrada manual no painel · relatórios pelo painel (gerar/limpar/baixar) · acesso automático após 7 dias | ✅ |
| Post-6 UX | Login redesenhado (Telegram como primário) · recuperação de senha via magic link · sessão 365 dias sem re-login · calculadora TDEE no cadastro · banner CTA Telegram · countdown preciso no rate-limit · datepicker bloqueia datas futuras | ✅ |
| Fase 2 | Painel B2B para nutricionistas (R$ 79,90/mês) | 🗓️ Próxima |
| Fase 3 | App nativo / Web | 🗓️ Planejado |
