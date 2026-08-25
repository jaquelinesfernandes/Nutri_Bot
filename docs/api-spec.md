# NutriBot — API Specification

**Versão:** 1.3 | **Data:** 2026-08-25

Todos os endpoints são assíncronos. A aplicação responde `200 OK` imediatamente em webhooks e processa em background task para evitar timeout.

---

## 1. Endpoints de Saúde

### GET /health

Verifica se a aplicação está operacional.

**Response 200:**
```json
{
  "status": "ok",
  "version": "1.0.0",
  "db": "connected",
  "scheduler": "running",
  "maintenance_mode": false
}
```

**Response 503 (modo manutenção ou DB offline):**
```json
{
  "status": "degraded",
  "db": "disconnected"
}
```

### GET /ping

Responde `pong` — usado pelo Railway para health check do container.

**Response 200:** `"pong"`

---

## 2. Webhooks de Entrada (Inbound)

### POST /webhook/telegram

Recebe updates do Telegram Bot API.

**Headers obrigatórios:**
```
X-Telegram-Bot-Api-Secret-Token: {TELEGRAM_WEBHOOK_SECRET}
Content-Type: application/json
```

**Validação:** O servidor verifica `X-Telegram-Bot-Api-Secret-Token` antes de processar. Retorna `403` se inválido.

**Payload (simplificado — ver Telegram Bot API docs para schema completo):**
```json
{
  "update_id": 123456789,
  "message": {
    "message_id": 1,
    "from": {
      "id": 987654321,
      "is_bot": false,
      "first_name": "Ana",
      "language_code": "pt-br"
    },
    "chat": {
      "id": 987654321,
      "type": "private"
    },
    "date": 1718000000,
    "text": "almocei arroz com feijão"
  }
}
```

Tipos de message tratados: `text`, `photo`, `voice`, `audio`, `document` (ignorado), `sticker` (ignorado).

**Response sempre:** `200 OK` com body vazio. Processamento acontece em background.

**Lógica interna:**
```
1. Valida assinatura do header
2. Extrai channel_id = message.chat.id
3. Busca ou cria User no DB
4. Verifica MAINTENANCE_MODE flag
5. Despacha para ConversationService.handle_message()
6. Responde 200 imediatamente
7. (background) ConversationService processa e envia resposta via Telegram API
```

---

### POST /webhook/whatsapp

Recebe mensagens do **Evolution API** (WhatsApp Business).

**Headers obrigatórios:**
```
Authorization: Bearer {EVOLUTION_WEBHOOK_SECRET}
Content-Type: application/json
```

**Payload Evolution API (simplificado):**
```json
{
  "event": "messages.upsert",
  "instance": "nutribot",
  "data": {
    "key": {
      "remoteJid": "5511999999999@s.whatsapp.net",
      "fromMe": false,
      "id": "MSG_ID"
    },
    "message": {
      "conversation": "almocei arroz com feijão"
    },
    "messageTimestamp": 1718000000,
    "pushName": "Ana Silva"
  }
}
```

Para foto (`imageMessage`):
```json
{
  "message": {
    "imageMessage": {
      "url": "https://...",
      "caption": "meu almoço",
      "mediaKey": "..."
    }
  }
}
```

**Tratamento de mensagens ativas:** Mensagens enviadas pelo bot ao usuário são feitas via Evolution API REST client no `NotificationService`.

**Response:** `200 OK` sempre.

---

### POST /webhook/payment

Recebe notificações de pagamento do Mercado Pago.

**Headers obrigatórios:**
```
x-signature: ts=...,v1=...
Content-Type: application/json
```

**Validação HMAC:** O servidor valida a assinatura com `MERCADOPAGO_WEBHOOK_SECRET` antes de processar. Retorna `403` se inválido.

**Payload Mercado Pago:**
```json
{
  "action": "payment.updated",
  "api_version": "v1",
  "data": {
    "id": "1234567890"
  },
  "date_created": "2026-06-15T20:00:00.000-03:00",
  "id": 123456,
  "live_mode": true,
  "type": "payment",
  "user_id": "123456789"
}
```

**Lógica interna:**
```
1. Valida assinatura HMAC
2. Responde 200 imediatamente
3. (background) Consulta Mercado Pago API pelo data.id
4. Determina ação: subscription.created | payment.failed | subscription.cancelled
5. Atualiza user.plan e subscription no DB
6. Notifica usuário via bot
```

