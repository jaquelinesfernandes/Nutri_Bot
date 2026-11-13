# Nouri — Documento de Arquitetura

**Versão:** 2.1 | **Data:** Outubro 2026

---

## 1. Visão Geral do Sistema

O NutriBot é um **monolito Python** que expõe webhooks HTTP, processa mensagens via Telegram, persiste dados em PostgreSQL e executa jobs agendados. A escolha de monolito é intencional: menor complexidade operacional, deploy único, e extração para microsserviços quando a escala justificar.

Canal implementado: **Telegram** (WhatsApp não implementado).

```
┌─────────────────────────────────────────────────────────┐
│                    USUÁRIO FINAL                         │
└─────────────────────────┬───────────────────────────────┘
                          │ Telegram
                          ▼
               ┌──────────────────────┐
               │    Telegram API      │
               └──────────┬───────────┘
                          │ webhook POST (produção)
                          │ polling (dev local)
                          ▼
               ┌──────────────────────────────────────────┐
               │              Nginx                        │
               │  (reverse proxy + SSL termination)        │
               │  app.seudominio.com → :8000               │
               │  seudominio.com     → /website (static)   │
               └──────────────┬───────────────────────────┘
                              │
               ┌──────────────▼───────────────────────────┐
               │          FastAPI Application              │
               │                                           │
               │  ┌─────────────────────────────────────┐  │
               │  │           Routers                   │  │
               │  │  POST /webhook/telegram             │  │
               │  │  POST /webhook/payment              │  │
               │  │  GET  /health  GET /ping            │  │
               │  │  /api/auth/*  /api/meals/*          │  │
               │  │  /dashboard/* /admin/*              │  │
               │  └────────────────┬────────────────────┘  │
               │                   │                        │
               │  ┌────────────────▼────────────────────┐  │
               │  │       ConversationService            │  │
               │  │  (pacote — 7 módulos / mixins)       │  │
               │  │  _constants · _helpers               │  │
               │  │  _handlers_meal · _handlers_commands │  │
               │  │  _handlers_b2b · service             │  │
               │  └────────────────┬────────────────────┘  │
               │                   │                        │
               │  ┌────────────────▼────────────────────┐  │
               │  │           AIService                  │  │
               │  │  Claude Haiku 4.5 (texto)            │  │
               │  │  Claude Sonnet 4.6 (visão)           │  │
               │  │  OpenAI Whisper (áudio)              │  │
               │  └────────────────┬────────────────────┘  │
               │                   │                        │
               │  ┌────────────────▼────────────────────┐  │
               │  │        NutritionService              │  │
               │  │  5 camadas: cache → TACO → TBCA      │  │
               │  │           → USDA → estimativa IA     │  │
               │  └────────────────────────────────────┘  │
               │                                           │
               │  ┌─────────────────────────────────────┐  │
               │  │         APScheduler (12 jobs)        │  │
               │  │  5 alertas · relatório · re-engage   │  │
               │  │  expiração convites · água           │  │
               │  └─────────────────────────────────────┘  │
               └──────────────────┬───────────────────────┘
                                  │
               ┌──────────────────▼───────────────────────┐
               │          PostgreSQL 16                    │
               │  (Docker — interno, sem porta exposta)    │
               │  Users, MealLogs, FoodItems               │
               │  WeeklyReports, Payments, AuditLogs...   │
               └──────────────────────────────────────────┘

               Serviços externos
               ├─ Anthropic API (Claude — NLP primário)
               ├─ OpenAI API    (Whisper — transcrição)
               ├─ Mercado Pago  (assinaturas)
               ├─ PostHog       (analytics)
               └─ Sentry        (error tracking)
```

---

## 2. Ambiente de desenvolvimento (pré-prod local)

```
docker-compose.yml
  ├── db       — PostgreSQL 16-alpine (porta 5432 exposta ao host)
  ├── pgadmin  — pgAdmin 4 (porta 5050, senha dev)
  └── app      — FastAPI com live reload (porta 8000)
                 Bot roda em polling mode (scripts/run_bot_polling.py)
```

Comandos:
```powershell
# Subir tudo
./scripts/dev-start.ps1

# Aplicar migrations em Docker
./scripts/dev-migrate.ps1

# Rodar testes (fora do Docker, no venv local)
pytest --cov=app
```

