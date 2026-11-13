# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NutriBot is a Telegram nutritional tracking chatbot that lets users log meals via text, audio, or photo in natural language. It identifies foods, calculates calories and macronutrients using three local databases — TACO/UNICAMP (306 items), TBCA/USP-FoRC (1,994 items), and USDA (25 items) — tracks meal schedules, sends proactive alerts, and delivers weekly PDF reports with AI-generated personalized suggestions.

The PRD (`docs/NutriBot_PRD_v2.1.md`) is the authoritative source for scope, priorities, and acceptance criteria.

## Current State (October 2026)

**All 6 sprints + Post-6 UX + B2B-1/2 + Admin-1 complete — pre-prod local Docker, production on VPS.**

- 447 tests passing · coverage 60% (threshold ≥ 55%)
- Channel: **Telegram only** (WhatsApp removed — not implemented)
- Beta open: reports unlocked for all users via `REPORTS_OPEN_BETA=true`
- Sessions persist for 365 days with sliding-expiration renewal (no re-login needed)
- Production: **VPS + Docker + Nginx** (Render/Railway removed)

## Real Architecture

**Backend:** Python 3.13 · FastAPI (monolith)  
**AI primary:** Anthropic Claude — `claude-haiku-4-5` for NLP, `claude-sonnet-4-6` for Vision  
**AI secondary:** OpenAI Whisper — audio transcription only  
**Database:** PostgreSQL 16 · SQLAlchemy asyncio · asyncpg · Alembic — **Docker container**  
**Alerts:** APScheduler AsyncIOScheduler (12 jobs)  
**PDF reports:** WeasyPrint + Jinja2 (not Puppeteer)  
**Auth:** JWT (python-jose) + bcrypt (passlib) · httpOnly cookie  
**Channels:** Telegram Bot API only (WhatsApp removed)  
**Nutrition data:** TACO/UNICAMP + TBCA/USP-FoRC + USDA as local JSON — no external call at runtime (5-layer fuzzy pipeline: cache → TACO → TBCA → USDA → Claude estimated)  
**Payments:** MercadoPago SDK  
**Analytics:** PostHog  
**Monitoring:** Sentry SDK  
**Hosting (prod):** VPS + Docker Compose + Nginx reverse proxy + Let's Encrypt SSL  
**Hosting (dev):** Local Docker Compose (db + pgadmin + app with live reload)  
**Website:** Static marketing site served by Nginx (`website/index.html`)

## Development Commands

```powershell
# ── Pré-prod local (Docker) ───────────────────────────────────────────
# Subir db + pgadmin + app (live reload)
./scripts/dev-start.ps1

# Aplicar migrations no container
./scripts/dev-migrate.ps1

# Polling Telegram local (em outro terminal)
docker exec nutribot_app python scripts/run_bot_polling.py

# ── Testes (no venv local, não no Docker) ────────────────────────────
.venv\Scripts\Activate.ps1
pytest
pytest --cov=app --cov-report=term-missing
pytest tests/test_nutrition.py -v

# ── Produção VPS ─────────────────────────────────────────────────────
# 1ª vez — emitir SSL
./scripts/init-ssl.sh seudominio.com admin@seudominio.com

# Deploy / atualização
./scripts/deploy.sh --build

# Registrar webhook Telegram
python scripts/register_telegram_webhook.py https://app.seudominio.com
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
OPENAI_API_KEY            # Whisper audio transcription only
MERCADOPAGO_ACCESS_TOKEN  # Payments
MERCADOPAGO_WEBHOOK_SECRET
MERCADOPAGO_MONTHLY_PLAN_ID
MERCADOPAGO_ANNUAL_PLAN_ID
ADMIN_API_KEY             # Protects /scheduler/trigger and /scheduler/status
ADMIN_PASSWORD            # Acesso ao painel admin /admin (obrigatório em produção)
POSTHOG_API_KEY           # Analytics
SENTRY_DSN                # Error monitoring
APP_URL                   # Public URL (used in bot links)
REPORTS_OPEN_BETA         # true (default) = all users access reports; false = premium only
```

## Key Domain Constraints

- **Nutrition database priority:** TACO (UNICAMP) > TBCA (USP/FoRC) > USDA. Always prefer TACO entries; TBCA is the second Brazilian source with 1,994 items collected via web scraping (`scripts/scrape_tbca.py`).
- **Language:** Portuguese (Brazilian), including gírias and regionalismos alimentares.
- **LGPD compliance:** Health data is classified as *dados sensíveis* (Art. 11). Explicit consent required on onboarding; support right-to-deletion within 72h. Raw meal input is encrypted at rest via `app/utils/crypto.py` (Fernet/AES-256).
- **MVP acceptance thresholds:** >80% text recognition accuracy on top-500 TACO foods; >75% photo identification; alerts delivered within 2 min in 99% of cases.
- **Scheduler reliability:** APScheduler uses `misfire_grace_time=3600` and `coalesce=True` so jobs fire up to 1h late. 12 jobs total.

## Project Structure