**Eventos tratados:**

| action | Subtype | Ação |
|--------|---------|------|
| `payment.updated` | `approved` | Ativa Premium, salva subscription |
| `payment.updated` | `rejected` | Incrementa retry_count, notifica usuário |
| `subscription_preapproval.updated` | `cancelled` | Agenda downgrade para fim do período |
| `subscription_preapproval.updated` | `paused` | Igual a cancelled |

---

## 3. Endpoints REST — Refeições

Autenticação: JWT em cookie `httpOnly` (definido em `POST /api/auth/login`). Todas as rotas abaixo retornam `401` se o cookie estiver ausente ou inválido.

---

### GET /api/meals

Retorna o balanço diário de refeições para uma data.

**Query params:**

| Param | Tipo | Default | Descrição |
|---|---|---|---|
| `date` | `YYYY-MM-DD` | hoje | Data a consultar |

**Response 200:**
```json
{
  "date": "2026-08-22",
  "total_calories_kcal": 1850.0,
  "total_protein_g": 95.5,
  "total_carb_g": 210.3,
  "total_fat_g": 62.1,
  "goal_calories": 2000,
  "remaining_calories": 149.7,
  "meals": [
    {
      "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "meal_type": "lunch",
      "logged_at": "2026-08-22T12:00:00-03:00",
      "total_calories_kcal": 720.0,
      "total_protein_g": 42.0,
      "total_carb_g": 88.0,
      "total_fat_g": 18.5,
      "food_items": [
        {
          "name": "Arroz branco cozido",
          "quantity_g": 150,
          "calories_kcal": 192,
          "protein_g": 2.8,
          "carb_g": 42.3,
          "fat_g": 0.3,
          "source": "taco",
          "confidence_score": 0.97
        }
      ]
    }
  ]
}
```

---

### GET /api/meals/today

Atalho para `GET /api/meals` com `date` = hoje (fuso do usuário). Mesmo schema de resposta.

---

### GET /api/meals/week

Retorna os últimos 7 dias. Response: `list[DailyBalance]`.

---

### POST /api/meals

Cria um registro de refeição manual via painel web. Usa o mesmo pipeline de IA do bot: descrição em linguagem natural → Claude extrai alimentos → lookup TACO/USDA → persiste com `logged_at` correto.

**Request body (`application/json`):**
```json
{
  "logged_date": "2026-08-21",
  "meal_type": "lunch",
  "description": "arroz branco 150g, feijão carioca 80g e frango grelhado 120g"
}
```

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `logged_date` | `YYYY-MM-DD` | ✅ | Data da refeição. Não pode ser futura. |
| `meal_type` | string | ❌ (default `"other"`) | `breakfast` \| `morning_snack` \| `lunch` \| `afternoon_snack` \| `dinner` \| `snack` \| `other` |
| `description` | string (3–500 chars) | ✅ | Descrição em linguagem natural do que foi consumido. |

**Regras de retroatividade:**

Qualquer data passada é aceita — **sem limite de dias** (free e premium igualados). Apenas datas futuras são rejeitadas.

**Responses:**

| Código | Condição |
|---|---|
| `201` | Criado com sucesso — retorna `MealLogRead` com `food_items` |
| `401` | Não autenticado |
| `422` | Data futura / nenhum alimento identificado / descrição inválida |
| `503` | Serviço de IA temporariamente indisponível |

**Response 201:**
```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "meal_type": "lunch",
  "logged_at": "2026-08-21T12:00:00-03:00",
  "total_calories_kcal": 650.5,
  "total_protein_g": 55.2,
  "total_carb_g": 72.1,
  "total_fat_g": 14.3,
  "food_items": [...]
}
```

**Notas:**
- O `meal_type` explícito do usuário prevalece sobre o sugerido pela IA. Se enviado como `"other"`, usa a inferência da IA.
- O `logged_at` é definido como `data_alvo + hora padrão do tipo de refeição` (café=8h, almoço=12h, jantar=19h…) no fuso do usuário.
- O `raw_input` é criptografado em repouso (AES-256 Fernet, LGPD Art. 11).

---

