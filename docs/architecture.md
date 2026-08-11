# NutriBot — Architecture Document

**Versão:** 1.0 | **Data:** Junho 2026

---

## 1. Visão Geral do Sistema

O NutriBot MVP é um **monolito Python** que expõe webhooks HTTP, processa mensagens de chatbot, persiste dados em PostgreSQL e executa jobs agendados. A escolha de monolito é intencional para o MVP: menor complexidade operacional, deploy único, e refatoração para microsserviços quando a escala justificar.

```
┌─────────────────────────────────────────────────────────┐
│                    USUÁRIO FINAL                         │
└────────────────┬──────────────────────────┬─────────────┘
                 │ Telegram                  │ WhatsApp
                 ▼                           ▼
        ┌────────────────┐         ┌─────────────────┐
        │  Telegram API  │         │   Z-API (WA)    │
        └───────┬────────┘         └────────┬────────┘
                │ webhook POST               │ webhook POST
                └────────────┬──────────────┘
                             ▼
              ┌──────────────────────────────┐
              │     FastAPI Application      │
              │   (Railway — sempre ligado)  │
              │                              │
              │  ┌────────────────────────┐  │
              │  │    WebhookRouter       │  │
              │  │  /webhook/telegram     │  │
              │  │  /webhook/whatsapp     │  │
              │  │  /webhook/payment      │  │
              │  │  /health               │  │
              │  └──────────┬─────────────┘  │
              │             │                │
              │  ┌──────────▼─────────────┐  │
              │  │   ConversationService  │  │
              │  │  (state machine core)  │  │
              │  └──────────┬─────────────┘  │
              │             │                │
              │  ┌──────────▼─────────────┐  │
              │  │     AIService          │  │
              │  │  GPT-4o / Vision /     │  │
              │  │  Whisper               │  │
              │  └──────────┬─────────────┘  │
              │             │                │
              │  ┌──────────▼─────────────┐  │
              │  │   NutritionService     │  │
              │  │  TACO + USDA lookup    │  │
              │  │  + FoodCache           │  │
              │  └──────────┬─────────────┘  │
              │             │                │
              │  ┌──────────▼─────────────┐  │
              │  │   NotificationService  │  │
              │  │  Telegram + WhatsApp   │  │
              │  └────────────────────────┘  │
              │                              │
              │  ┌────────────────────────┐  │
              │  │   APScheduler Jobs     │  │
              │  │  - Alert checker       │  │
              │  │  - Report generator    │  │
              │  │  - Re-engagement       │  │
              │  └──────────┬─────────────┘  │
              └─────────────┼────────────────┘
                            │
              ┌─────────────▼────────────────┐
              │      PostgreSQL (Supabase)   │
              │  Users, MealLogs, FoodItems  │
              │  WeeklyReports, Payments...  │
              └──────────────────────────────┘

              ┌──────────────────────────────┐
              │   APIs Externas              │
              │  - OpenAI (GPT-4o, Whisper)  │
              │  - Mercado Pago Subscriptions│
              │  - Sentry (error tracking)   │
              │  - PostHog (analytics)       │
              └──────────────────────────────┘
```

---

## 2. Diagramas de Sequência

### 2.1 Registro de Refeição por Texto

```
Usuário       Telegram      FastAPI       ConvService    AIService     NutritionSvc    DB
   │              │             │               │              │              │          │
   │─ "almocei ──▶│             │               │              │              │          │
   │   arroz..."  │─ webhook ──▶│               │              │              │          │
   │              │             │─ get_user ───────────────────────────────────────────▶│
   │              │             │◀─ user (IDLE)────────────────────────────────────────│
   │              │             │─ process_msg ▶│               │              │          │
   │              │             │               │─ parse_text ─▶│              │          │
   │              │             │               │               │─ GPT-4o ────▶│          │
   │              │             │               │               │◀─ foods[] ───│          │
   │              │             │               │◀─ foods[]    ─│              │          │
   │              │             │               │─ lookup ──────────────────────▶│         │
   │              │             │               │               │              │─ TACO ──▶│
   │              │             │               │               │              │◀─ macros─│
   │              │             │               │◀─ enriched_foods──────────────│          │
   │              │             │               │─ set_state(CONFIRMING)        │          │
   │              │             │               │─ save_pending ──────────────────────────▶│
   │              │             │◀─ reply_text ─│               │              │          │
   │              │◀─ sendMsg ──│               │               │              │          │
   │◀─ "Anotei! ──│             │               │               │              │          │
   │   Total:463" │             │               │               │              │          │
   │              │             │               │               │              │          │
   │─ "Sim ✅" ──▶│             │               │               │              │          │
   │              │─ webhook ──▶│               │               │              │          │
   │              │             │─ process_msg ▶│               │              │          │
   │              │             │               │─ confirm() ───────────────────────────▶│
   │              │             │               │─ set_state(IDLE)              │          │
   │              │             │◀─ "Salvo ✅" ─│               │              │          │
   │              │◀─ sendMsg ──│               │               │              │          │
   │◀─ "Salvo ✅"─│             │               │               │              │          │
```