```
app/
  main.py                  # FastAPI app factory + SecurityHeadersMiddleware
  config.py                # Pydantic-settings — validates secrets at startup
  routers/
    health.py              # /health, /ping, /scheduler/status*, /scheduler/trigger*
    webhook_telegram.py    # POST /webhook/telegram (validates X-Telegram-Bot-Api-Secret-Token)
    webhook_payment.py     # POST /webhook/payment (HMAC validation, required in prod)
    auth.py                # POST /api/auth/register|login|logout
    dashboard.py           # Jinja2 server-rendered web dashboard · GET /login · GET /esqueci-senha · POST /auth/esqueci-senha · GET /auth/magic
    meals.py               # REST API meals
    reports.py             # REST API reports
    users.py               # REST API user profile
    admin.py               # Painel admin /admin — auth JWT própria (type=admin), gestão de usuários, LGPD, scheduler
  services/
    conversation/          # Pacote — refatorado de conversation.py (2.631 linhas)
      __init__.py          # Re-exporta ConversationService (backward-compatible)
      _constants.py        # ConversationState, timeouts, emojis
      _helpers.py          # HelpersMixin — DB helpers, URLs, formatters
      _handlers_meal.py    # MealMixin — confirmar, corrigir, texto/foto/áudio
      _handlers_commands.py# CommandsMixin — todos os /cmd_* handlers + água
      _handlers_b2b.py     # B2BMixin — convite nutricionista, revogação LGPD
      service.py           # ConversationService(HelpersMixin, MealMixin, ...) + dispatch
    ai_service.py          # Anthropic Claude integration (text, vision); Whisper (audio)
    nutrition.py           # TACO + TBCA + USDA lookup + RapidFuzz (5-layer pipeline)
    scheduler.py           # APScheduler jobs: 12 jobs (alertas + relatório + água + re-engage)
    report.py              # PDF generation (WeasyPrint)
    analytics.py           # PostHog event tracking
    notification.py        # Send messages via Telegram only
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
    meal.py
    ai_response.py
  db/
    session.py             # AsyncSession factory (pool_size=3)
    base.py
  utils/
    crypto.py              # Fernet AES-256 encrypt/decrypt for health data
    jwt.py                 # JWT create/decode + FastAPI cookie deps
    rate_limiter.py        # In-memory rate limiter (per IP, per user)
    timezone.py            # BRT utilities
data/
  taco.json                # TACO/UNICAMP nutritional table (306 Brazilian foods — includes 10 fast-food items)
  tbca.json                # TBCA/USP-FoRC nutritional table (1,994 Brazilian foods — scraped)
  tbca_raw.json            # Raw scraping links (2,000 items — input for scrape_tbca.py)
  usda.json                # USDA FoodData Central subset (25 items — imported/international products)
  report_template.html     # Jinja2 template for PDF reports
migrations/versions/
  aa27ebf221d2_initial_schema.py
  b3c91f4e7d02_add_report_period_fields.py
docker-compose.yml             # Pré-prod local: db + pgadmin + app (live reload)
docker-compose.prod.yml        # Produção VPS: db + app + nginx + certbot
nginx/
  nginx.conf                   # Config global Nginx
  conf.d/
    app.conf                   # app.seudominio.com → FastAPI + SSL
    website.conf               # seudominio.com → site estático + SSL
website/
  index.html                   # Landing page de marketing (PT-BR)
scripts/
  dev-start.ps1                # Sobe docker-compose.yml (dev local)
  dev-migrate.ps1              # Aplica migrations no container dev
  init-ssl.sh                  # Emite certificados SSL Let's Encrypt (1ª vez no VPS)
  deploy.sh                    # Deploy / atualização na VPS
  register_telegram_webhook.py # setWebhook com secret_token
  run_bot_polling.py           # Polling mode (dev local)
  check_db.py
  testar_relatorio.py
  testar_alerta.py
  expand_taco.py
  scrape_tbca.py               # Web scraping TBCA (20 páginas → tbca.json); --retomar para retomar
  fix_tbca_categories.py       # Pós-processamento: recategoriza tbca.json
tests/
  conftest.py
  test_nutrition.py
  test_conversation.py
  test_services.py
  test_sprint4.py
  test_sprint5.py
  test_webhooks.py
docs/
  NutriBot_PRD_v2.1.md         # PRD autoritativo
  architecture.md              # Arquitetura real (atualizado outubro 2026)
  api-spec.md
  prompts.md
  fuzzy-match.md
  admin-panel.md               # Painel admin: autenticação, rotas, auditoria, roadmap
  prd-historico-peso.md        # PRD para implementação futura do histórico de peso
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
| 6 | Deploy (orig. Render + Neon, migrado para VPS + Docker) · auditoria segurança · beta aberto | ✅ |
| Post-6 | Registro retroativo sem limite · entrada manual no painel · relatórios pelo painel (gerar/limpar/baixar) · acesso automático após 7 dias | ✅ |
| Post-6 UX | Login redesenhado (Telegram como primário) · recuperação de senha via magic link · sessão 365 dias sem re-login · calculadora TDEE no cadastro · banner CTA Telegram · countdown preciso no rate-limit · datepicker bloqueia datas futuras | ✅ |
| B2B-1 | Infra · cadastro nutricionista · convites · deep link Telegram · scheduler expiração · LGPD consentimento | ✅ |
| B2B-2 | Perfil do paciente · gráfico kcal 30d · notas clínicas · PDF on-demand · revogação pelo bot (estado REVOKING) | ✅ |
| Admin-1 | Painel admin /admin · auth JWT própria · gestão usuários · LGPD anonimização · scheduler trigger · auditoria admin_logs | ✅ |
| Infra VPS | WhatsApp removido · Render removido · conversation.py → pacote · VPS Docker + Nginx · site marketing · segurança (CSP, _apply_pending_ddl removido) | ✅ |
| Fase 3 | App nativo / Web | 🗓️ Planejado |