### DELETE /api/meals/{meal_id}

Remove um registro de refeição do usuário autenticado.

**Path param:** `meal_id` — UUID da refeição.

**Responses:**

| Código | Condição |
|---|---|
| `204` | Deletado com sucesso |
| `401` | Não autenticado |
| `404` | Refeição não encontrada ou pertence a outro usuário |
| `422` | `meal_id` não é um UUID válido |

---

## 4. Endpoints REST — Relatórios

Autenticação: JWT em cookie `httpOnly`. Todas as rotas retornam `401` se ausente ou inválido.

**Acesso:** usuários com plano Premium **ou** com cadastro ≥ 7 dias têm acesso a relatórios (`User.can_access_reports`). Open beta (`REPORTS_OPEN_BETA=true`) libera para todos.

---

### GET /api/reports

Lista os relatórios gerados pelo usuário (máx. 20, ordenados por data desc).

**Response 200:**
```json
[
  {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "week_start_date": "2026-08-17",
    "period_type": "weekly",
    "generated_at": "2026-08-24T20:00:00",
    "has_pdf": true
  }
]
```

---

### POST /api/reports/generate

Gera um novo relatório sob demanda e retorna o arquivo diretamente.

**Request body:**
```json
{ "period": "semana" }
```

| Valor de `period` | Período gerado |
|---|---|
| `semana` / `week` / `7dias` | Últimos 7 dias |
| `mes` / `mês` / `month` | Do 1º dia do mês atual até hoje |
| `3meses` / `trimestre` | Últimos 3 meses (início do mês) |
| `total` / `all` | Da data de cadastro até hoje |

**Comportamento:**
- Salva **um único** `WeeklyReport` no banco.
- Retorna o PDF (ou HTML se WeasyPrint indisponível) diretamente no body — sem redirect.

**Responses:**

| Código | Condição |
|---|---|
| `201` | PDF gerado — `Content-Type: application/pdf`, `Content-Disposition: attachment` |
| `401` | Não autenticado |
| `403` | Cadastro com menos de 7 dias e sem plano Premium |
| `422` | `period` inválido / período sem dados |
| `503` | Erro interno ao gerar relatório |

---

### GET /api/reports/{report_id}/download

Re-renderiza e faz download de um relatório existente **sem** criar novo registro no banco.

**Path param:** `report_id` — UUID do relatório.

**Responses:**

| Código | Condição |
|---|---|
| `200` | PDF/HTML do relatório — `Content-Disposition: attachment` |
| `401` | Não autenticado |
| `404` | Relatório não encontrado ou de outro usuário |

---

### DELETE /api/reports

Remove **todos** os relatórios do usuário autenticado.

**Response 200:**
```json
{ "deleted": 5, "message": "5 relatório(s) removido(s)." }
```

| Código | Condição |
|---|---|
| `200` | Sucesso (mesmo se não havia relatórios — `deleted: 0`) |
| `401` | Não autenticado |

---

## 5. Endpoints — Autenticação

### GET /login

Renderiza a página de login (Jinja2).

Aceita query params para exibir mensagens:

| Param | Descrição |
|---|---|
| `error` | Código de erro (`invalid_credentials`, `account_deleted`, `magic_expired`, `magic_invalid`, `magic_used`, `magic_type`) |
| `success` | Código de sucesso (`magic_sent`) |

---

### POST /dashboard/login  *(HTML form)*

Autentica via formulário web com e-mail + senha.  
Rate limit: **5 tentativas / 5 min** por IP — mensagem de erro inclui countdown preciso (ex.: "Aguarde 4min 23s.").  
Proteção timing-attack: `dummy_verify()` é chamado mesmo quando o usuário não existe.

**Form fields:** `email`, `password`

**Redirect em sucesso:** `302 → /dashboard`  
**Redirect em erro:** `302 → /login?error=<código>`

---

### POST /api/auth/register  *(JSON API)*

Cria uma nova conta. Retorna JWT em cookie `httpOnly`.  
Rate limit: **5 cadastros / hora** por IP.

**Request body:**
```json
{
  "name": "Ana Silva",
  "email": "ana@example.com",
  "password": "senha-segura",
  "daily_calorie_goal": 2000
}
```

**Response 201:** `AuthResponse` — JWT definido em cookie `httpOnly`, **não** retornado no body.

