# NutriBot — Guia de Setup: Neon + Render + Telegram

**Tipo:** Guia de Configuração  
**Versão:** 1.0  
**Data:** Agosto 2026  
**Status:** Ativo  
**Tempo estimado:** 45–60 min  
**Canal inicial:** Telegram (só)

---

## Índice

- [Pré-requisitos](#pré-requisitos)
- [Parte 1 — Neon: criar conta e banco PostgreSQL](#parte-1--neon-criar-conta-e-banco-postgresql)
- [Parte 2 — Render: criar conta, conectar GitHub e fazer deploy](#parte-2--render-criar-conta-conectar-github-e-fazer-deploy)
- [Parte 3 — Migrations do banco (Alembic)](#parte-3--migrations-do-banco-alembic)
- [Parte 4 — Registrar webhook do Telegram](#parte-4--registrar-webhook-do-telegram)
- [Checklist de verificação final](#checklist-de-verificação-final)

---

## Pré-requisitos

Tenha em mãos antes de começar:

| Item | Como obter |
|---|---|
| **Repositório no GitHub** | Suba o código em um repo GitHub (público ou privado). O Render conecta direto ao GitHub. |
| **Token do bot Telegram** | Telegram → @BotFather → `/newbot` → anote o token (`1234567:ABCdef…`) |
| **Chave da OpenAI** | [platform.openai.com](https://platform.openai.com) → API Keys → Create new secret key |
| **JWT_SECRET gerado** | Gere agora: `.venv\Scripts\python -c "import secrets; print(secrets.token_hex(32))"` |
| **.venv ativo** | Para rodar scripts locais e migrations |

---

## Parte 1 — Neon: criar conta e banco PostgreSQL

> **Site:** [neon.tech](https://neon.tech) · Gratuito, sem cartão de crédito

### Passo 1 — Criar conta

Acesse [neon.tech](https://neon.tech) e clique em **Sign Up**.

Escolha **Continue with GitHub** — autorize o OAuth quando solicitado. Você será direcionado ao dashboard automaticamente.

---

### Passo 2 — Criar projeto "nutribot"

No dashboard, clique em **Create a project** (ou **New Project**).

Preencha:

| Campo | Valor |
|---|---|
| Project name | `nutribot` |
| Postgres version | `16` |
| Region | `AWS US East (Ohio)` — mais próxima do Brasil disponível no free tier |
| Database name | `neondb` (padrão, manter) |

Clique em **Create project**.

---

### Passo 3 — Copiar a connection string no formato correto

Após criar o projeto, o Neon exibe o modal com a connection string.

> ⚠️ **Ajuste obrigatório de formato:**
>
> O Neon exibe:  
> `postgresql://user:pass@ep-xxx.neon.tech/neondb?sslmode=require`
>
> Você precisa usar:  
> `postgresql+asyncpg://user:pass@ep-xxx.neon.tech/neondb?ssl=require`
>
> **Diferenças:**
> - Adicionar `+asyncpg` após `postgresql`
> - Trocar `sslmode=require` por `ssl=require`

Salve a string ajustada — será usada como `DATABASE_URL` no Render.

---

### Passo 4 — Verificar o banco (recomendado)

No dashboard Neon → **SQL Editor** → execute:

```sql
SELECT version();
```

Deve retornar algo como `PostgreSQL 16.x on x86_64…`. O banco está pronto.

---

## Parte 2 — Render: criar conta, conectar GitHub e fazer deploy

> **Site:** [render.com](https://render.com) · Free tier, sem cartão

### Passo 1 — Criar conta

Acesse [render.com](https://render.com) e clique em **Get Started for Free**.

Escolha **Sign up with GitHub**. Autorize o Render a acessar seus repositórios. Complete o cadastro (nome, finalidade → "Personal project").

---

### Passo 2 — Criar novo Web Service

No dashboard do Render:

```
New + → Web Service → Build and deploy from a Git repository → Next
```

---

### Passo 3 — Conectar o repositório GitHub

O Render lista seus repositórios GitHub. Se o repo do NutriBot não aparecer, clique em **Configure account** e ajuste as permissões do GitHub App do Render.

Encontre o repositório **Nutri_Bot** e clique em **Connect**.

---

### Passo 4 — Configurar o serviço

Preencha os campos na tela de configuração:

| Campo | Valor |
|---|---|
| Name | `nutribot` |
| Region | `Ohio (US East)` — mesmo da Neon |
| Branch | `main` |
| Runtime | `Docker` — o Render detecta o Dockerfile automaticamente |
| Instance Type | `Free` |

> ℹ️ **Docker vs Python nativo:** O projeto tem um `Dockerfile` na raiz. Selecionar *Docker* garante que o ambiente de produção seja idêntico ao local. O `Procfile` existente também funciona se preferir o runtime *Python*.

---

### Passo 5 — Configurar variáveis de ambiente

Role até **Environment Variables** e adicione cada variável:

```
DATABASE_URL     = postgresql+asyncpg://[user]:[pass]@[host].neon.tech/neondb?ssl=require
TELEGRAM_BOT_TOKEN = 1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ
OPENAI_API_KEY   = sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxx
JWT_SECRET       = [32+ chars hex gerado no pré-requisito]
ENVIRONMENT      = production

# Opcionais — deixar em branco por agora
SENTRY_DSN       =
WHATSAPP_API_TOKEN =
WHATSAPP_PHONE_NUMBER_ID =
```

> ⚠️ **Atenção:** O `app/config.py` usa pydantic-settings. Confirme que `WHATSAPP_API_TOKEN` tem valor padrão `None` no config — variável obrigatória sem valor trava o startup.

---

### Passo 6 — Configurar health check

Em **Health & Alerts** (ou Advanced settings):

| Campo | Valor |
|---|---|
| Health Check Path | `/health` |

A rota `/health` já está implementada em `app/routers/health.py`.

---

### Passo 7 — Iniciar o deploy

Clique em **Create Web Service**. O Render vai:

1. Clonar o repositório
2. Executar o build Docker (3–8 min na primeira vez)
3. Iniciar o container e verificar `/health`
4. Exibir status **Live** quando pronto

Acompanhe os logs em tempo real no painel **Logs**. Aguarde `Application startup complete`.

> ✅ **URL do serviço:** O Render atribui `https://nutribot-xxxx.onrender.com`. Anote — necessária para o webhook Telegram.

---

## Parte 3 — Migrations do banco (Alembic)

### Opção A — Rodar localmente (mais simples)

Com `.venv` ativo e `.env` com `DATABASE_URL` apontando para o Neon:

```powershell
.venv\Scripts\Activate.ps1
alembic upgrade head
```

**Saída esperada:**

```
INFO  [alembic.runtime.migration] Running upgrade  -> aa27ebf221d2, initial schema
INFO  [alembic.runtime.migration] Running upgrade aa27ebf221d2 -> b3c91f4e7d02, add report period fields
```

---

### Opção B — Via Render Shell

```
Render Dashboard → nutribot → Shell
```

```bash
alembic upgrade head
```

O container já tem `DATABASE_URL` configurado como variável de ambiente.

---

### Verificar tabelas no Neon SQL Editor

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;
```

**Deve retornar (9 tabelas):**

```
alembic_version
audit_logs
food_items
meal_logs
meal_windows
payment_subscriptions
users
water_logs
weekly_reports
```

---

## Parte 4 — Registrar webhook do Telegram

### Passo 1 — Definir a URL no .env local

Edite o arquivo `.env` na raiz do projeto:

```env
WEBHOOK_BASE_URL=https://nutribot-xxxx.onrender.com
# substitua pela URL real do seu serviço Render
```

---

### Passo 2 — Executar o script de registro

```powershell
.venv\Scripts\Activate.ps1
python scripts\register_telegram_webhook.py
```

O script registra `https://nutribot-xxxx.onrender.com/webhook/telegram` na Telegram Bot API.

**Saída esperada:**

```
Webhook registrado: https://nutribot-xxxx.onrender.com/webhook/telegram
{"ok": true, "result": true, "description": "Webhook was set"}
```

---

### Passo 3 — Confirmar o webhook

```powershell
$TOKEN = "seu-token-aqui"
Invoke-RestMethod "https://api.telegram.org/bot$TOKEN/getWebhookInfo" | ConvertTo-Json
```

Confirme na resposta:

- `"url"` → URL do Render com `/webhook/telegram`
- `"pending_update_count"` → `0`
- `"last_error_message"` → ausente ou vazio

---

### Passo 4 — Enviar mensagem de teste

Abra o Telegram, encontre o seu bot e envie qualquer mensagem (ex: **Olá**).

O bot deve responder. Verifique os logs no Render:

```
Render Dashboard → nutribot → Logs
```

---

## Checklist de verificação final

Confirme cada item antes de considerar o setup concluído:

- [ ] Conta Neon criada e projeto "nutribot" existente
- [ ] Connection string no formato `postgresql+asyncpg://…?ssl=require` anotada
- [ ] Conta Render criada e repositório GitHub conectado
- [ ] Web Service criado com Runtime Docker e todas as variáveis de ambiente preenchidas
- [ ] Deploy concluído com status **Live** e `Application startup complete` nos logs
- [ ] Migrations Alembic aplicadas sem erros (`alembic upgrade head`)
- [ ] 9 tabelas visíveis no SQL Editor do Neon
- [ ] Webhook registrado e confirmado via `getWebhookInfo` (url preenchida, pending=0)
- [ ] Bot respondeu à mensagem de teste no Telegram
- [ ] Health check passando: `GET https://nutribot-xxxx.onrender.com/health` retorna 200

---

## Dica: manter o APScheduler vivo no free tier

O Render suspende o container após 15 min sem requisição, o que mata o APScheduler (alertas de refeição). Para manter o app acordado:

1. Acesse [uptimerobot.com](https://uptimerobot.com) e crie conta gratuita
2. **New Monitor** → **HTTP(s)**
3. URL: `https://nutribot-xxxx.onrender.com/health`
4. Intervalo: **5 minutos**

Isso mantém o container ativo 24/7 dentro das 750h mensais gratuitas do Render.

---

*NutriBot · Guia de Setup v1.0 · Agosto 2026 · Render + Neon*
