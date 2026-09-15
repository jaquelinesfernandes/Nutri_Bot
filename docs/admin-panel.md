# NutriBot — Painel Administrativo

> Versão inicial criada em setembro de 2026 (Sprint Admin-1)  
> Autor: equipe NutriBot

---

## Visão Geral

O painel administrativo (`/admin`) é uma interface web interna para gestão operacional do NutriBot. Ele **não** compartilha autenticação com o painel do paciente ou o painel da nutricionista — usa um sistema de senha + JWT próprio, com sessões de 2 horas.

### Acesso

```
URL:    https://nutri-bot-ot0p.onrender.com/admin
Auth:   senha via env var ADMIN_PASSWORD
Sessão: cookie httpOnly `admin_session`, TTL 2h, path=/admin
```

---

## Autenticação

- **Login:** `GET/POST /admin/login`
  - Valida `ADMIN_PASSWORD` (env var obrigatória em produção)
  - Emite JWT com claim `{"sub":"admin","type":"admin"}` — diferente dos tokens de usuário (`type=null`) e nutricionista
  - Registra IP no log a cada tentativa (bem-sucedida ou não)
- **Logout:** `POST /admin/logout` — apaga o cookie e redireciona para `/admin/login`
- **Token inválido:** qualquer rota protegida redireciona para `/admin/login` (302)

### Configurar senha

```bash
# Render Dashboard → Environment
ADMIN_PASSWORD=<senha-forte-aqui>
```

Se `ADMIN_PASSWORD` não estiver definido, a rota de login retorna HTTP 500 com mensagem de erro — o painel fica inacessível (fail-safe).

---

## Páginas

### Dashboard (`GET /admin/`)

Visão geral do sistema em tempo real:

| Seção | Dado |
|-------|------|
| Tiles | Total usuários, Novos (7d), Ativos (7d), Total refeições |
| Distribuição | Por plano (free/premium/nutritionist) + por canal (telegram/whatsapp) |
| Scheduler | Status (rodando/parado), lista de jobs com próximo disparo, botão "Acionar" |
| Últimos cadastros | Tabela com os 5 usuários mais recentes |

### Lista de Usuários (`GET /admin/usuarios`)

Tabela paginada (50/página) com:
- Busca por nome, Channel ID ou e-mail (ilike)
- Filtro por plano
- Estado de conversa destacado em amarelo quando diferente de IDLE
- Usuários anonimizados exibidos com opacidade 0.5 + badge "deletado"

### Perfil do Usuário (`GET /admin/usuarios/{user_id}`)

Ficha completa do usuário:

**Dados do usuário**
- ID (UUID), nome, e-mail, canal, Channel ID, plano + data de expiração, onboarding, LGPD consent, cadastro, último acesso, alertas, metas calórica e de água

**Estatísticas**
- Total de refeições, total de registros de água, data da última refeição

**Estado de conversa**
- Estado atual (IDLE ou outro), dados de estado (state_data como JSON), data de expiração do estado

**Ações administrativas** (não disponíveis para usuários já anonimizados)
- Alterar plano (com expiração opcional em dias)
- Limpar estado de conversa (banco + memória)
- Deletar dados LGPD (requer digitação de "CONFIRMAR" no prompt)

---

## API JSON

Todas as rotas JSON requerem o cookie `admin_session` válido. Erros retornam `{"detail": "..."}` com status HTTP adequado.

### Alterar plano

```http
POST /admin/api/usuarios/{user_id}/plano
Content-Type: application/x-www-form-urlencoded

new_plan=premium&expires_days=30
```

**Response:** `{"ok": true, "plan": "premium"}`

| Campo | Tipo | Obrigatório | Valores |
|-------|------|-------------|---------|
| new_plan | string | ✅ | free, premium, nutritionist |
| expires_days | integer | ❌ | 1–3650 (vazio = sem expiração) |

### Limpar estado de conversa

```http
POST /admin/api/usuarios/{user_id}/limpar-estado
```

**Response:** `{"ok": true, "old_state": "AWAITING_CONFIRMATION"}`