| Código | Condição |
|---|---|
| `201` | Conta criada |
| `400` | E-mail já cadastrado |
| `422` | Dados inválidos |
| `429` | Rate limit atingido |

---

### POST /api/auth/login  *(JSON API)*

Autentica com e-mail + senha. Retorna JWT em cookie `httpOnly`.  
Rate limit: **5 tentativas / 5 min** por IP.

| Código | Condição |
|---|---|
| `200` | Autenticado — cookie definido |
| `401` | Credenciais inválidas |
| `429` | Rate limit atingido (body inclui `retry_after` em segundos) |

---

### POST /api/auth/logout

Limpa o cookie de sessão (define `max_age=0`).

**Response 200:** `{ "message": "Logout realizado com sucesso." }`

---

### GET /esqueci-senha

Renderiza a página de recuperação de senha (Jinja2).

Query param `?sent=1` exibe a tela de confirmação de envio (estado pós-submit).

---

### POST /auth/esqueci-senha  *(HTML form)*

Inicia a recuperação de acesso via magic link enviado ao Telegram do usuário.

**Comportamento anti-enumeração:** sempre redireciona para `/esqueci-senha?sent=1`, independente de o e-mail existir ou não.

**Lógica interna:**
```
1. Busca usuário pelo e-mail informado
2. Se encontrado e channel_type == "telegram":
   a. Gera JWT de 30 min com type='magic'
   b. Envia link /auth/magic?t={token} via Telegram Bot API sendMessage
3. Sempre: redirect 302 → /esqueci-senha?sent=1
```

**Form field:** `email`

---

### GET /auth/magic

Autentica o usuário via magic link (token JWT de curta duração).

**Query param:** `t` — JWT com `type='magic'` e `exp` de 10 min (fluxo `/painel`) ou 30 min (fluxo recuperação de senha).

**Lógica:**
```
1. Decodifica o JWT; verifica type == 'magic' e exp
2. Busca o usuário pelo sub (UUID)
3. Emite cookie de sessão completo (365 dias, sliding)
4. Redirect 302 → /dashboard
```

| Código | Condição |
|---|---|
| `302 → /dashboard` | Autenticado com sucesso |
| `302 → /login?error=magic_expired` | Token expirado |
| `302 → /login?error=magic_invalid` | Token inválido ou mal-formado |
| `302 → /login?error=magic_type` | JWT não é do tipo `magic` |
| `302 → /login?error=account_deleted` | Usuário não encontrado no banco |

---

### Sessão e Sliding Expiration

O JWT de sessão tem duração de **365 dias**. O `SlidingSessionMiddleware` renova automaticamente o cookie quando restar ≤ 30 dias de validade — o usuário jamais precisa re-logar enquanto usar o painel ao menos uma vez a cada ~335 dias.

O middleware é ignorado para rotas de API, webhooks e arquivos estáticos (prefixos `/api/`, `/webhook/`, `/static/`, `/health`, `/ping`, `/scheduler/`, `/docs`, `/redoc`, `/openapi`).

---

## 6. Interfaces Internas dos Services

Estas não são rotas HTTP — são contratos internos entre módulos Python, documentados aqui para referência da equipe.

### ConversationService

```python
class ConversationService:
    async def handle_message(
        self,
        user: User,
        message_type: Literal["text", "photo", "audio"],
        content: str | bytes,       # texto ou bytes da mídia
        caption: str | None = None  # caption de fotos
    ) -> str:
        """
        Orquestra o processamento de uma mensagem.
        Retorna o texto de resposta para enviar ao usuário.
        Atualiza conversation_state do usuário no DB.
        """

    async def handle_command(
        self,
        user: User,
        command: str,               # ex: "/hoje", "/historico"
        args: str | None = None
    ) -> str:
        """
        Processa um comando explícito do usuário.
        """
```

### AIService