### 2.2 Registro de Refeição por Foto

```
Usuário       Telegram      FastAPI       ConvService    AIService        DB
   │              │             │               │              │            │
   │─ [foto] ────▶│             │               │              │            │
   │              │─ webhook ──▶│               │              │            │
   │              │             │─ download_file─────────────────────────────
   │              │             │               │─ process_photo▶│            │
   │              │             │               │               │─ GPT-4 ───▶
   │              │             │               │               │  Vision    │
   │              │             │               │               │◀─ foods[]──│
   │              │             │               │◀─ foods[]    ─│            │
   │              │             │               │ [mesmo fluxo do texto acima]
```

### 2.3 Fluxo de Alerta (APScheduler)

```
APScheduler     DB              NotificationSvc    Telegram/WA
     │            │                    │                │
     │─ (a cada hora)                  │                │
     │─ get_pending_alerts() ─────────▶│                │
     │◀─ alerts[]             ─────────│                │
     │                                 │                │
     │ para cada alert:                │                │
     │─ check if user registered       │                │
     │  meal in window ───────────────▶│                │
     │◀─ not_registered ───────────────│                │
     │─ send_alert(user) ─────────────▶│                │
     │                                 │─ send_msg() ──▶│
     │                                 │◀─ ok ──────────│
     │─ log_alert_sent() ─────────────▶│                │
```

### 2.4 Geração do Relatório Semanal

```
APScheduler    DB           ReportService    WeasyPrint    Notif.Svc    Telegram
     │           │                │               │              │           │
     │─ domingo 20h               │               │              │           │
     │─ get_eligible_users() ────▶│               │              │           │
     │◀─ users[] ────────────────│               │              │           │
     │                            │               │              │           │
     │ processa em lotes de 25:   │               │              │           │
     │─ get_week_data(user) ─────▶│               │              │           │
     │◀─ meals, totals, streak ──│               │              │           │
     │─ generate_suggestions()   │               │              │           │
     │  (GPT-4o summary prompt)  │               │              │           │
     │─ render_pdf() ────────────────────────────▶│              │           │
     │◀─ pdf_bytes ───────────────────────────────│              │           │
     │─ save_report() ───────────▶│               │              │           │
     │─ send_report(user, pdf) ──────────────────────────────────▶│           │
     │                            │               │              │─ sendDoc()▶│
     │─ sleep(40ms) ─ (rate limit)│               │              │           │
     │ [próximo usuário do lote]  │               │              │           │
```

### 2.5 Webhook de Pagamento (Mercado Pago)

```
MercadoPago    FastAPI        DB              NotificationSvc
     │             │            │                    │
     │─ POST ─────▶│            │                    │
     │  /webhook/  │            │                    │
     │  payment    │─ validate_signature()           │
     │             │─ 200 OK ──▶│ (responde imediato)│
     │             │            │                    │
     │             │ (async):   │                    │
     │             │─ get_subscription_status()─────▶│
     │             │            │                    │
     │             │ se approved:                    │
     │             │─ update_user_plan(premium) ────▶│
     │             │─ notify_user() ─────────────────▶│
     │             │            │                    │─ "Bem-vindo ao Premium!"
     │             │            │                    │
     │             │ se canceled/failed:             │
     │             │─ downgrade_user(free) ─────────▶│
     │             │─ notify_user() ─────────────────▶│
```

---

## 3. Architecture Decision Records (ADRs)

### ADR-001: Monolito para o MVP

**Decisão:** Monolito Python único em vez de microsserviços.  
**Motivo:** Microsserviços adicionam complexidade operacional (service discovery, comunicação entre serviços, deploys independentes) que não se justifica com equipe de 2 engenheiros e < 1.000 usuários.  
**Consequência:** Refatoração para microsserviços planejada na Fase 3 (> 50k usuários). O código deve ser organizado em módulos/services coesos desde o início para facilitar essa extração futura.

### ADR-002: PostgreSQL (Supabase) em vez de MongoDB

**Decisão:** PostgreSQL relacional.  
**Motivo:** Dados nutricionais têm schema bem definido e relações claras (User → MealLog → FoodItem). PostgreSQL com `jsonb` cobre casos de schema flexível (state_data da máquina de estados). Supabase oferece Row Level Security nativo, relevante para LGPD.  
**Consequência:** Migrations versionadas com Alembic são obrigatórias — nenhuma alteração de schema sem migration.

