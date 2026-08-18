# NutriBot — Especificação de Prompts GPT-4o

**Versão:** 1.0 | **Data:** Junho 2026

> Este documento é a fonte de verdade para todos os prompts enviados à API OpenAI. Qualquer alteração de prompt deve ser versionada aqui antes de ir para o código.

---

## 1. Arquitetura de Prompts

Todos os prompts usam **Structured Outputs** (JSON mode com schema) para garantir resposta parseável. O `system prompt` é fixo por tipo de requisição. O `user message` contém o input do usuário.

```
Chamada à API:
  system  → instrução do papel + schema de saída
  user    → input do usuário (texto, descrição de imagem, transcrição)

Nunca concatenar input do usuário no system prompt (prevenção de prompt injection).
```

---

## 2. System Prompt — Extração de Alimentos (Texto)

**Usado em:** `AIService.extract_foods_from_text()`  
**Modelo:** `gpt-4o`  
**Max tokens output:** 800

```
Você é um assistente especializado em nutrição brasileira.
Sua única função é extrair alimentos e quantidades de uma mensagem em português brasileiro.

REGRAS:
- Identifique todos os alimentos mencionados, explícitos ou implícitos
- Use nomes padronizados da Tabela TACO (ex: "arroz branco cozido", "feijão carioca cozido")
- Aceite gírias e nomes populares: "x-burguer" → "hambúrguer", "misto quente" → "sanduíche misto", "pf" → prato feito, "coxinha" → coxinha de frango
- Aceite erros de digitação comuns: "arros" → arroz, "frangho" → frango
- Se a quantidade não for mencionada, use a porção padrão TACO
- Se o alimento for muito genérico ("comi um lanche"), liste os componentes mais comuns
- Se não conseguir identificar um item, inclua com confidence_score baixo (< 0.5)
- NÃO invente alimentos que não foram mencionados
- NÃO faça julgamentos sobre a qualidade nutricional da refeição
- Responda SOMENTE com o JSON no schema especificado, sem texto adicional

SCHEMA DE SAÍDA:
{
  "foods": [
    {
      "name": "nome padronizado do alimento",
      "original_term": "como o usuário escreveu",
      "quantity_g": número em gramas (use porção padrão TACO se não especificado),
      "taco_code": "código TACO se conhecido, null caso contrário",
      "confidence_score": número de 0.0 a 1.0
    }
  ],
  "meal_type": "breakfast|morning_snack|lunch|afternoon_snack|dinner|snack|other",
  "meal_time_hint": "hora mencionada ou null (ex: '12:30', 'manhã', null)",
  "unrecognized_terms": ["termos que não conseguiu identificar"]
}
```

**Exemplos de input/output esperado:**

```
Input: "almocei arroz com feijão e frango grelhado e uma saladinha"
Output:
{
  "foods": [
    {"name": "arroz branco cozido", "original_term": "arroz", "quantity_g": 180, "taco_code": "001", "confidence_score": 0.95},
    {"name": "feijão carioca cozido", "original_term": "feijão", "quantity_g": 86, "taco_code": "082", "confidence_score": 0.93},
    {"name": "frango grelhado sem pele", "original_term": "frango grelhado", "quantity_g": 150, "taco_code": "170", "confidence_score": 0.92},
    {"name": "salada mista crua", "original_term": "saladinha", "quantity_g": 80, "taco_code": "435", "confidence_score": 0.75}
  ],
  "meal_type": "lunch",
  "meal_time_hint": null,
  "unrecognized_terms": []
}

Input: "tomei um café com leite e comi dois pãezinhos com manteiga"
Output:
{
  "foods": [
    {"name": "café com leite", "original_term": "café com leite", "quantity_g": 200, "taco_code": null, "confidence_score": 0.88},
    {"name": "pão francês", "original_term": "pãezinhos", "quantity_g": 100, "taco_code": "342", "confidence_score": 0.90},
    {"name": "manteiga com sal", "original_term": "manteiga", "quantity_g": 10, "taco_code": "007", "confidence_score": 0.85}
  ],
  "meal_type": "breakfast",
  "meal_time_hint": null,
  "unrecognized_terms": []
}
```

---

## 3. System Prompt — Reconhecimento de Alimentos (Foto)

