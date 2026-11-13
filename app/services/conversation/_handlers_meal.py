"""MealMixin — processamento de refeições e fluxo confirmar/corrigir."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.food_item import FoodItem
from app.models.meal_log import MealLog
from app.models.user import User
from app.services import analytics

from ._constants import (
    CONFIRM_WORDS,
    DENY_WORDS,
    MEAL_EMOJI,
    _MEAL_DEFAULT_HOURS,
    _matches_intent,
)

logger = logging.getLogger(__name__)


class MealMixin:

    _REMOVE_PATTERNS = re.compile(
        r"^(?:remover?|tirar?|tira|sem|excluir?|apagar?|deletar?)\s+(\d+)$",
        re.IGNORECASE,
    )

    # ── Handlers de estado CONFIRMING / CORRECTING ────────────────────────────

    async def _handle_confirming(self, user: User, text: str, db: AsyncSession) -> str:
        normalized = text.strip().lower()
        pending = user.state_data or {}

        if not pending:
            user.conversation_state = "IDLE"
            await db.commit()
            return "Não há registro pendente. Me conte o que você comeu!"

        action = pending.get("pending_action", "confirm_meal")

        if action == "delete_meal_pick":
            return await self._handle_delete_pick(user, normalized, db, pending)  # type: ignore[attr-defined]

        if action == "delete_meal":
            return await self._handle_delete_confirm(user, normalized, db, pending)  # type: ignore[attr-defined]

        if _matches_intent(normalized, CONFIRM_WORDS):
            return await self._save_confirmed_meal(user, db)

        if _matches_intent(normalized, DENY_WORDS):
            food_items = pending.get("food_items", [])
            self._set_timed_state(user, "CORRECTING")  # type: ignore[attr-defined]
            user.state_data = {**pending, "editing_mode": True}
            flag_modified(user, "state_data")
            await db.commit()

            if food_items:
                numbered = "\n".join(
                    f"{i + 1}. {fi['name']} ({fi['quantity_g']:.0f}g)"
                    f" — {fi['calories_kcal']:.0f} kcal"
                    for i, fi in enumerate(food_items)
                )
                return (
                    f"✏️ *O que precisa ajustar?*\n\n"
                    f"{numbered}\n\n"
                    "Me diga o que está errado, por exemplo:\n"
                    "• _'era arroz integral, não branco'_\n"
                    "• _'o frango eram 200g'_\n"
                    "• _'não tinha feijão'_\n"
                    "• _'adicionar ovo cozido'_\n\n"
                    "Ou descreva toda a refeição novamente."
                )
            return (
                "Tudo bem! ✏️ Me descreva a refeição novamente.\n"
                "Ex: 'arroz integral, feijão e frango grelhado 150g'"
            )

        return (
            "Não entendi. 😊 Responda:\n"
            "• *sim* — confirmar a refeição\n"
            "• *não* — corrigir a identificação\n"
            "• /cancelar — descartar"
        )

    async def _handle_correcting(self, user: User, text: str, db: AsyncSession) -> str:
        from app.services.ai_service import ai_service
        from app.services.nutrition import nutrition_service
        from app.utils.crypto import encrypt

        pending = user.state_data or {}
        food_items: list[dict] = pending.get("food_items", [])
        editing_mode: bool = pending.get("editing_mode", False)

        if editing_mode and food_items:
            removed = self._try_remove_item(text, food_items)
            if removed is not None:
                new_items, action_msg = removed
                if not new_items:
                    user.conversation_state = "IDLE"
                    user.state_data = None
                    await db.commit()
                    return "Ok, descartei a refeição inteira. Me conta o que comeu quando quiser! 😊"
                return await self._rebuild_confirming(user, db, pending, new_items, action_msg)

            meal_type = pending.get("meal_type", "other")
            try:
                extraction = await ai_service.extract_foods_correction(
                    food_items, text, meal_type
                )
            except Exception as e:
                logger.warning(f"extract_foods_correction falhou, usando extração simples: {e}")
                return await self._run_meal_extraction(text, user, db, is_correction=True)

            if not extraction.foods:
                return (
                    "Não entendi a correção 🤔\n"
                    "Tente ser mais específico, por ex: 'o arroz era integral' ou 'adicionar ovo'."
                )

            foods_raw = [
                {
                    "name": f.name,
                    "quantity_g": f.quantity_g,
                    "est_calories_kcal": f.est_calories_kcal,
                    "est_protein_g": f.est_protein_g,
                    "est_carb_g": f.est_carb_g,
                    "est_fat_g": f.est_fat_g,
                }
                for f in extraction.foods
            ]
            enriched = nutrition_service.enrich_foods(foods_raw)
            new_items_dicts = [
                {
                    "name": e.name,
                    "original_term": e.original_term,
                    "quantity_g": e.quantity_g,
                    "calories_kcal": e.calories_kcal,
                    "protein_g": e.protein_g,
                    "carb_g": e.carb_g,
                    "fat_g": e.fat_g,
                    "fiber_g": e.fiber_g,
                    "source": e.source,
                    "confidence_score": e.confidence_score,
                    "taco_code": e.taco_code,
                }
                for e in enriched
            ]

            new_state = dict(pending)
            new_state["meal_type"] = extraction.meal_type
            new_state["raw_input_encrypted"] = encrypt(text)
            return await self._rebuild_confirming(
                user, db, new_state, new_items_dicts, "🔄 *Corrigi para:*"
            )

        return await self._run_meal_extraction(text, user, db, is_correction=True)

    # ── Helpers de edição por item ────────────────────────────────────────────

    def _try_remove_item(
        self, text: str, food_items: list[dict]
    ) -> tuple[list[dict], str] | None:
        normalized = text.strip().lower()

        m = self._REMOVE_PATTERNS.match(normalized)
        if m:
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(food_items):
                removed_name = food_items[idx]["name"]
                new_items = [fi for i, fi in enumerate(food_items) if i != idx]
                return new_items, f"🗑️ *{removed_name}* removido."
            return None

        sem_match = re.match(
            r"^(?:sem|sem o|sem a|não tinha|nao tinha|tira o|tira a|tirar o|tirar a)\s+(.+)$",
            normalized,
        )
        if sem_match:
            term = sem_match.group(1).strip()
            for i, fi in enumerate(food_items):
                if term in fi["name"].lower() or fi["name"].lower() in term:
                    removed_name = fi["name"]
                    new_items = [item for j, item in enumerate(food_items) if j != i]
                    return new_items, f"🗑️ *{removed_name}* removido."

        return None

    async def _rebuild_confirming(
        self,
        user: User,
        db: AsyncSession,
        pending: dict,
        new_items: list[dict],
        action_msg: str,
    ) -> str:
        total_kcal = round(sum(fi["calories_kcal"] for fi in new_items), 1)
        total_protein = round(sum(fi["protein_g"] for fi in new_items), 1)
        total_carb = round(sum(fi["carb_g"] for fi in new_items), 1)
        total_fat = round(sum(fi["fat_g"] for fi in new_items), 1)
        total_fiber = round(sum(fi.get("fiber_g", 0) for fi in new_items), 1)

        new_state: dict = {k: v for k, v in pending.items() if k != "editing_mode"}
        new_state["food_items"] = new_items
        new_state["total_calories_kcal"] = total_kcal
        new_state["total_protein_g"] = total_protein
        new_state["total_carb_g"] = total_carb
        new_state["total_fat_g"] = total_fat
        new_state["total_fiber_g"] = total_fiber

        self._set_timed_state(user, "CONFIRMING")  # type: ignore[attr-defined]
        user.state_data = new_state
        flag_modified(user, "state_data")
        await db.commit()

        meal_type = new_state.get("meal_type", "other")
        emoji = MEAL_EMOJI.get(meal_type, "🍽️")
        foods_lines = "\n".join(
            f"• {fi['name']} ({fi['quantity_g']:.0f}g) — {fi['calories_kcal']:.0f} kcal"
            for fi in new_items
        )
        return (
            f"{action_msg}\n\n"
            f"{emoji} *Refeição atualizada:*\n\n"
            f"{foods_lines}\n\n"
            f"📊 *Total:* {total_kcal:.0f} kcal | "
            f"P: {total_protein:.0f}g | C: {total_carb:.0f}g | G: {total_fat:.0f}g\n\n"
            "✅ Está correto agora? Responda *sim* ou *não* para ajustar mais."
        )

    # ── Processadores de mídia ────────────────────────────────────────────────

    async def _process_text_meal(self, user: User, text: str, db: AsyncSession) -> str:
        return await self._run_meal_extraction(text, user, db)

    async def _process_photo_meal(
        self, user: User, image: bytes, caption: str | None, db: AsyncSession
    ) -> str:
        from app.services.ai_service import ai_service
        from app.services.nutrition import nutrition_service
        from app.utils.crypto import encrypt

        try:
            extraction = await ai_service.extract_foods_from_image(image, caption)
        except Exception as e:
            logger.error(f"Extração de foto falhou: {e}")
            return (
                "Não consegui analisar a foto agora 😔\n"
                "Tente novamente ou descreva a refeição em texto."
            )

        if not extraction.image_has_food or not extraction.foods:
            return (
                "Não identifiquei alimentos nessa foto 📸\n"
                "Tente uma foto mais clara e de frente para o prato.\n"
                "Ou me descreva o que você comeu em texto!"
            )

        foods_raw = [
            {
                "name": f.name,
                "quantity_g": f.quantity_g,
                "est_calories_kcal": f.est_calories_kcal,
                "est_protein_g": f.est_protein_g,
                "est_carb_g": f.est_carb_g,
                "est_fat_g": f.est_fat_g,
            }
            for f in extraction.foods
        ]
        enriched = nutrition_service.enrich_foods(foods_raw)

        total_kcal = round(sum(e.calories_kcal for e in enriched), 1)
        total_protein = round(sum(e.protein_g for e in enriched), 1)
        total_carb = round(sum(e.carb_g for e in enriched), 1)
        total_fat = round(sum(e.fat_g for e in enriched), 1)
        total_fiber = round(sum(e.fiber_g for e in enriched), 1)

        foods_lines = "\n".join(
            f"• {e.name} ({e.quantity_g:.0f}g) — {e.calories_kcal:.0f} kcal"
            for e in enriched
        )

        self._set_timed_state(user, "CONFIRMING")  # type: ignore[attr-defined]
        user.state_data = {
            "raw_input_encrypted": encrypt(caption or "foto"),
            "meal_type": extraction.meal_type,
            "input_type": "photo",
            "total_calories_kcal": total_kcal,
            "total_protein_g": total_protein,
            "total_carb_g": total_carb,
            "total_fat_g": total_fat,
            "total_fiber_g": total_fiber,
            "food_items": [
                {
                    "name": e.name,
                    "original_term": e.original_term,
                    "quantity_g": e.quantity_g,
                    "calories_kcal": e.calories_kcal,
                    "protein_g": e.protein_g,
                    "carb_g": e.carb_g,
                    "fat_g": e.fat_g,
                    "fiber_g": e.fiber_g,
                    "source": e.source,
                    "confidence_score": e.confidence_score,
                    "taco_code": e.taco_code,
                }
                for e in enriched
            ],
        }
        flag_modified(user, "state_data")
        await db.commit()

        quality_note = ""
        if extraction.image_quality == "poor":
            quality_note = "\n\n⚠️ _Foto com baixa qualidade — valores são aproximados._"

        emoji = MEAL_EMOJI.get(extraction.meal_type, "🍽️")
        return (
            f"📸 {emoji} *Identifiquei na foto:*\n\n"
            f"{foods_lines}\n\n"
            f"📊 *Total:* {total_kcal:.0f} kcal | "
            f"P: {total_protein:.0f}g | C: {total_carb:.0f}g | G: {total_fat:.0f}g"
            f"{quality_note}\n\n"
            "✅ Está correto? Responda *sim* para confirmar ou *não* para corrigir."
        )

    async def _process_audio_meal(self, user: User, audio: bytes, db) -> str:
        from app.services.ai_service import ai_service

        try:
            transcript = await ai_service.transcribe_audio(audio)
        except Exception as e:
            logger.error(f"Transcrição de áudio falhou: {e}")
            return (
                "Não consegui transcrever o áudio agora 😔\n"
                "Tente novamente ou descreva a refeição em texto."
            )

        if not transcript or not transcript.strip():
            return "Não entendi o áudio 😕\nPode digitar o que comeu?"

        return await self._run_meal_extraction(transcript.strip(), user, db)

    # ── Extração compartilhada ────────────────────────────────────────────────

    async def _run_meal_extraction(
        self,
        text: str,
        user: User,
        db: AsyncSession,
        is_correction: bool = False,
        target_date: date | None = None,
    ) -> str:
        from app.services.ai_service import ai_service
        from app.services.nutrition import nutrition_service
        from app.utils.crypto import encrypt

        if is_correction and target_date is None:
            existing = user.state_data or {}
            td_str = existing.get("target_date")
            if td_str:
                target_date = date.fromisoformat(td_str)

        try:
            extraction = await ai_service.extract_foods_from_text(text)
        except Exception as e:
            logger.error(f"Extração AI falhou: {e}")
            return (
                "Não consegui processar sua mensagem agora 😔\n"
                "Tente novamente em instantes ou descreva de forma diferente."
            )

        if not extraction.foods:
            if is_correction:
                user.conversation_state = "IDLE"
                user.state_data = None
                await db.commit()
                return "Não identifiquei alimentos na correção. Registro cancelado — me conte novamente quando quiser!"
            return (
                "Não consegui identificar alimentos na sua mensagem 🤔\n"
                "Tente ser mais específico.\n"
                "Ex: 'almocei arroz com feijão e frango grelhado'"
            )

        if target_date is None and (extraction.date_offset != 0 or extraction.date_explicit):
            tz = ZoneInfo(user.timezone or "America/Sao_Paulo")
            today = datetime.now(tz).date()

            if extraction.date_offset != 0:
                candidate = today + timedelta(days=extraction.date_offset)
            else:
                import re as _re
                m = _re.match(r'(\d{1,2})[/\-](\d{1,2})(?:[/\-](\d{2,4}))?',
                              extraction.date_explicit or "")
                candidate = None
                if m:
                    try:
                        day, month = int(m.group(1)), int(m.group(2))
                        yr_raw = m.group(3)
                        yr = int(yr_raw) if yr_raw else today.year
                        if yr < 100:
                            yr += 2000
                        candidate = date(yr, month, day)
                        if candidate > today:
                            candidate = date(yr - 1, month, day)
                    except ValueError:
                        candidate = None

            if candidate and candidate < today:
                err = self._check_backdate_limit(candidate, user)  # type: ignore[attr-defined]
                if err:
                    return err
                target_date = candidate

        foods_raw = [
            {
                "name": f.name,
                "quantity_g": f.quantity_g,
                "est_calories_kcal": f.est_calories_kcal,
                "est_protein_g": f.est_protein_g,
                "est_carb_g": f.est_carb_g,
                "est_fat_g": f.est_fat_g,
            }
            for f in extraction.foods
        ]
        enriched = nutrition_service.enrich_foods(foods_raw)

        total_kcal = round(sum(e.calories_kcal for e in enriched), 1)
        total_protein = round(sum(e.protein_g for e in enriched), 1)
        total_carb = round(sum(e.carb_g for e in enriched), 1)
        total_fat = round(sum(e.fat_g for e in enriched), 1)
        total_fiber = round(sum(e.fiber_g for e in enriched), 1)

        foods_lines = "\n".join(
            f"• {e.name} ({e.quantity_g:.0f}g) — {e.calories_kcal:.0f} kcal"
            for e in enriched
        )

        state_data: dict = {
            "raw_input_encrypted": encrypt(text),
            "meal_type": extraction.meal_type,
            "input_type": "text",
            "total_calories_kcal": total_kcal,
            "total_protein_g": total_protein,
            "total_carb_g": total_carb,
            "total_fat_g": total_fat,
            "total_fiber_g": total_fiber,
            "food_items": [
                {
                    "name": e.name,
                    "original_term": e.original_term,
                    "quantity_g": e.quantity_g,
                    "calories_kcal": e.calories_kcal,
                    "protein_g": e.protein_g,
                    "carb_g": e.carb_g,
                    "fat_g": e.fat_g,
                    "fiber_g": e.fiber_g,
                    "source": e.source,
                    "confidence_score": e.confidence_score,
                    "taco_code": e.taco_code,
                }
                for e in enriched
            ],
        }
        if target_date is not None:
            state_data["target_date"] = target_date.isoformat()

        self._set_timed_state(user, "CONFIRMING")  # type: ignore[attr-defined]
        user.state_data = state_data
        flag_modified(user, "state_data")
        await db.commit()

        emoji = MEAL_EMOJI.get(extraction.meal_type, "🍽️")

        if is_correction:
            prefix = "🔄 *Corrigi para:*\n\n"
        elif target_date is not None:
            tz = ZoneInfo(user.timezone or "America/Sao_Paulo")
            lbl = self._date_label(target_date, tz)  # type: ignore[attr-defined]
            prefix = f"📅 *{lbl.capitalize()}* — {emoji} *Identifiquei:*\n\n"
        else:
            prefix = f"{emoji} *Identifiquei sua refeição:*\n\n"

        return (
            f"{prefix}{foods_lines}\n\n"
            f"📊 *Total:* {total_kcal:.0f} kcal | "
            f"P: {total_protein:.0f}g | C: {total_carb:.0f}g | G: {total_fat:.0f}g\n\n"
            "✅ Está correto? Responda *sim* para confirmar ou *não* para corrigir."
        )

    async def _save_confirmed_meal(self, user: User, db: AsyncSession) -> str:
        pending = user.state_data or {}
        user_goal = user.daily_calorie_goal

        target_date_str = pending.get("target_date")
        logged_at_override: datetime | None = None
        target_date_obj: date | None = None
        if target_date_str:
            target_date_obj = date.fromisoformat(target_date_str)
            tz = ZoneInfo(user.timezone or "America/Sao_Paulo")
            default_hour = _MEAL_DEFAULT_HOURS.get(pending.get("meal_type", "other"), 12)
            logged_at_override = datetime(
                target_date_obj.year, target_date_obj.month, target_date_obj.day,
                default_hour, 0, 0, tzinfo=tz,
            )

        meal_log = MealLog(
            user_id=user.id,
            meal_type=pending.get("meal_type", "other"),
            raw_input_encrypted=pending.get("raw_input_encrypted"),
            input_type=pending.get("input_type", "text"),
            total_calories_kcal=pending.get("total_calories_kcal", 0.0),
            total_protein_g=pending.get("total_protein_g", 0.0),
            total_carb_g=pending.get("total_carb_g", 0.0),
            total_fat_g=pending.get("total_fat_g", 0.0),
            total_fiber_g=pending.get("total_fiber_g", 0.0),
            confirmed=True,
        )
        if logged_at_override is not None:
            meal_log.logged_at = logged_at_override
        db.add(meal_log)
        await db.flush()

        for fi in pending.get("food_items", []):
            try:
                raw_code = fi.get("taco_code") or None
                safe_code = raw_code[:32] if raw_code else None
                db.add(FoodItem(
                    meal_log_id=meal_log.id,
                    name=fi.get("name", "Alimento"),
                    original_term=fi.get("original_term"),
                    quantity_g=float(fi.get("quantity_g") or 0),
                    calories_kcal=float(fi.get("calories_kcal") or 0),
                    protein_g=float(fi.get("protein_g") or 0),
                    carb_g=float(fi.get("carb_g") or 0),
                    fat_g=float(fi.get("fat_g") or 0),
                    fiber_g=float(fi.get("fiber_g") or 0),
                    source=(fi.get("source") or "taco")[:20],
                    confidence_score=float(fi.get("confidence_score") or 1.0),
                    taco_code=safe_code,
                ))
            except Exception as e:
                logger.warning(f"[MEAL] FoodItem ignorado por dado inválido: {e} — {fi}")

        user.conversation_state = "IDLE"
        user.state_data = None
        user.state_expires_at = None
        await db.commit()

        kcal = pending.get("total_calories_kcal", 0)
        analytics.meal_confirmed(
            user.channel_id, pending.get("meal_type", "other"), float(kcal)
        )

        if target_date_obj is not None:
            tz = ZoneInfo(user.timezone or "America/Sao_Paulo")
            lbl = self._date_label(target_date_obj, tz)  # type: ignore[attr-defined]
            msg = f"✅ *Registrado para {lbl}!* {kcal:.0f} kcal\n"
            if user_goal:
                day_total = await self._get_date_total_kcal(user, db, target_date_obj)  # type: ignore[attr-defined]
                remaining = user_goal - day_total
                pct = min(100, int(day_total / user_goal * 100))
                bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
                msg += (
                    f"\n📊 {lbl.capitalize()}: {day_total:.0f} / {user_goal} kcal\n"
                    f"`{bar}` {pct}%\n"
                    f"{'⚠️ Meta atingida nesse dia!' if remaining <= 0 else f'Faltam {remaining:.0f} kcal'}"
                )
        else:
            msg = f"✅ *Refeição registrada!* {kcal:.0f} kcal\n"
            if user_goal:
                today_total = await self._get_today_total_kcal(user, db)  # type: ignore[attr-defined]
                remaining = user_goal - today_total
                pct = min(100, int(today_total / user_goal * 100))
                bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
                msg += (
                    f"\n📊 Hoje: {today_total:.0f} / {user_goal} kcal\n"
                    f"`{bar}` {pct}%\n"
                    f"{'⚠️ Meta atingida!' if remaining <= 0 else f'Faltam {remaining:.0f} kcal'}"
                )

        return msg