Regra: **nunca dois processos de polling simultâneos** — matar o anterior antes de iniciar.

---

## 3. Ambiente de produção (VPS + Docker)

```
docker-compose.prod.yml
  ├── db       — PostgreSQL 16-alpine (sem porta exposta, rede interna)
  ├── app      — FastAPI 2 workers (uvicorn), healthcheck em /ping
  ├── nginx    — Nginx 1.27-alpine (portas 80/443), proxy + static site
  └── certbot  — Let's Encrypt, perfil ssl (cron no host para renovação)
```

Fluxo de deploy:
```
git push origin main
ssh vps "cd /opt/nutribot && ./scripts/deploy.sh --build"
```

Scripts de setup:
- `scripts/init-ssl.sh <domínio> <email>` — emite certificados na 1ª vez
- `scripts/deploy.sh [--build]` — atualiza a stack em produção

### Domínios

| Subdomínio | Serve |
|------------|-------|
| `seudominio.com` | Site de marketing (static `/website`) |
| `app.seudominio.com` | FastAPI (bot + dashboard + API) |

### Telegram Webhook (produção)

```
python scripts/register_telegram_webhook.py https://app.seudominio.com
```

O webhook aponta para `POST /webhook/telegram` e valida o header
`X-Telegram-Bot-Api-Secret-Token` configurado em `TELEGRAM_WEBHOOK_SECRET`.

---

## 4. Diagramas de Sequência

### 4.1 Registro de Refeição por Texto

```
Usuário    Telegram    FastAPI    ConvService    AIService    NutritionSvc    DB
   │           │           │           │              │              │         │
   │─ "arroz" ▶│           │           │              │              │         │
   │           │─ webhook ▶│           │              │              │         │
   │           │           │─ get_user ──────────────────────────────────────▶│
   │           │           │◀─ user (IDLE) ──────────────────────────────────│
   │           │           │─ process_msg ▶│           │              │         │
   │           │           │               │─ parse ──▶│              │         │
   │           │           │               │           │─ Claude ────▶│         │
   │           │           │               │           │◀─ foods[] ──│         │
   │           │           │               │◀─ foods[] │              │         │
   │           │           │               │─ lookup ─────────────────▶│        │
   │           │           │               │           │              │─ TACO ─▶│
   │           │           │               │           │              │◀─ macros│
   │           │           │               │◀─ enriched ──────────────│         │
   │           │           │               │─ state→CONFIRMING        │         │
   │           │           │◀─ reply ──────│           │              │         │
   │           │◀─ sendMsg │               │           │              │         │
   │◀─ "463kcal"│           │               │           │              │         │
   │─ "Sim" ───▶│           │               │           │              │         │
   │           │─ webhook ─▶│               │           │              │         │
   │           │           │─ confirm() ────────────────────────────────────── ▶│
   │           │           │               │─ state→IDLE               │         │
   │           │◀─ "Salvo!" │               │           │              │         │
```

### 4.2 Fluxo de Alerta (APScheduler)

```
APScheduler    DB                  NotificationSvc    Telegram
     │            │                      │                │
     │─ horário BRT (12 jobs)            │                │
     │─ busca users com alertas ativos ─▶│                │
     │◀─ users[] ─────────────────────── │                │
     │                                   │                │
     │  para cada user:                  │                │
     │─ verificou hoje? ─────────────────▶│                │
     │◀─ não_registrou ──────────────────│                │
     │─ send_alert(user) ────────────────▶│                │
     │                                   │─ send_msg() ──▶│
```

### 4.3 Geração do Relatório Semanal

```
APScheduler    DB      ReportService    WeasyPrint    Notif.Svc    Telegram
     │           │           │               │              │           │
     │─ dom 20h  │           │               │              │           │
     │─ get_eligible_users() ▶│              │              │           │
     │◀─ users[] ─────────── │               │              │           │
     │                        │               │              │           │
     │  lotes de 25:          │               │              │           │
     │─ get_week_data() ─────▶│               │              │           │
     │─ generate_suggestions()│ (Claude)      │              │           │
     │─ render_pdf() ─────────────────────── ▶│              │           │
     │◀─ pdf_bytes ───────────────────────── │              │           │
     │─ save_report() ───────▶│               │              │           │
     │─ send_report() ─────────────────────── ────────────── ▶│           │
     │                        │               │              │─ sendDoc()▶│
     │─ sleep(40ms) (rate limit)              │              │           │
```

