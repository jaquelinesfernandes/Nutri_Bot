# NutriBot — API Specification

**Versão:** 1.0 | **Data:** Junho 2026

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

Recebe mensagens do Z-API (WhatsApp Business).

**Headers obrigatórios:**
```
Authorization: Bearer {ZAPI_WEBHOOK_SECRET}
Content-Type: application/json
```

**Payload Z-API (simplificado):**
```json
{
  "instanceId": "ABC123",
  "messageId": "msg_xyz",
  "phone": "5511999999999",
  "fromMe": false,
  "momment": 1718000000,
  "type": "ReceivedCallback",
  "chatName": "Ana Silva",
  "senderName": "Ana Silva",
  "text": {
    "message": "almocei arroz com feijão"
  }
}
```

Para foto (`type: "ImageMessage"`):
```json
{
  "image": {
    "imageUrl": "https://...",
    "caption": "meu almoço"
  }
}
```

**Tratamento de mensagens ativas (templates):** Mensagens enviadas pelo bot ao usuário fora da janela de 24h usam templates aprovados pela Meta. O endpoint `/webhook/whatsapp` apenas recebe — envios são feitos via Z-API REST client no `NotificationService`.

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

## 3. Interfaces Internas dos Services

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

## 4. Schema de Respostas da IA (Pydantic)

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

## 5. Códigos de Resposta HTTP

| Código | Usado em | Significado |
|--------|----------|-------------|
| 200 | Todos os webhooks | Recebido com sucesso (mesmo se processamento posterior falhar) |
| 403 | Webhooks com assinatura | Assinatura inválida |
| 404 | Rotas não encontradas | — |
| 422 | Validação Pydantic | Payload malformado (não deve ocorrer em webhooks de parceiros) |
| 503 | /health | Serviço degradado |

> **Regra:** Nunca retornar 5xx para webhooks de parceiros (Telegram, Z-API, Mercado Pago). Eles fazem retry automático em erros 5xx, o que pode causar processamento duplicado. Sempre retornar 200 e tratar erros internamente.