```python
class AIService:
    async def extract_foods_from_text(
        self,
        text: str
    ) -> FoodExtractionResponse:
        """
        Chama GPT-4o com o prompt de extração de texto.
        Retorna schema validado com lista de alimentos.
        """

    async def extract_foods_from_image(
        self,
        image_bytes: bytes,
        caption: str | None = None
    ) -> FoodExtractionResponse:
        """
        Chama GPT-4o Vision com a imagem em base64.
        """

    async def transcribe_audio(
        self,
        audio_bytes: bytes
    ) -> str:
        """
        Chama Whisper API e retorna transcrição em texto.
        """

    async def generate_report_suggestions(
        self,
        user_context: dict,
        week_summary: dict
    ) -> ReportSuggestionsResponse:
        """
        Gera sugestões personalizadas para o relatório semanal.
        """
```

### NutritionService

```python
class NutritionService:
    def enrich_foods(
        self,
        foods: list[ExtractedFood]
    ) -> list[EnrichedFood]:
        """
        Para cada alimento extraído pelo GPT:
        1. Tenta match no FoodCache (top 100 alimentos)
        2. Tenta fuzzy match em taco.json (RapidFuzz, threshold 80)
        3. Tenta fuzzy match em usda.json
        4. Se não encontrar: usa estimativa do GPT (source="gpt_estimated")
        Retorna lista com calorias e macros preenchidos.
        """

    def calculate_daily_balance(
        self,
        user: User,
        date: date
    ) -> DailyBalance:
        """
        Soma todos os MealLogs do usuário na data.
        Retorna totais vs meta.
        """
```

### NotificationService

```python
class NotificationService:
    async def send_text(
        self,
        user: User,
        text: str,
        reply_markup: dict | None = None  # inline keyboard buttons
    ) -> None:
        """
        Envia mensagem de texto via Telegram ou WhatsApp
        baseado em user.channel_type.
        """

    async def send_document(
        self,
        user: User,
        document_bytes: bytes,
        filename: str,
        caption: str | None = None
    ) -> None:
        """
        Envia arquivo (PDF do relatório) via Telegram ou WhatsApp.
        """
```

---

## 7. Schema de Respostas da IA (Pydantic)

```python
# app/schemas/ai_response.py

from pydantic import BaseModel, Field
from typing import Literal

class ExtractedFoodItem(BaseModel):
    name: str
    original_term: str
    quantity_g: float = Field(gt=0)
    taco_code: str | None = None
    confidence_score: float = Field(ge=0.0, le=1.0)

class FoodExtractionResponse(BaseModel):
    foods: list[ExtractedFoodItem]
    meal_type: Literal["breakfast", "lunch", "dinner", "snack", "other"]
    meal_time_hint: str | None = None
    unrecognized_terms: list[str] = []
    # campos adicionais para foto:
    image_has_food: bool = True
    image_quality: Literal["good", "poor", "unreadable"] = "good"
    overall_confidence: float = Field(default=1.0, ge=0.0, le=1.0)

class ReportSuggestion(BaseModel):
    category: Literal["proteina", "carboidrato", "gordura", "hidratacao", "horario", "variedade"]
    text: str
    priority: Literal["high", "medium", "low"]

class ReportSuggestionsResponse(BaseModel):
    highlights: list[str]
    suggestions: list[ReportSuggestion]
    weekly_insight: str
```

---

## 8. Códigos de Resposta HTTP

| Código | Usado em | Significado |
|--------|----------|-------------|
| 200 | Webhooks, `DELETE /api/reports` | Recebido / operação concluída com sucesso |
| 201 | `POST /api/meals`, `POST /api/reports/generate` | Recurso criado com sucesso |
| 204 | `DELETE /api/meals/{id}` | Refeição deletada com sucesso (sem body) |
| 401 | Endpoints REST autenticados | JWT ausente ou inválido |
| 403 | Webhooks com assinatura, `POST /api/reports/generate` | Assinatura inválida ou acesso negado (cadastro < 7 dias sem Premium) |
| 404 | `DELETE /api/meals/{id}`, `GET /api/reports/{id}/download` | Recurso não encontrado ou de outro usuário |
| 422 | Validação Pydantic / regras de negócio | Payload malformado, data futura, IA sem alimentos, período inválido |
| 503 | `/health`, `POST /api/meals`, `POST /api/reports/generate` | Serviço degradado ou IA indisponível |

> **Regra:** Nunca retornar 5xx para webhooks de parceiros (Telegram, Evolution API, Mercado Pago). Eles fazem retry automático em erros 5xx, o que pode causar processamento duplicado. Sempre retornar 200 e tratar erros internamente.