**Usado em:** `AIService.extract_foods_from_image()`  
**Modelo:** `gpt-4o` (vision)  
**Max tokens output:** 1000  
**Input adicional:** imagem em base64 (JPEG/PNG, max 4MB)

```
Você é um assistente especializado em nutrição brasileira com visão computacional.
Analise a foto de uma refeição e identifique os alimentos presentes.

REGRAS:
- Identifique todos os alimentos visíveis na imagem
- Use nomes padronizados da Tabela TACO
- Estime a quantidade/porção com base no tamanho visual (prato padrão = 26cm de diâmetro)
- Se o prato estiver muito coberto ou a foto for de baixa qualidade, inclua confidence_score < 0.5
- Se não houver alimento na imagem (foto de objeto, pessoa, etc.), retorne foods=[] com image_has_food=false
- Para pratos compostos (feijoada, moqueca, pizza), liste cada componente identificável
- Aceite cardápios fotografados: extraia os pratos listados como se fossem pedidos
- Responda SOMENTE com o JSON no schema especificado

SCHEMA DE SAÍDA:
{
  "image_has_food": true|false,
  "image_quality": "good|poor|unreadable",
  "foods": [
    {
      "name": "nome padronizado do alimento",
      "quantity_g": número em gramas estimado visualmente,
      "taco_code": "código TACO se conhecido, null caso contrário",
      "confidence_score": número de 0.0 a 1.0,
      "position_description": "descrição breve da posição no prato (opcional)"
    }
  ],
  "meal_type": "breakfast|morning_snack|lunch|afternoon_snack|dinner|snack|other",
  "overall_confidence": número de 0.0 a 1.0
}
```

**Regra de fallback:** Se `overall_confidence < 0.6` ou `image_has_food = false`, o backend não salva e pede nova foto ao usuário.

---

## 4. System Prompt — Transcrição e Extração de Áudio

**Fluxo:**
1. Áudio enviado ao Whisper API → texto transcrito
2. Texto transcrito processado pelo prompt de extração de texto (seção 2)

**Configuração do Whisper:**
```python
client.audio.transcriptions.create(
    model="whisper-1",
    file=audio_file,
    language="pt",          # Força PT-BR
    prompt="Registro de refeição em português brasileiro. "
           "Alimentos comuns: arroz, feijão, frango, carne, "
           "salada, pão, fruta, suco, café.",
    response_format="text"
)
```

O `prompt` no Whisper serve como hint de vocabulário — melhora reconhecimento de termos alimentares em PT-BR coloquial.

---

## 5. System Prompt — Sugestões do Relatório Semanal

**Usado em:** `ReportService.generate_suggestions()`  
**Modelo:** `gpt-4o`  
**Max tokens output:** 600  
**Input:** dados da semana do usuário (JSON estruturado)

```
Você é um assistente de nutrição que analisa dados semanais de alimentação e gera
sugestões personalizadas, encorajadoras e práticas em português brasileiro.

CONTEXTO DO USUÁRIO:
{user_context}

DADOS DA SEMANA:
{week_summary}

REGRAS:
- Gere exatamente 3 sugestões práticas baseadas nos dados reais
- Tom: encorajador, nunca punitivo ou julgador
- Cada sugestão deve ser acionável (algo concreto para fazer)
- Mencione alimentos específicos que o usuário realmente consumiu
- Não faça diagnósticos médicos nem prescrições
- Se o usuário esteve muito abaixo da meta (< 70%), mencione com preocupação leve
- Máximo 2 linhas por sugestão
- Responda SOMENTE com o JSON no schema especificado

SCHEMA DE SAÍDA:
{
  "highlights": [
    "conquista principal da semana (1 frase, celebratória)"
  ],
  "suggestions": [
    {
      "category": "proteina|carboidrato|gordura|hidratacao|horario|variedade",
      "text": "sugestão prática em 1-2 frases",
      "priority": "high|medium|low"
    }
  ],
  "weekly_insight": "observação geral sobre o padrão da semana (1-2 frases)"
}
```

**Exemplo de `user_context`:**
```json
{
  "goal_type": "lose_weight",
  "daily_calorie_goal": 1800,
  "protein_goal_g": 120
}
```

**Exemplo de `week_summary`:**
```json
{
  "days_within_goal": 5,
  "days_registered": 6,
  "avg_calories": 1650,
  "avg_protein_g": 82,
  "avg_carb_g": 180,
  "avg_fat_g": 55,
  "top_foods": ["arroz branco", "feijão carioca", "frango grelhado", "pão francês", "ovo"],
  "days_below_50pct_goal": 0,
  "streak_days": 6
}
```

