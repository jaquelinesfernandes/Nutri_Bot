"""
AIService — integração com Anthropic Claude (NLP + Vision) e OpenAI Whisper (áudio).
System prompts completos em docs/prompts.md.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging

import anthropic

from app.config import settings
from app.schemas.ai_response import FoodExtractionResponse, ReportSuggestionsResponse

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_TEXT = """Você é um assistente especializado em nutrição brasileira.
Sua única função é extrair alimentos e quantidades de uma mensagem em português brasileiro.

REGRAS OBRIGATÓRIAS:
1. Separe SEMPRE cada alimento em um item individual. NUNCA combine dois alimentos em um só item.
   ERRADO: {"name":"pão com manteiga"}
   CERTO: {"name":"pão francês"} + {"name":"manteiga"}
2. Use nomes simples no singular, sem adjetivos de preparo desnecessários.
   ERRADO: "ovo mexido", "suco de laranja natural", "arroz branco cozido"
   CERTO: "ovo", "suco de laranja", "arroz"
3. Aceite gírias (x-burguer, misto quente, pf, coxinha) e erros de digitação (arros→arroz).
4. PORÇÕES CONSERVADORAS — quando a quantidade não for mencionada, use as referências abaixo.
   Prefira sempre a estimativa MENOR em caso de dúvida.
   - arroz: 80g (4 colheres de sopa)
   - feijão: 60g (2 colheres de sopa)
   - frango/carne: 100g (filé pequeno ou fatia fina)
   - ovo: 50g (1 unidade)
   - pão francês: 50g (1 unidade)
   - manteiga/requeijão: 10g (1 colher de chá)
   - frutas médias: 100g
   - legumes/verduras: 50g
   - oleaginosas (castanhas, nozes): 15g (punhado pequeno)
   - queijo fatiado: 20g (1 fatia)
5. Para cada alimento, forneça estimativas nutricionais por 100g nos campos est_calories_kcal, est_protein_g, est_carb_g, est_fat_g.
6. Responda SOMENTE com JSON válido, sem texto adicional, sem markdown.
7. CLASSIFICAÇÃO DE REFEIÇÃO (meal_type):
   - breakfast: café da manhã (manhã, café, pão, ovo pela manhã)
   - morning_snack: lanche da manhã (explícito "lanche da manhã", "lanchinho antes do almoço", horário 9h–11h30)
   - lunch: almoço (almoço, almoçar, meio-dia)
   - afternoon_snack: lanche da tarde (explícito "lanche da tarde", "lanchinho", horário 14h–18h)
   - dinner: jantar (jantar, janta, noite)
   - snack: lanche sem contexto claro de horário (use quando não for possível distinguir manhã/tarde)
   - other: qualquer refeição não classificável acima
8. REFERÊNCIA DE DATA (date_offset / date_explicit):
   - Se o usuário mencionar um dia passado, preencha date_offset ou date_explicit:
   - "ontem", "ontem de manhã", "ontem à noite" → date_offset: -1
   - "anteontem", "antes de ontem" → date_offset: -2
   - "há 3 dias" → date_offset: -3
   - "sexta", "sábado" (dias da semana passados) → calcule o offset em relação a hoje
   - "dia 20", "20/08", "20 de agosto", "dia 15 à noite" → date_explicit: "20/08" (formato DD/MM)
   - Se não houver referência de data passada → date_offset: 0 e date_explicit: null

SCHEMA:
{"foods":[{"name":"string","original_term":"string","quantity_g":number,"taco_code":"string|null","confidence_score":number,"est_calories_kcal":number,"est_protein_g":number,"est_carb_g":number,"est_fat_g":number}],"meal_type":"breakfast|morning_snack|lunch|afternoon_snack|dinner|snack|other","meal_time_hint":"string|null","unrecognized_terms":[],"date_offset":0,"date_explicit":null}"""

SYSTEM_PROMPT_VISION = """Você é um assistente especializado em nutrição brasileira com visão computacional.
Analise a foto de uma refeição e identifique os alimentos presentes.

REGRAS:
1. Separe cada alimento em um item individual — não combine ingredientes.
2. Use nomes simples em português brasileiro (ex: "arroz", "feijão", "frango").
3. PORÇÕES CONSERVADORAS — estime sempre para o lado menor em caso de dúvida.
   Use o prato como referência (prato raso padrão brasileiro = 26cm):
   - arroz: 80g se não cobre o prato todo (1/4 do prato = 80g, metade = 160g)
   - feijão/caldo: 60g (2 colheres de sopa)
   - proteína (frango, carne, peixe): 100g por porção visível
   - ovo: 50g por unidade
   - legumes/verduras: 50g por tipo
   - salada: 40g por tipo de folha
   - molhos/azeite: 5–10g
   - pão: 50g por unidade
   - frutas: 100g por unidade média
   - oleaginosas (castanhas): 15g (punhado pequeno)
   Um prato típico de almoço brasileiro (arroz+feijão+proteína+salada) = 600–750 kcal.
   Se a soma dos seus itens ultrapassar 900 kcal em um único prato, revise as porções para baixo.