### 4.4 Webhook de Pagamento

```
MercadoPago    FastAPI         DB              NotificationSvc
     │              │             │                   │
     │─ POST /webhook/payment ──▶│                   │
     │              │─ validate_hmac()                │
     │              │─ 200 OK (imediato)              │
     │              │                                  │
     │              │  (async):                        │
     │              │─ get_subscription_status()──────▶│
     │              │─ update_user_plan() ─────────────▶│
     │              │─ notify_user() ───────────────────▶│
```

---

## 5. Architecture Decision Records (ADRs)

### ADR-001: Monolito para o MVP
**Decisão:** Monolito Python único em vez de microsserviços.  
**Motivo:** Complexidade desnecessária com equipe pequena e < 1.000 usuários.  
**Path:** Extração para microsserviços na Fase 3 (> 50k usuários).

### ADR-002: PostgreSQL (Docker) em vez de Neon/Supabase
**Decisão:** PostgreSQL 16 em container Docker (pré-prod local e produção VPS).  
**Motivo:** Custo zero, sem limites de conexões, dados sob controle. Neon foi descartado após usar em produção — free tier limitado.  
**Consequência:** Migrations obrigatórias via Alembic; `_apply_pending_ddl()` foi removido.

### ADR-003: VPS + Docker + Nginx em vez de Render/Railway
**Decisão:** VPS própria com docker-compose.prod.yml e Nginx.  
**Motivo:** Custo operacional; Render adormecia o free tier; Railway descontinuado.  
**Consequência:** Ops manual de deploy via `scripts/deploy.sh`; SSL via Let's Encrypt/Certbot.

### ADR-004: Anthropic Claude como IA primária (não OpenAI)
**Decisão:** `claude-haiku-4-5` para NLP, `claude-sonnet-4-6` para Vision.  
**Motivo:** Melhor performance em português, custo competitivo, output estruturado confiável.  
**OpenAI:** Mantido apenas para Whisper (transcrição de áudio).

### ADR-005: Telegram apenas (WhatsApp removido)
**Decisão:** Somente Telegram implementado. WhatsApp via Evolution API foi planejado mas removido.  
**Motivo:** Complexidade de setup da Evolution API vs. benefício no MVP.  
**Consequência:** `webhook_whatsapp.py`, `schemas/whatsapp.py` e toda config Evolution foram deletados.

### ADR-006: APScheduler in-process
**Decisão:** APScheduler (AsyncIOScheduler) embutido no FastAPI.  
**Motivo:** Celery exige Redis como broker. Para MVP com 12 jobs simples, in-process é suficiente.  
**Mitigação:** Jobs são idempotentes; `misfire_grace_time=3600` + `coalesce=True`.

### ADR-007: conversation.py → pacote de 7 módulos
**Decisão:** Refatorado de monolito (2.631 linhas) para `app/services/conversation/` com mixins.  
**Motivo:** Arquivo monolítico com 2.631 linhas — difícil de manter e testar.  
**Estrutura:** `_constants`, `_helpers`, `_handlers_meal`, `_handlers_commands`, `_handlers_b2b`, `service`.

### ADR-008: Base nutricional local (TACO + TBCA + USDA)
**Decisão:** Bases carregadas em memória na startup, sem chamada externa em tempo real.  
**Pipeline:** cache → TACO (306) → TBCA (1.994) → USDA (25) → estimativa Claude.  
**Motivo:** Latência zero no lookup; dados nacionais (TACO/TBCA) têm prioridade sobre USDA.

### ADR-009: WeasyPrint para PDF
**Decisão:** WeasyPrint (Python puro) em vez de Puppeteer/Chrome headless.  
**Motivo:** Sem dependência Node.js; stack Python uniforme.  
**Limitação:** Template HTML deve usar CSS simples (sem JS, grid/flex básico).

### ADR-010: Autenticação por channel_id (bot) + JWT httpOnly (dashboard)
**Decisão:** Bot identifica usuário pelo `chat_id` do Telegram. Dashboard usa JWT em cookie httpOnly.  
**Motivo:** Menor fricção no onboarding; `chat_id` é autenticado pelo Telegram.  
**Segurança:** JWT nunca retorna no body (apenas cookie); sessão 365 dias com sliding renewal.

