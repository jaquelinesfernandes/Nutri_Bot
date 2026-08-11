# NutriBot — Arquitetura de Produção: Render + Neon → GCP

**Tipo:** PRD de Infraestrutura  
**Versão:** 1.0  
**Data:** Agosto 2026  
**Status:** Ativo — prototipagem / MVP  
**Responsável:** Engenharia

---

## Índice

1. [Contexto e objetivo](#1-contexto-e-objetivo)
2. [Componentes da arquitetura atual](#2-componentes-da-arquitetura-atual)
3. [Diagrama: Render + Neon](#3-diagrama-render--neon)
4. [Variáveis de ambiente](#4-variáveis-de-ambiente)
5. [Limitações do free tier](#5-limitações-do-free-tier)
6. [Critérios de migração para GCP](#6-critérios-de-migração-para-gcp)
7. [Plano de migração para GCP](#7-plano-de-migração-para-gcp)
8. [Diagrama pós-migração](#8-diagrama-pós-migração)
9. [Comparativo de custos](#9-comparativo-de-custos)

---

## 1. Contexto e objetivo

O NutriBot é implantado inicialmente com **Render** (app) + **Neon** (banco) para validar o protótipo e MVP com custo zero. Quando atingir os critérios de escala definidos neste documento, a arquitetura migra para **Google Cloud Platform** (região São Paulo), mantendo o Dockerfile e a estrutura FastAPI sem reescrita.

Este documento descreve a arquitetura de partida, os limites de cada componente e o roteiro de migração passo a passo.

---

## 2. Componentes da arquitetura atual

| Componente | Serviço | Plano | Responsabilidade |
|---|---|---|---|
| App (FastAPI) | Render Web Service | Free | Recebe webhook do Telegram, processa mensagens, chama OpenAI, grava no banco |
| Banco de dados | Neon PostgreSQL 16 | Free | Persistência de usuários, refeições, logs, relatórios — serverless com autoescala de conexões |
| Bot canal | Telegram Bot API | Gratuito | Canal de entrada: recebe e envia mensagens via webhook HTTPS |
| AI (NLP + Vision) | OpenAI API | Pay-as-you-go | GPT-4o para texto/áudio, GPT-4 Vision para fotos, Whisper para transcrição |
| Alertas / cron | APScheduler (in-process) | Embutido | Verifica janelas de refeição e dispara alertas via Telegram a cada hora configurada |
| Relatórios PDF | WeasyPrint (in-process) | Embutido | Gera PDF semanal a partir do template HTML + dados do banco |
| Monitoramento | Sentry SDK (FastAPI) | Free tier | Captura erros em tempo real; alertas por e-mail |

---

## 3. Diagrama: Render + Neon

```mermaid
graph TD
  U["👤 Usuário\n(app Telegram)"] --> TG["Telegram API\n(externa)"]
  TG -->|"HTTPS POST\n/webhook/telegram"| R

  subgraph render ["🟩 Render — Web Service (free tier)"]
    R["FastAPI + uvicorn\napp.main:app"]
    AP["APScheduler\n(thread interna)"]
    WP["WeasyPrint\n(geração de PDF)"]
    R --- AP
    R --- WP
  end

  R -->|"asyncpg (SSL)"| N
  R -->|"HTTPS"| OAI["OpenAI API\nGPT-4o · Whisper · Vision"]
  R -->|"Bot API HTTPS"| TG
  AP -->|"Bot API HTTPS\nalertas"| TG

  subgraph neon ["🟦 Neon — PostgreSQL 16 (serverless)"]
    N["Banco nutribot\nusers · meal_logs\nweekly_reports · …"]
  end
```

> **Nota:** Todos os processos rodam no mesmo container Render. O APScheduler roda em thread interna — se o container for suspenso por inatividade, os alertas param até o próximo acesso.

---

## 4. Variáveis de ambiente

| Variável | Formato / Exemplo | Obrigatória |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@ep-xxx.us-east-2.aws.neon.tech/neondb?ssl=require` | ✅ sim |
| `TELEGRAM_BOT_TOKEN` | `1234567890:ABCdef...` | ✅ sim |
| `OPENAI_API_KEY` | `sk-proj-...` | ✅ sim |
| `JWT_SECRET` | 32+ bytes hex | ✅ sim |
| `ENVIRONMENT` | `production` | ✅ sim |
| `SENTRY_DSN` | `https://xxx@oyyy.ingest.sentry.io/zzz` | opcional |
| `WHATSAPP_API_TOKEN` | — | deixar em branco |
| `WHATSAPP_PHONE_NUMBER_ID` | — | deixar em branco |

> ⚠️ **Formato crítico — `DATABASE_URL`:** O SQLAlchemy com asyncpg exige o prefixo `postgresql+asyncpg://`. A Neon exibe por padrão `postgresql://` — adicionar `+asyncpg` e trocar `sslmode=require` por `ssl=require`.

---

## 5. Limitações do free tier

| Serviço | Limite | Impacto prático |
|---|---|---|
| Render Web Service | 512 MB RAM · 0.1 vCPU · 750 h/mês | Suficiente até ~50 usuários simultâneos. WeasyPrint em PDFs grandes pode estourar RAM. |
| Render (sleep) | Suspende após 15 min sem requisição | APScheduler morre junto. Alertas podem falhar em janelas de silêncio. |
| Neon PostgreSQL | 512 MB storage · 1 projeto · escala a 0 | Suficiente para MVP. Cold-start do banco após inatividade pode adicionar ~200 ms. |
| Neon (conexões) | 10 conexões simultâneas no free | Sem problema até ~100 usuários. Acima disso, configurar `pool_size` e Neon Pooler. |

> 💡 **Workaround para alertas no free tier:** Configurar o [UptimeRobot](https://uptimerobot.com) (gratuito) para fazer GET em `/health` a cada 5 minutos. Mantém o container acordado dentro das 750h mensais.

---

## 6. Critérios de migração para GCP

Migrar quando **qualquer** dos gatilhos abaixo for atingido:

| Gatilho | Threshold | Motivo |
|---|---|---|
| Usuários ativos | > 100/dia | RAM do Render começa a comprometer tempo de resposta |
| Banco de dados | > 400 MB | 80% do limite Neon free tier; risco de perda de dados |
| Alertas falhando | > 5% das entregas | APScheduler morto por sleep; threshold de negócio é 99% |
| Monetização | Qualquer usuário pagante | SLA mínimo de 99,5% uptime exige infra dedicada |
| WhatsApp ativo | Qualquer volume | Webhooks de alto volume requerem resposta < 5s |

---

## 7. Plano de migração para GCP

> **Premissas:** `gcloud` CLI instalado, Docker local funcional, conta GCP com billing ativo.  
> **Tempo estimado:** 3–4 horas para um desenvolvedor familiarizado com o projeto.

### Fase 1 — Criar projeto GCP e ativar APIs (~10 min)

```bash
# Autenticar e criar projeto
gcloud auth login
gcloud projects create nutribot-prod --name="NutriBot Production"
gcloud config set project nutribot-prod

# Ativar billing via: console.cloud.google.com/billing

# Ativar APIs necessárias
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  sql-component.googleapis.com \
  cloudscheduler.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com
```

---

### Fase 2 — Criar instância Cloud SQL em São Paulo (~15 min)

```bash
# PostgreSQL 16 na região São Paulo
gcloud sql instances create nutribot-db \
  --database-version=POSTGRES_16 \
  --tier=db-f1-micro \
  --region=southamerica-east1 \
  --storage-type=SSD \
  --storage-size=10GB \
  --storage-auto-increase \
  --no-backup

# Criar banco e usuário
gcloud sql databases create nutribot --instance=nutribot-db

DB_PASS=$(python -c "import secrets; print(secrets.token_urlsafe(24))")
echo "Salve a senha: $DB_PASS"

gcloud sql users create nutribot_user \
  --instance=nutribot-db \
  --password="$DB_PASS"
```

---

### Fase 3 — Migrar dados do Neon para Cloud SQL (~20 min)

```bash
# Exportar do Neon
pg_dump \
  "postgresql://[usuario]:[senha]@[host].neon.tech/neondb?sslmode=require" \
  --no-owner --no-privileges --no-acl \
  -f nutribot_dump.sql

# Instalar Cloud SQL Auth Proxy
# Windows: https://cloud.google.com/sql/docs/postgres/connect-auth-proxy

# Iniciar proxy em outro terminal
cloud-sql-proxy nutribot-prod:southamerica-east1:nutribot-db --port 5433

# Restaurar (em outro terminal)
psql "postgresql://nutribot_user:$DB_PASS@127.0.0.1:5433/nutribot" \
  -f nutribot_dump.sql

# Verificar
psql "postgresql://nutribot_user:$DB_PASS@127.0.0.1:5433/nutribot" \
  -c "SELECT COUNT(*) FROM users;"
```

---

### Fase 4 — Adicionar endpoint interno para Cloud Scheduler (~15 min)

Esta é a **única mudança de código** necessária. O APScheduler roda acoplado ao processo — no Cloud Run com scale-to-zero, o processo não existe entre requisições. A solução é expor um endpoint HTTP que o Cloud Scheduler chama por cron externo.

**Criar `app/routers/internal.py`:**

```python
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.services import scheduler as sched_svc
import os

router = APIRouter(prefix="/internal", include_in_schema=False)

_SECRET = os.getenv("INTERNAL_SECRET", "")

def _auth(x_internal_secret: str = Header(default="")):
    if _SECRET and x_internal_secret != _SECRET:
        raise HTTPException(status_code=403)

# Chamado pelo Cloud Scheduler a cada hora configurada
@router.post("/alerts/check", dependencies=[Depends(_auth)])
async def trigger_alerts(db: AsyncSession = Depends(get_db)):
    await sched_svc.check_and_send_alerts(db)
    return {"dispatched": True}
```

**Atualizar `app/main.py`:**

```python
from app.routers import internal
app.include_router(internal.router)

# No evento de startup: desligar APScheduler se ambiente for GCP
import os

@app.on_event("startup")
async def startup():
    if os.getenv("ENVIRONMENT") != "gcp":
        scheduler.start()  # apenas em Render / local
```

---

### Fase 5 — Build e push da imagem (~10 min)

```bash
# Criar repositório de imagens em São Paulo
gcloud artifacts repositories create nutribot-repo \
  --repository-format=docker \
  --location=southamerica-east1

# Build remoto via Cloud Build (não precisa de Docker local)
gcloud builds submit \
  --tag southamerica-east1-docker.pkg.dev/nutribot-prod/nutribot-repo/nutribot:latest \
  .
```

---

### Fase 6 — Deploy no Cloud Run (~5 min)

```bash
IMAGE="southamerica-east1-docker.pkg.dev/nutribot-prod/nutribot-repo/nutribot:latest"
INSTANCE="nutribot-prod:southamerica-east1:nutribot-db"

gcloud run deploy nutribot \
  --image "$IMAGE" \
  --platform managed \
  --region southamerica-east1 \
  --allow-unauthenticated \
  --min-instances 1 \
  --max-instances 10 \
  --memory 512Mi \
  --cpu 1 \
  --add-cloudsql-instances "$INSTANCE" \
  --set-env-vars \
"DATABASE_URL=postgresql+asyncpg://nutribot_user:$DB_PASS@/nutribot?host=/cloudsql/$INSTANCE,\
TELEGRAM_BOT_TOKEN=[seu-token],\
OPENAI_API_KEY=[sua-key],\
JWT_SECRET=[seu-secret],\
INTERNAL_SECRET=[gerar-com-secrets-token-hex-32],\
ENVIRONMENT=gcp"

# Capturar URL do serviço
CLOUD_RUN_URL=$(gcloud run services describe nutribot \
  --region southamerica-east1 --format 'value(status.url)')
echo "URL: $CLOUD_RUN_URL"
```

---

### Fase 7 — Rodar migrations no Cloud SQL (~5 min)

```bash
# Criar e executar job one-shot para alembic upgrade head
gcloud run jobs create nutribot-migrate \
  --image "$IMAGE" \
  --region southamerica-east1 \
  --add-cloudsql-instances "$INSTANCE" \
  --set-env-vars "DATABASE_URL=postgresql+asyncpg://nutribot_user:$DB_PASS@/nutribot?host=/cloudsql/$INSTANCE" \
  --command "alembic" \
  --args "upgrade,head"

gcloud run jobs execute nutribot-migrate --region southamerica-east1 --wait
```

---

### Fase 8 — Cloud Scheduler (substitui APScheduler) (~10 min)

```bash
INTERNAL_SECRET="[mesmo-valor-do-env-var]"
HEADERS="Content-Type=application/json,X-Internal-Secret=$INTERNAL_SECRET"

# Café da manhã: 7h, 8h, 9h (BRT)
gcloud scheduler jobs create http nutribot-cafe \
  --schedule="0 7,8,9 * * *" --time-zone="America/Sao_Paulo" \
  --uri="$CLOUD_RUN_URL/internal/alerts/check" \
  --http-method=POST --headers="$HEADERS" --message-body="{}" \
  --location=southamerica-east1

# Almoço: 12h, 13h (BRT)
gcloud scheduler jobs create http nutribot-almoco \
  --schedule="0 12,13 * * *" --time-zone="America/Sao_Paulo" \
  --uri="$CLOUD_RUN_URL/internal/alerts/check" \
  --http-method=POST --headers="$HEADERS" --message-body="{}" \
  --location=southamerica-east1

# Lanche: 15h, 16h (BRT)
gcloud scheduler jobs create http nutribot-lanche \
  --schedule="0 15,16 * * *" --time-zone="America/Sao_Paulo" \
  --uri="$CLOUD_RUN_URL/internal/alerts/check" \
  --http-method=POST --headers="$HEADERS" --message-body="{}" \
  --location=southamerica-east1

# Jantar: 19h, 20h (BRT)
gcloud scheduler jobs create http nutribot-jantar \
  --schedule="0 19,20 * * *" --time-zone="America/Sao_Paulo" \
  --uri="$CLOUD_RUN_URL/internal/alerts/check" \
  --http-method=POST --headers="$HEADERS" --message-body="{}" \
  --location=southamerica-east1
```

---

### Fase 9 — Atualizar webhook e desativar Render (~5 min)

```bash
# Registrar nova URL no Telegram
WEBHOOK_URL="$CLOUD_RUN_URL" python scripts/register_telegram_webhook.py

# Verificar
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getWebhookInfo" | python -m json.tool

# Suspender serviço no Render (não deletar — manter como fallback)
# Render Dashboard → nutribot → Settings → Suspend Service
```

**Validação final:** Envie uma mensagem ao bot. Verifique os logs:

```bash
gcloud run services logs tail nutribot --region southamerica-east1
```

Espere a resposta em < 2s.

---

## 8. Diagrama pós-migração

```mermaid
graph TD
  U["👤 Usuário\n(app Telegram)"] --> TG["Telegram API"]
  TG -->|"Webhook HTTPS\n/webhook/telegram"| CR

  subgraph gcp ["☁️ Google Cloud — southamerica-east1 (São Paulo)"]
    CR["Cloud Run\nFastAPI · min-instances=1"]
    CS["Cloud Scheduler\ncafé · almoço · lanche · jantar"]
    SQL["Cloud SQL\nPostgreSQL 16\n(db-f1-micro)"]
    CR -->|"Cloud SQL Proxy\nUnix socket"| SQL
    CS -->|"POST /internal/alerts/check\nX-Internal-Secret"| CR
  end

  CR -->|"HTTPS"| OAI["OpenAI API\nGPT-4o · Whisper · Vision"]
  CR -->|"Bot API HTTPS"| TG
```

> **Diferenças-chave pós-migração:** APScheduler substituído por Cloud Scheduler (cron externo). Cloud SQL acessado via Unix socket sem latência de rede. `min-instances=1` garante que não há cold start para o webhook Telegram.

---

## 9. Comparativo de custos

| Componente | Render + Neon | GCP (escala) | Observação |
|---|---|---|---|
| App hosting | R$ 0 | R$ 15–40/mês | Cloud Run com min-instances=1 |
| Banco de dados | R$ 0 | R$ 40–60/mês | Cloud SQL db-f1-micro, São Paulo |
| Alertas (cron) | R$ 0 (APScheduler) | ~R$ 1/mês | Cloud Scheduler: $0.10/job/mês |
| Build (CI) | R$ 0 | R$ 0–5/mês | 120 min/dia grátis no Cloud Build |
| Monitoramento | R$ 0 (Sentry free) | R$ 0 | Cloud Logging: 50 GB/mês grátis |
| **Total estimado** | **R$ 0** | **R$ 55–105/mês** | Com 100–500 usuários ativos |

> Valores estimados em BRL (câmbio ~5,80). OpenAI API não inclusa — custo separado por chamada (GPT-4o: ~$0.0025/1K tokens input).

---

*NutriBot · PRD de Infraestrutura v1.0 · Agosto 2026*