Limpa `conversation_state` → IDLE, `state_data` → null e remove o estado em memória do `ConversationService` (evita que o usuário fique preso em um fluxo mesmo após o bot reiniciar).

### Deletar dados (LGPD)

```http
POST /admin/api/usuarios/{user_id}/deletar
Content-Type: application/x-www-form-urlencoded

confirm=CONFIRMAR
```

**Response:** `{"ok": true, "message": "Usuário anonimizado com sucesso."}`

Ações executadas:
1. `deleted_at = NOW()`
2. `first_name = NULL`, `email = NULL`, `password_hash = NULL`, `lgpd_consent_at = NULL`
3. `DELETE FROM meal_logs WHERE user_id = ?`
4. `DELETE FROM water_logs WHERE user_id = ?`
5. Limpa estado em memória
6. Registra ação em `admin_logs`

> ⚠️ Irreversível. Mantém o ID/UUID para rastreabilidade de auditoria.

### Acionar job do scheduler

```http
POST /admin/api/scheduler/trigger/{job_id}
```

**Response:** `{"ok": true, "triggered": "send_meal_alerts"}`

Dispara o job imediatamente (`next_run_time = now()`). O scheduler continua sua cadência normal depois.

IDs de jobs disponíveis (verificar no dashboard):
- `send_meal_alerts`
- `send_weekly_reports`
- `check_inactive_patients`

---

## Auditoria

Toda ação via API JSON é registrada na tabela `admin_logs`:

```sql
CREATE TABLE admin_logs (
    id             BIGSERIAL PRIMARY KEY,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    action         TEXT NOT NULL,
    target_user_id UUID,
    detail         JSONB NOT NULL DEFAULT '{}'
);
```

### Ações registradas

| action | detail |
|--------|--------|
| `change_plan` | `{old, new, expires_days}` |
| `clear_state` | `{old_state}` |
| `delete_user_lgpd` | `{channel_id}` |
| `trigger_job` | `{job_id}` |

Para consultar os logs no banco:

```sql
-- Últimas 50 ações
SELECT created_at, action, target_user_id, detail
FROM admin_logs
ORDER BY created_at DESC
LIMIT 50;

-- Ações de deleção (LGPD)
SELECT * FROM admin_logs WHERE action = 'delete_user_lgpd';
```

---

## Segurança

| Aspecto | Implementação |
|---------|---------------|
| Autenticação | JWT próprio com claim `type=admin`, secret compartilhado com a app |
| Armazenamento | Cookie httpOnly, `path=/admin`, TTL 2h |
| Sessão | Não renovável automaticamente (diferente do painel de usuário) |
| Fail-safe | Painel inacessível se `ADMIN_PASSWORD` não configurado |
| Auditoria | Toda ação gravada em `admin_logs` |
| LGPD | Deleção exige confirmação explícita + registra IP implicitamente via logs |
| Isolamento | Cookie scoped a `/admin` — não vaza para outras rotas |
| Rate limit | Nenhum implementado ainda — adicionar na v2 (issue planejado) |

---

## Roadmap

### v2 (próxima iteração)

- [ ] Rate limiting no endpoint de login (5 tentativas/5min por IP)
- [ ] 2FA via TOTP (Google Authenticator)
- [ ] Visualização de `admin_logs` como tabela no próprio painel
- [ ] Gestão de assinaturas MercadoPago (reembolso, cancelamento)
- [ ] Estatísticas de receita (MRR, churn)
- [ ] Export CSV de usuários

### v3 (pós-pagamentos)

- [ ] Dashboard financeiro (MRR, LTV, cohorts)
- [ ] Gestão de cobranças em atraso
- [ ] Bulk actions (ex: enviar mensagem para todos os usuários free)

---

## Desenvolvimento Local

```bash
# Definir senha admin no .env
ADMIN_PASSWORD=admin123

# Rodar servidor
uvicorn app.main:app --reload

# Acessar
open http://localhost:8000/admin
```

A tabela `admin_logs` é criada automaticamente via `_apply_pending_ddl()` no startup — não é necessário rodar migration manual.