### ADR-003: APScheduler em vez de Celery+Redis

**Decisão:** APScheduler (AsyncIOScheduler) embutido no processo FastAPI.  
**Motivo:** Celery exige Redis como broker — adiciona um componente de infra, custo e complexidade. Para o MVP com cron jobs simples (alertas, relatório semanal, re-engajamento), APScheduler in-process é suficiente.  
**Consequência:** Se o servidor reiniciar, jobs em execução são perdidos. Mitigação: jobs são idempotentes (verificam no DB se já foram executados antes de agir). Migrar para Celery na Fase 2 se a carga de jobs crescer.

### ADR-004: WeasyPrint em vez de Puppeteer

**Decisão:** WeasyPrint (Python) para geração de PDF.  
**Motivo:** Puppeteer exige Node.js no servidor — stack mista. WeasyPrint é Python puro, sem dependência adicional. Para PDFs estáticos (relatório nutricional), qualidade é equivalente.  
**Consequência:** WeasyPrint tem limitações com JavaScript e layouts muito complexos. O template HTML do relatório deve usar CSS simples (sem JS, sem flexbox avançado, sem grid complexo).

### ADR-005: Fuzzy Match com RapidFuzz para Lookup TACO

**Decisão:** RapidFuzz (Python) para busca aproximada na base TACO/USDA.  
**Motivo:** `pg_trgm` (PostgreSQL) exige extensão e query SQL adicional por lookup. RapidFuzz em memória é mais rápido para base pequena (< 10.000 itens TACO), sem round-trip ao banco.  
**Consequência:** A base TACO/USDA é carregada em memória na inicialização da aplicação (~5MB). Aceitável para o MVP.

### ADR-006: Estado de Conversa no PostgreSQL (não Redis)

**Decisão:** Campo `conversation_state` + `state_data` (jsonb) na tabela `users`.  
**Motivo:** Redis adiciona componente de infra. Para o MVP, a latência de um SELECT por usuário (~1–5ms) é aceitável. O estado muda raramente (apenas durante fluxos de confirmação).  
**Consequência:** Migrar para Redis quando latência de estado se tornar gargalo (estimado > 5.000 usuários simultâneos).

### ADR-007: Autenticação por channel_id (sem JWT no MVP)

**Decisão:** Identificação do usuário pelo `chat_id` (Telegram) ou número de telefone E.164 (WhatsApp).  
**Motivo:** Exigir login com e-mail/senha no MVP aumentaria abandono no onboarding em 40–60%. O canal de mensagem já é o fator de autenticação — só o dono do número/chat consegue enviar mensagens para o bot.  
**Consequência:** Sem suporte a múltiplos dispositivos ou transferência de conta no MVP. Usuário que troca de número perde o histórico.

---

## 4. Estrutura de Diretórios

```
nutri_bot/
├── app/
│   ├── main.py                  # FastAPI factory, lifespan (startup/shutdown)
│   ├── config.py                # Settings via pydantic-settings (lê .env)
│   │
│   ├── routers/
│   │   ├── webhook_telegram.py  # POST /webhook/telegram
│   │   ├── webhook_whatsapp.py  # POST /webhook/whatsapp
│   │   ├── webhook_payment.py   # POST /webhook/payment
│   │   └── health.py            # GET /health, GET /ping
│   │
│   ├── services/
│   │   ├── conversation.py      # Máquina de estados; orquestra os outros services
│   │   ├── ai_service.py        # GPT-4o text, vision, Whisper
│   │   ├── nutrition.py         # Lookup TACO/USDA + enriquecimento nutricional
│   │   ├── notification.py      # Envio de mensagens Telegram + WhatsApp
│   │   ├── report.py            # Geração de PDF semanal
│   │   ├── scheduler.py         # APScheduler setup + job definitions
│   │   ├── payment.py           # Mercado Pago integration
│   │   └── analytics.py         # PostHog event tracking
│   │
│   ├── models/                  # SQLAlchemy ORM models
│   │   ├── user.py
│   │   ├── meal_log.py
│   │   ├── food_item.py
│   │   ├── water_log.py
│   │   ├── weekly_report.py
│   │   ├── payment_subscription.py
│   │   └── audit_log.py
│   │
│   ├── schemas/                 # Pydantic schemas (request/response)
│   │   ├── telegram.py          # Telegram webhook payload
│   │   ├── whatsapp.py          # Z-API webhook payload
│   │   ├── payment.py           # Mercado Pago webhook payload
│   │   ├── meal.py              # MealLog create/response
│   │   └── ai_response.py       # Structured output do GPT-4o
│   │
│   ├── db/
│   │   ├── session.py           # AsyncSession factory (asyncpg)
│   │   └── base.py              # Base declarativa SQLAlchemy
│   │
│   └── utils/
│       ├── rate_limiter.py      # Rate limiting por channel_id
│       ├── crypto.py            # AES-256 para raw_input
│       └── timezone.py          # Helpers de fuso horário (zoneinfo)
│
├── data/
│   ├── taco.json                # Base TACO (UNICAMP) normalizada
│   └── usda.json                # Subconjunto USDA relevante para BR
│
├── migrations/                  # Alembic migrations
│   ├── env.py
│   └── versions/
│       └── 001_initial_schema.py
│
├── templates/
│   └── weekly_report.html       # Template HTML para WeasyPrint
│
├── tests/
│   ├── test_nutrition.py        # NutritionService unit tests
│   ├── test_conversation.py     # State machine tests
│   ├── test_ai_accuracy.py      # Golden dataset tests
│   ├── test_webhooks.py         # Webhook endpoint integration tests
│   └── fixtures/
│       ├── golden_meals.json    # 200 casos de teste de IA
│       └── taco_sample.json     # Subconjunto TACO para testes
│
├── .env.example                 # Template de variáveis de ambiente
├── requirements.txt
├── alembic.ini
├── Procfile                     # Para Railway: web + worker
└── pyproject.toml               # Configuração de ferramentas (ruff, pytest)
```

