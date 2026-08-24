# 🥗 NutriBot

> Assistente nutricional conversacional para **WhatsApp e Telegram** — registre refeições por texto, foto ou áudio em português natural, sem instalar nada.

![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Anthropic](https://img.shields.io/badge/Claude-Haiku%204.5-D4A017?logo=anthropic&logoColor=white)
![Status](https://img.shields.io/badge/status-beta%20aberto-brightgreen)
![Cobertura](https://img.shields.io/badge/cobertura-72%25-brightgreen)
![Testes](https://img.shields.io/badge/testes-290%20passing-brightgreen)
![Security](https://img.shields.io/badge/security-auditado-blue)

---

## 📖 Sobre o projeto

O NutriBot é um chatbot SaaS Freemium que permite rastrear a alimentação de forma natural — o usuário manda uma mensagem como *"almocei arroz, feijão e frango"* e o bot identifica os alimentos, calcula calorias e macronutrientes usando a base **TACO** (brasileira) e **USDA**, e registra tudo automaticamente.

**Diferenciais frente a apps tradicionais (MyFitnessPal, YAZIO):**

- 📱 Funciona **dentro do WhatsApp e Telegram** — sem instalação
- 🇧🇷 Base nutricional **TACO** (alimentos brasileiros com prioridade)
- 🗣️ Entende **português coloquial** — "tomei um caldinho de feijão" funciona
- 📸 Identifica alimentos por **foto** (Claude Vision)
- 🎙️ Transcreve **áudios** de voz (Whisper)
- ⏰ Envia **alertas proativos** por janela de refeição
- 📊 Gera **relatório PDF semanal** com sugestões personalizadas de IA

---

## ✨ Funcionalidades

| Funcionalidade | Canal | Status |
|---|---|---|
| Registro por texto em PT-BR | Telegram / WhatsApp | ✅ Implementado |
| Busca fuzzy na base TACO + USDA | — | ✅ Implementado |
| Reconhecimento de foto (Claude Vision) | Telegram / WhatsApp | ✅ Implementado |
| Transcrição de áudio (Whisper) | Telegram / WhatsApp | ✅ Implementado |
| Fluxo de confirmação de refeição | Telegram / WhatsApp | ✅ Implementado |
| **Registro retroativo pelo bot** (`/registrar` + NLP) — sem limite de dias | Telegram / WhatsApp | ✅ Implementado |
| **Entrada manual de refeições no painel web** — sem limite de dias | Dashboard | ✅ Implementado |
| Alertas proativos por janela de refeição | Telegram / WhatsApp | ✅ Implementado |
| Meta de calorias diária configurável | — | ✅ Implementado |
| **Relatório PDF sob demanda** — bot e painel web (liberado após 7 dias) | Bot + Dashboard | ✅ Implementado |
| **Painel de relatórios** — gerar, baixar e limpar relatórios | Dashboard | ✅ Implementado |
| Onboarding guiado | Telegram / WhatsApp | ✅ Implementado |
| Rastreamento de água | — | ✅ Implementado |
| Planos (Freemium / Premium) + pagamento | MercadoPago | ✅ Implementado |
| Conformidade LGPD (Art. 11) | — | ✅ Implementado |
| Painel B2B para nutricionistas | — | 🗓️ Fase 2 |
| App nativo / Web | — | 🗓️ Fase 3 |

---

## 🏗️ Arquitetura

```
Usuário
  │
  ├── Telegram Bot API ──► Render (FastAPI) ──► Neon (PostgreSQL 16)
  │                             │
  └── WhatsApp Business API     ├── Anthropic API (Claude Haiku — NLP + Vision)
                                ├── OpenAI API (Whisper — só áudio)
                                ├── APScheduler (alertas) ← UptimeRobot mantém vivo
                                └── WeasyPrint (PDF)
```

**Hosting atual (MVP):** [Render](https://render.com) + [Neon](https://neon.tech)  
**Hosting de escala:** Google Cloud Run + Cloud SQL (São Paulo)  
→ Veja [`docs/infra-arch-render-neon.md`](docs/infra-arch-render-neon.md)

---

## 🛠️ Stack técnica

| Camada | Tecnologia |
|---|---|
| **Backend** | Python 3.13 · FastAPI · uvicorn |
| **Banco de dados** | PostgreSQL 16 · SQLAlchemy (asyncio) · asyncpg · Alembic |
| **AI primária** | Anthropic Claude — Haiku 4.5 (NLP) · Sonnet 4.6 (Vision) |
| **AI secundária** | OpenAI Whisper — transcrição de áudio |
| **Busca nutricional** | RapidFuzz (fuzzy matching) · TACO JSON · USDA JSON |
| **Canais** | Telegram Bot API · WhatsApp via Evolution API |
| **Alertas** | APScheduler AsyncIOScheduler · UptimeRobot (keep-alive) |
| **PDF** | WeasyPrint · Jinja2 |
| **Auth** | JWT httpOnly cookie · bcrypt · rate limiting por IP |
| **Pagamentos** | MercadoPago SDK (HMAC webhook validation) |
| **Monitoramento** | Sentry SDK · PostHog (analytics) |
| **Segurança** | Security headers · startup validation · secrets.choice |
| **Testes** | pytest · pytest-asyncio · pytest-cov |

---

## 📁 Estrutura do projeto

```
Nutri_Bot/
├── app/
│   ├── main.py                  # FastAPI app factory + lifespan
│   ├── config.py                # Pydantic-settings (env vars)
│   ├── routers/
│   │   ├── health.py            # GET /health
│   │   ├── webhook_telegram.py  # POST /webhook/telegram
│   │   ├── webhook_whatsapp.py  # POST /webhook/whatsapp
│   │   └── webhook_payment.py   # POST /webhook/payment
│   ├── services/
│   │   ├── conversation.py      # Máquina de estados conversacional (~61 KB)
│   │   ├── ai_service.py        # Integração OpenAI (texto/foto/áudio)
│   │   ├── nutrition.py         # Lookup TACO + USDA + fuzzy match
│   │   ├── scheduler.py         # APScheduler + lógica de alertas
│   │   ├── report.py            # Geração de relatório PDF semanal
│   │   ├── analytics.py         # PostHog + métricas internas
│   │   ├── notification.py      # Envio de mensagens (Telegram/WhatsApp)
│   │   └── payment.py           # MercadoPago webhook handler
│   ├── models/                  # SQLAlchemy ORM
│   │   ├── user.py
│   │   ├── meal_log.py
│   │   ├── food_item.py
│   │   ├── meal_window.py
│   │   ├── water_log.py
│   │   ├── weekly_report.py
│   │   └── payment_subscription.py
│   ├── schemas/                 # Pydantic request/response
│   │   ├── telegram.py
│   │   ├── whatsapp.py
│   │   ├── meal.py
│   │   └── ai_response.py
│   ├── db/
│   │   ├── session.py           # AsyncSession factory
│   │   └── base.py              # Base declarativa
│   └── utils/
│       ├── crypto.py            # Criptografia de dados sensíveis
│       ├── rate_limiter.py      # Rate limiting por usuário
│       └── timezone.py          # Utilitários de fuso horário (BRT)
├── data/
│   ├── taco.json                # Base TACO (alimentos brasileiros)
│   ├── usda.json                # Base USDA (complemento)
│   └── report_template.html     # Template HTML do relatório PDF
├── migrations/
│   └── versions/
│       ├── aa27ebf221d2_initial_schema.py
│       └── b3c91f4e7d02_add_report_period_fields.py
├── scripts/
│   ├── register_telegram_webhook.py   # Registrar URL no BotFather
│   ├── expand_taco.py                 # Expansão da base TACO
│   ├── testar_relatorio.py            # Gerar PDF de teste
│   ├── testar_alerta.py               # Disparar alerta manualmente
│   ├── run_bot_polling.py             # Polling local (desenvolvimento)
│   └── check_db.py                    # Verificar conexão com banco
├── tests/
│   ├── conftest.py
│   ├── test_nutrition.py
│   ├── test_conversation.py
│   ├── test_services.py
│   ├── test_sprint4.py
│   ├── test_sprint5.py
│   ├── test_webhooks.py
│   ├── test_meals_api.py          # POST /api/meals + DELETE /api/meals/{id}
│   └── fixtures/
│       ├── golden_meals.json          # Dataset de refeições para testes
│       └── taco_sample.json
├── docs/
│   ├── NutriBot_PRD_v2.1.md           # PRD principal do produto
│   ├── architecture.md                # Decisões de arquitetura
│   ├── api-spec.md                    # Especificação da API
│   ├── prompts.md                     # Prompts do sistema (OpenAI)
│   ├── fuzzy-match.md                 # Documentação do algoritmo TACO
│   ├── infra-arch-render-neon.md      # PRD de infraestrutura + migração GCP
│   └── infra-setup-render-neon.md     # Guia de setup passo a passo
├── .env.example                       # Variáveis de ambiente de exemplo
├── Dockerfile
├── Procfile                           # web: uvicorn app.main:app …
├── railway.toml                       # Config Railway (alternativa)
├── alembic.ini
├── requirements.txt
├── requirements-dev.txt
└── pyproject.toml
```

---

## 🚀 Setup rápido (desenvolvimento local)

### 1. Clonar e ativar o ambiente

```powershell
git clone https://github.com/seu-usuario/nutri-bot.git
cd Nutri_Bot
.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
```

### 2. Configurar variáveis de ambiente

```powershell
Copy-Item .env.example .env
# Edite o .env com suas credenciais
```

Variáveis obrigatórias no `.env`:

```env
DATABASE_URL=postgresql://user:pass@host.neon.tech/neondb?sslmode=require
# (pode colar a URL bruta do Neon — config.py converte para asyncpg automaticamente)

ANTHROPIC_API_KEY=sk-ant-...   # Claude — NLP + Vision (obrigatória)
OPENAI_API_KEY=sk-proj-...     # Whisper — transcrição de áudio
TELEGRAM_BOT_TOKEN=1234567890:ABCdef...
TELEGRAM_WEBHOOK_SECRET=       # gerar: python -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET=                    # gerar: mesmo comando acima
RAW_INPUT_ENCRYPTION_KEY=      # gerar: mesmo comando acima (LGPD — criptografia dos dados)
APP_ENV=development
```

> ⚠️ Em `APP_ENV=production` a aplicação **não sobe** se `JWT_SECRET`, `RAW_INPUT_ENCRYPTION_KEY` ou `TELEGRAM_WEBHOOK_SECRET` usarem os valores padrão/vazios. Isso é intencional — impede deploy acidental com configuração insegura.

### 3. Aplicar migrations

```powershell
alembic upgrade head
```

### 4. Iniciar o servidor

```powershell
uvicorn app.main:app --reload
```

API disponível em `http://localhost:8000` · Docs em `http://localhost:8000/docs`

### 5. Testar o bot localmente (polling)

```powershell
python scripts/run_bot_polling.py
```

---

## 🌐 Deploy (Render + Neon)

Para o guia completo de criação de conta e configuração:  
→ **[`docs/infra-setup-render-neon.md`](docs/infra-setup-render-neon.md)**

**Status atual: ✅ Em produção** — `https://nutri-bot-ot0p.onrender.com`

Resumo dos passos:

```
1. Criar conta em neon.tech → projeto "nutribot" → anotar DATABASE_URL
2. Criar conta em render.com → Web Service → Runtime Docker → configurar env vars
3. alembic upgrade head  (via Render Shell ou local com .env apontando para Neon)
4. python scripts/register_telegram_webhook.py
5. Configurar UptimeRobot → ping /health a cada 5 min (mantém APScheduler vivo)
```

> ⚠️ **Atenção:** A AI primária é **Anthropic** (`ANTHROPIC_API_KEY`), não OpenAI. O OpenAI é usado apenas para Whisper (áudio).

> ⚠️ **Docker:** o `Dockerfile` usa `python:3.13-slim-bookworm` — não alterar para `slim` sem versão ou as dependências do WeasyPrint falham no build.

---

## 🗺️ Roadmap de sprints (MVP)

| Sprint | Foco | Status |
|---|---|---|
| **Sprint 1** | Infra · bots · registro de refeições por texto · TACO lookup | ✅ Concluído |
| **Sprint 2** | Claude Vision (foto) · Whisper · fluxo de confirmação | ✅ Concluído |
| **Sprint 3** | Alertas por janela de refeição · meta de calorias | ✅ Concluído |
| **Sprint 4** | Relatório PDF semanal · sugestões IA · histórico | ✅ Concluído |
| **Sprint 5** | Onboarding · UX polish · dashboard web · beta fechado | ✅ Concluído |
| **Sprint 6** | Deploy Render + Neon · UptimeRobot · auditoria de segurança · beta aberto | ✅ Concluído |
| **Post-6** | Registro retroativo sem limite · relatórios pelo painel (gerar/limpar) · acesso automático após 7 dias | ✅ Concluído |
| **Fase 2** | Painel B2B para nutricionistas (R$ 79,90/mês) | 🗓️ Próxima |
| **Fase 3** | App nativo / Web | 🗓️ Planejado |

---

## 🧪 Testes

```powershell
# Suite completa (290 testes, cobertura 72%)
pytest

# Com cobertura detalhada
pytest --cov=app --cov-report=term-missing

# Arquivo específico
pytest tests/test_nutrition.py -v

# Sprint específico
pytest tests/test_sprint5.py -v

# Novos endpoints REST de refeições
pytest tests/test_meals_api.py -v
```

**Thresholds de aceitação (PRD):**

- ✅ > 80% de acurácia no reconhecimento textual — top 500 alimentos TACO
- ✅ > 75% de acurácia no reconhecimento por foto
- ✅ Alertas entregues em < 2 min em 99% dos casos
- ✅ Cobertura de testes ≥ 55% (atual: 72% · 290 testes)

---

## ⚙️ Comandos úteis

```powershell
# Gerar nova migration
alembic revision --autogenerate -m "descrição da mudança"

# Verificar conexão com banco
python scripts/check_db.py

# Registrar webhook Telegram (lê WEBHOOK_BASE_URL do .env automaticamente)
python scripts/register_telegram_webhook.py

# Diagnóstico completo do bot (health + webhook + envio de mensagem)
python scripts/test_telegram_bot.py

# Gerar relatório PDF de teste
python scripts/testar_relatorio.py

# Disparar alerta manualmente
python scripts/testar_alerta.py

# Expandir base TACO
python scripts/expand_taco.py
```

### Comandos do bot (Telegram)

| Comando | Descrição |
|---|---|
| `/start` | Onboarding ou resumo do dia |
| `/ajuda` | Lista todos os comandos |
| `/hoje` | Resumo calórico do dia |
| `/historico` | Histórico de refeições |
| `/registrar [data]` | Adicionar refeição de dia passado (ex: `/registrar ontem`, `/registrar 20/08`) |
| `/meta` | Configurar meta de calorias |
| `/agua` | Registrar consumo de água |
| `/relatorio [semana\|mes\|3meses\|total]` | Gerar relatório PDF sob demanda (liberado após 7 dias de cadastro) |
| `/relatorios` | Listar relatórios gerados |
| `/deletar` | Remover última refeição |
| `/ping` | Verificar se o bot está online |
| `/privacidade` | Informações LGPD e seus dados |
| `/deletar_dados` | Exclusão de conta (LGPD) |

---

## 🛡️ Segurança

Auditoria realizada em 2026-08-20. Controles implementados:

| Controle | Implementação |
|---|---|
| Startup validation | App não sobe em produção com secrets padrão/vazios |
| JWT storage | Cookie httpOnly apenas — nunca no response body |
| Brute force | Rate limit: 5 tentativas/5 min por IP no login |
| Timing attack | `dummy_verify()` no login quando e-mail não existe |
| Webhook Telegram | `X-Telegram-Bot-Api-Secret-Token` validado (obrigatório em prod) |
| Webhook MercadoPago | HMAC SHA-256 obrigatório em produção |
| Endpoints admin | `/scheduler/trigger` e `/scheduler/status` exigem `X-Admin-Key` |
| Security headers | `X-Frame-Options`, `HSTS`, `X-Content-Type-Options`, `Referrer-Policy` |
| Link token | Gerado com `secrets.choice()` (criptograficamente seguro) |

---

## 🔐 LGPD e privacidade

O NutriBot lida com **dados sensíveis de saúde** (LGPD Art. 11 — comportamento alimentar, metas e histórico).

| Requisito | Implementação |
|---|---|
| Consentimento explícito | Coletado no onboarding antes de qualquer registro |
| Dados sensíveis criptografados | `app/utils/crypto.py` — meal logs cifrados em repouso |
| Direito à exclusão | Exclusão lógica em ≤ 72h via comando `/deletar` |
| Audit log | Tabela `audit_logs` registra todas as operações críticas |
| Dados em território nacional | Deploy com Cloud SQL São Paulo (migração GCP) |

---

## 📚 Documentação

| Documento | Descrição |
|---|---|
| [`docs/NutriBot_PRD_v2.1.md`](docs/NutriBot_PRD_v2.1.md) | PRD completo do produto (requisitos, personas, roadmap) |
| [`docs/architecture.md`](docs/architecture.md) | Decisões de arquitetura e ADRs |
| [`docs/api-spec.md`](docs/api-spec.md) | Especificação dos endpoints da API |
| [`docs/prompts.md`](docs/prompts.md) | Prompts do sistema enviados ao Claude |
| [`docs/fuzzy-match.md`](docs/fuzzy-match.md) | Algoritmo de busca fuzzy na base TACO |
| [`docs/infra-arch-render-neon.md`](docs/infra-arch-render-neon.md) | Arquitetura de infra + plano de migração para GCP |
| [`docs/infra-setup-render-neon.md`](docs/infra-setup-render-neon.md) | Setup passo a passo: Neon + Render + Telegram |

---

## 🤝 Contribuindo

1. Crie uma branch: `git checkout -b feat/nome-da-feature`
2. Escreva testes para a mudança
3. Certifique-se que `pytest` passa com cobertura ≥ 55%
4. Abra um Pull Request com descrição clara do que foi alterado

---

### Registro retroativo de refeições

Usuários podem registrar refeições de dias passados de três formas — **sem limite de dias** (free e premium igualados):

**1. Linguagem natural no bot** — basta mencionar a data na mensagem:
```
"ontem almocei arroz, feijão e frango"
"anteontem tomei café com pão às 8h"
"dia 20 jantar pizza"
```

**2. Comando `/registrar [data]`** — abre o fluxo de registro para a data indicada:
```
/registrar ontem
/registrar anteontem
/registrar 20/08
/registrar 18/08/2026
```

**3. Painel web** — botão "＋ Adicionar refeição" na página de Histórico abre um modal com:
- Seletor de tipo de refeição
- Data pré-preenchida conforme o dia exibido
- Textarea de descrição em linguagem natural
- Processamento IA (TACO/USDA) igual ao bot
- Resultado aparece na lista sem recarregar a página

> **Retroatividade:** sem limite de dias em todos os planos (qualquer data passada é aceita).

---

### Relatórios nutricionais

**Acesso automático após 7 dias de cadastro** — sem precisar de plano Premium.

**Pelo bot (Telegram):**
```
/relatorio semana   → últimos 7 dias
/relatorio mes      → mês atual
/relatorio 3meses   → trimestre
/relatorio total    → todo o histórico
/relatorios         → lista de relatórios gerados
```

**Pelo painel web (`/relatorios`):**

| Botão | Função |
|---|---|
| **Gerar relatório** | Abre modal com 4 opções de período → gera PDF → download automático |
| **Limpar** | Remove todos os relatórios (confirmação obrigatória) |

Cada relatório inclui: médias de kcal e macros, aderência à meta, tabela por dia/semana e sugestões personalizadas de IA.

> **Novo usuário (< 7 dias):** mensagem de contagem regressiva no bot e banner informativo no painel. Acesso imediato disponível com plano Premium.

---

*NutriBot · Agosto 2026 · Python 3.13 · FastAPI · PostgreSQL · Anthropic Claude · Sprint 6 ✅ + Post-6 ✅ · Beta aberto*