---

## 6. Estrutura de Diretórios Atual

```
app/
  main.py                    # FastAPI factory, SecurityHeadersMiddleware (incl. CSP)
  config.py                  # Pydantic-settings — valida segredos na startup
  routers/
    health.py                # /health, /ping, /scheduler/status*, /scheduler/trigger*
    webhook_telegram.py      # POST /webhook/telegram (valida X-Telegram-Bot-Api-Secret-Token)
    webhook_payment.py       # POST /webhook/payment (HMAC HMAC em produção)
    auth.py                  # POST /api/auth/register|login|logout
    dashboard.py             # Jinja2 server-rendered /login, /esqueci-senha, /auth/magic
    meals.py  reports.py  users.py  admin.py
  services/
    conversation/            # Pacote — 7 módulos (refatorado de conversation.py)
      __init__.py            # Re-exporta ConversationService
      _constants.py          # Estados, timeouts, emojis
      _helpers.py            # HelpersMixin — DB helpers, formatters
      _handlers_meal.py      # MealMixin — confirmar, corrigir, foto, áudio
      _handlers_commands.py  # CommandsMixin — /hoje, /relatorio, alertas...
      _handlers_b2b.py       # B2BMixin — convites nutricionista, LGPD revogação
      service.py             # ConversationService (herda todos os mixins)
    ai_service.py  nutrition.py  scheduler.py  report.py
    analytics.py  notification.py  payment.py
  models/                    # SQLAlchemy ORM (9 tabelas)
  schemas/
  db/
    session.py               # AsyncSession factory (pool_size=3)
  utils/
    crypto.py                # Fernet AES-256 (LGPD)
    jwt.py                   # JWT create/decode + deps
    rate_limiter.py
    timezone.py
data/
  taco.json    tbca.json    tbca_raw.json    usda.json
  report_template.html
migrations/versions/
docker-compose.yml           # Pré-prod local: db + pgadmin + app
docker-compose.prod.yml      # Produção VPS: db + app + nginx + certbot
nginx/
  nginx.conf                 # Config global
  conf.d/
    app.conf                 # app.seudominio.com → FastAPI
    website.conf             # seudominio.com → static site
website/
  index.html                 # Landing page de marketing
scripts/
  dev-start.ps1  dev-migrate.ps1
  init-ssl.sh  deploy.sh
  register_telegram_webhook.py  run_bot_polling.py
tests/                       # 447 testes · 60% cobertura
docs/
  NutriBot_PRD_v2.1.md  architecture.md  api-spec.md
  prompts.md  fuzzy-match.md  admin-panel.md
  prd-historico-peso.md
```

---

## 7. Decisões de Performance

| Área | Estratégia |
|------|-----------|
| Lookup TACO/TBCA/USDA | Bases carregadas em memória na startup (~8MB total) |
| Cache de alimentos | Top 500 alimentos pré-calculados em dict Python |
| Conexões ao banco | Pool asyncpg: pool_size=3 (Docker dev) |
| Claude retries | Exponential backoff automático via SDK Anthropic |
| Relatórios | Lotes de 25 usuários, 40ms entre mensagens (rate limit Telegram) |
| Webhook response | Responde 200 imediatamente, processa em `BackgroundTask` |

---

## 8. Segurança (auditoria 2026-08-25)

| Controle | Implementação |
|----------|--------------|
| Segredos em produção | `_check_production_secrets()` bloqueia startup com defaults inseguros |
| JWT | Cookie httpOnly; nunca no body; 365 dias com sliding renewal |
| Rate limiting | Auth: 5 tentativas/5min por IP; Register: 5/hora por IP |
| Timing attack | `dummy_verify()` quando usuário não encontrado |
| Dados sensíveis LGPD | Fernet AES-256 (`RAW_INPUT_ENCRYPTION_KEY`) para raw meal input |
| Webhook Telegram | `X-Telegram-Bot-Api-Secret-Token` validado em todas as requisições |
| Webhook Pagamento | HMAC obrigatório em produção |
| Headers HTTP | CSP, HSTS, X-Frame-Options, X-Content-Type-Options via middleware |
| SQL injection | SQLAlchemy ORM com parâmetros ligados — sem SQL raw |