---

## 5. Configuração de Ambiente

Todas as configurações via variáveis de ambiente. Nunca hardcoded.

```env
# .env.example

# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
OPENAI_VISION_MODEL=gpt-4o
OPENAI_WHISPER_MODEL=whisper-1

# Banco de dados
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/nutribot

# Telegram
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_WEBHOOK_SECRET=random-secret-string

# WhatsApp (Z-API)
ZAPI_INSTANCE_ID=...
ZAPI_TOKEN=...
ZAPI_WEBHOOK_SECRET=...

# Mercado Pago
MERCADOPAGO_ACCESS_TOKEN=APP_USR-...
MERCADOPAGO_WEBHOOK_SECRET=...
MERCADOPAGO_MONTHLY_PLAN_ID=...
MERCADOPAGO_ANNUAL_PLAN_ID=...

# Segurança
RAW_INPUT_ENCRYPTION_KEY=32-byte-hex-key
JWT_SECRET=...  # reservado para Fase 2

# Analytics
POSTHOG_API_KEY=phc_...
POSTHOG_HOST=https://app.posthog.com

# Monitoramento
SENTRY_DSN=https://...@sentry.io/...

# Aplicação
APP_ENV=production  # development | staging | production
LOG_LEVEL=INFO
MAINTENANCE_MODE=false
DEFAULT_TIMEZONE=America/Sao_Paulo
```

---

## 6. Arquitetura de Deploy

```
GitHub (repositório)
       │
       │ push para main
       ▼
GitHub Actions (CI)
  ├─ ruff lint
  ├─ pytest (incluindo golden dataset)
  ├─ verificação de coverage > 80%
  └─ se tudo ok → trigger deploy Railway
       │
       ▼
Railway (produção)
  ├─ Web service: uvicorn app.main:app --host 0.0.0.0 --port $PORT
  └─ (APScheduler roda dentro do mesmo processo)

Supabase
  └─ PostgreSQL (conexão via DATABASE_URL)

Serviços externos (SaaS)
  ├─ OpenAI API
  ├─ Z-API (WhatsApp)
  ├─ Mercado Pago
  ├─ PostHog
  └─ Sentry
```

**Environments:**

| Env | Branch | DB | Observações |
|-----|--------|-----|-------------|
| development | local | PostgreSQL local ou Supabase dev project | `.env` local |
| staging | `staging` | Supabase staging project | Testes de integração pré-deploy |
| production | `main` | Supabase produção | Deploy automático via Railway |

---

## 7. Decisões de Performance

| Área | Estratégia |
|------|-----------|
| Lookup TACO | Base carregada em memória na startup (`@app.on_event("startup")`) |
| Cache de alimentos comuns | Top 100 alimentos TACO com resultado pré-calculado em dict Python |
| Conexões ao banco | Connection pool asyncpg (min=2, max=10 para MVP) |
| OpenAI retries | Exponential backoff: 3s, 6s, 12s (3 tentativas máximas) |
| Broadcast de relatórios | Lotes de 25 usuários com delay de 40ms entre mensagens |
| Webhook response time | Responde 200 imediatamente, processa mensagem em background task |