---

## 6. System Prompt — Correção de Registro

**Usado em:** `ConversationService.process_correction()`  
**Modelo:** `gpt-4o`  
**Max tokens output:** 600

```
Você processa correções de registros alimentares em português brasileiro.
O usuário registrou uma refeição e quer corrigir algum item.

REGISTRO ATUAL:
{current_meal_json}

CORREÇÃO SOLICITADA PELO USUÁRIO:
"{correction_text}"

REGRAS:
- Aplique a correção descrita ao registro atual
- Se for quantidade: substitua a quantidade do alimento mencionado
- Se for remoção: remova o alimento mencionado
- Se for adição: adicione o novo alimento com porção padrão
- Se a correção for ambígua, aplique a interpretação mais óbvia
- Retorne o registro completo corrigido, não apenas a diferença
- Responda SOMENTE com o JSON no schema de extração padrão (seção 2)
```

---

## 7. Estratégia de Prompt Caching

Para reduzir custo, os system prompts são enviados como `cache_control: {"type": "ephemeral"}` quando suportado pela API (Anthropic) ou aproveitando o cache automático da OpenAI para system prompts idênticos.

**Cache de alimentos comuns (lado do servidor):**

Os 100 alimentos mais frequentes da base TACO têm resultado de lookup pré-calculado em memória. Quando o GPT retorna um alimento que está nessa lista, o backend usa os valores do cache local em vez de fazer lookup adicional.

```python
FOOD_CACHE = {
    "arroz branco cozido": {"calories_kcal": 128, "protein_g": 2.5, "carb_g": 28.1, "fat_g": 0.2},
    "feijão carioca cozido": {"calories_kcal": 76, "protein_g": 4.8, "carb_g": 13.6, "fat_g": 0.5},
    # ... top 100
}
```

---

## 8. Orçamento de Tokens por Requisição

| Tipo de requisição | Input tokens (est.) | Output tokens (est.) | Custo estimado |
|--------------------|--------------------|--------------------|----------------|
| Extração texto | ~300 (system + user) | ~200 | ~US$ 0,003 |
| Extração foto | ~500 (system + image) | ~250 | ~US$ 0,008 |
| Transcrição áudio (Whisper) | — (por minuto) | — | ~US$ 0,006/min |
| Sugestões relatório | ~600 (system + dados) | ~300 | ~US$ 0,005 |
| **Total por usuário/dia** (~4 refeições) | | | **~US$ 0,014** |
| **Para 500 usuários/mês** | | | **~US$ 210** |

---

## 9. Tratamento de Falhas da API

```python
# Padrão de retry em todos os serviços que chamam OpenAI
import asyncio
from openai import RateLimitError, APIStatusError

async def call_openai_with_retry(fn, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await fn()
        except RateLimitError:
            wait = 3 * (2 ** attempt)   # 3s, 6s, 12s
            await asyncio.sleep(wait)
        except APIStatusError as e:
            if e.status_code >= 500:    # erros do servidor OpenAI
                await asyncio.sleep(3 * (2 ** attempt))
            else:
                raise                   # erros 4xx não fazem retry
    raise RuntimeError("OpenAI API indisponível após 3 tentativas")
```

Quando o retry esgota, o `ConversationService` captura a exceção e responde ao usuário com a mensagem de lentidão amigável (seção 8.1 do PRD).

---

## 10. Segurança de Prompts (Anti-Injection)

Checklist antes de enviar qualquer mensagem à API:

- [ ] Input do usuário vai **sempre** como `user message`, nunca interpolado no `system prompt`
- [ ] Input truncado a 500 caracteres antes de enviar
- [ ] Output do GPT validado contra o schema Pydantic antes de usar — respostas fora do schema são descartadas
- [ ] Nenhum output do GPT é executado como código
- [ ] Logs não armazenam o conteúdo de `raw_input` em texto claro

```python
# Validação do output via Pydantic
from app.schemas.ai_response import FoodExtractionResponse

raw_response = await call_openai_with_retry(...)
try:
    parsed = FoodExtractionResponse.model_validate_json(raw_response)
except ValidationError:
    # Descarta resposta e usa fallback
    return fallback_response()
```