4. Para cada alimento, forneça estimativas nutricionais por 100g: est_calories_kcal, est_protein_g, est_carb_g, est_fat_g. Isso é obrigatório.
5. Se não houver alimento na imagem, retorne foods=[] com image_has_food=false.
6. Responda SOMENTE com JSON válido, sem texto adicional, sem markdown.

SCHEMA:
{"image_has_food":true,"image_quality":"good|poor|unreadable","foods":[{"name":"string","quantity_g":number,"taco_code":"string|null","confidence_score":number,"est_calories_kcal":number,"est_protein_g":number,"est_carb_g":number,"est_fat_g":number}],"meal_type":"breakfast|morning_snack|lunch|afternoon_snack|dinner|snack|other","overall_confidence":number}"""


class AIService:
    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def _call_with_retry(self, fn, max_retries: int = 3):
        for attempt in range(max_retries):
            try:
                return await fn()
            except anthropic.RateLimitError as e:
                if attempt == max_retries - 1:
                    raise RuntimeError("Claude API: limite de requisições atingido.") from e
                wait = 5 * (attempt + 1)
                logger.warning(f"Claude rate limit — aguardando {wait}s")
                await asyncio.sleep(wait)
            except anthropic.APIStatusError as e:
                if e.status_code >= 500 and attempt < max_retries - 1:
                    logger.warning(f"Claude erro {e.status_code} — aguardando 5s")
                    await asyncio.sleep(5)
                else:
                    raise RuntimeError(f"Claude API erro {e.status_code}: {e.message}") from e

    async def extract_foods_from_text(self, text: str) -> FoodExtractionResponse:
        truncated = text[:500]

        async def _call():
            response = await self._client.messages.create(
                model=settings.anthropic_model,
                max_tokens=1500,  # 800 era insuficiente para refeições com 7+ itens
                system=SYSTEM_PROMPT_TEXT,
                messages=[{"role": "user", "content": truncated}],
            )
            raw = response.content[0].text.strip()
            # Remove possível bloco de código markdown ```json ... ```
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            try:
                return FoodExtractionResponse.model_validate_json(raw)
            except Exception as parse_err:
                # Loga o raw para diagnóstico — ajuda a entender truncamento ou schema inválido
                logger.error(
                    f"[AI] Falha ao parsear resposta da extração de texto. "
                    f"stop_reason={response.stop_reason!r} "
                    f"raw_preview={raw[:200]!r} "
                    f"erro={parse_err}"
                )
                raise

        return await self._call_with_retry(_call)

    async def extract_foods_from_image(
        self, image_bytes: bytes, caption: str | None = None
    ) -> FoodExtractionResponse:
        b64 = base64.standard_b64encode(image_bytes).decode()
        content: list[dict] = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
            }
        ]
        if caption:
            content.append({"type": "text", "text": caption[:200]})

        async def _call():
            response = await self._client.messages.create(
                model=settings.anthropic_vision_model,
                max_tokens=1000,
                system=SYSTEM_PROMPT_VISION,
                messages=[{"role": "user", "content": content}],
            )
            raw = response.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            return FoodExtractionResponse.model_validate_json(raw)

        return await self._call_with_retry(_call)

    async def transcribe_audio(self, audio_bytes: bytes) -> str:
        """Usa OpenAI Whisper — Claude não suporta transcrição de áudio."""
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.openai_api_key)

        async def _call():
            import io
            audio_file = io.BytesIO(audio_bytes)
            audio_file.name = "audio.ogg"
            transcript = await client.audio.transcriptions.create(
                model=settings.openai_whisper_model,
                file=audio_file,
                language="pt",
                prompt="Registro de refeição em português brasileiro.",
                response_format="text",
            )
            return transcript

        for attempt in range(3):
            try:
                return await _call()
            except Exception as e:
                if attempt == 2:
                    raise RuntimeError(f"Whisper falhou após 3 tentativas: {e}") from e
                await asyncio.sleep(3)

    async def generate_report_suggestions(
        self, user_context: dict, week_summary: dict
    ) -> ReportSuggestionsResponse:
        system = (
            "Você é um assistente de nutrição que analisa dados semanais e gera "
            "sugestões personalizadas, encorajadoras e práticas em português brasileiro. "
            "Tom: encorajador, nunca punitivo. Gere exatamente 3 sugestões acionáveis. "
            "Responda SOMENTE com JSON válido, sem texto adicional, sem markdown.\n"
            "ATENÇÃO: o campo category DEVE ser exatamente um destes valores (lowercase, sem acento): "
            "proteina, carboidrato, gordura, hidratacao, horario, variedade\n"
            'SCHEMA: {"highlights":["string"],"suggestions":[{"category":"proteina|carboidrato|gordura|hidratacao|horario|variedade","text":"string","priority":"high|medium|low"}],"weekly_insight":"string"}'
        )
        user_msg = (
            f"CONTEXTO DO USUÁRIO: {json.dumps(user_context, ensure_ascii=False)}\n"
            f"DADOS DA SEMANA: {json.dumps(week_summary, ensure_ascii=False)}"
        )

        async def _call():
            response = await self._client.messages.create(
                model=settings.anthropic_model,
                max_tokens=800,
                system=system,
                messages=[{"role": "user", "content": user_msg}],
            )
            raw = response.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            return ReportSuggestionsResponse.model_validate_json(raw)

        return await self._call_with_retry(_call)


ai_service = AIService()
