"""ConversationService — máquina de estados da conversa.
Estados: IDLE | ONBOARDING | CONFIRMING | CORRECTING | DELETING | BACKDATING |
         INVITE_PENDING | REVOKING
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.meal_window import MealWindow
from app.models.user import User
from app.services import analytics

from ._constants import (
    MAINTENANCE_RESPONSE,
    UNRECOGNIZED_RESPONSE,
    _matches_intent,
    CONFIRM_WORDS,
    DENY_WORDS,
)
from ._handlers_b2b import B2BMixin
from ._handlers_commands import CommandsMixin
from ._handlers_meal import MealMixin
from ._helpers import HelpersMixin

logger = logging.getLogger(__name__)


class ConversationService(HelpersMixin, MealMixin, CommandsMixin, B2BMixin):
    """Serviço principal de conversa — combina todos os mixins."""

    # ── Handlers públicos ──────────────────────────────────────────────────────

    async def handle_message(
        self,
        user: User,
        message_type: Literal["text", "photo", "audio"],
        content: str | bytes,
        caption: str | None = None,
        db: AsyncSession | None = None,
    ) -> str:
        reply = await self._dispatch_message(user, message_type, content, caption, db)
        return self._append_panel_link(reply, user)

    async def _dispatch_message(
        self,
        user: User,
        message_type: Literal["text", "photo", "audio"],
        content: str | bytes,
        caption: str | None = None,
        db: AsyncSession | None = None,
    ) -> str:
        from app.config import settings

        if settings.maintenance_mode:
            return MAINTENANCE_RESPONSE

        state = user.conversation_state

        if state not in ("IDLE", "ONBOARDING"):
            now_utc = datetime.now(ZoneInfo("UTC"))
            expires = user.state_expires_at

            if expires is None:
                expired = False
            else:
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=ZoneInfo("UTC"))
                expired = now_utc > expires

            if expired:
                user.conversation_state = "IDLE"
                user.state_data = None
                user.state_expires_at = None
                if db:
                    await db.commit()
                return (
                    "⏱️ Sua ação anterior expirou por inatividade.\n"
                    "Me conta o que você comeu, ou use /ajuda para ver os comandos."
                )
            state = user.conversation_state

        if state == "ONBOARDING":
            return await self._handle_onboarding(user, str(content), db)
        if state == "CONFIRMING":
            return await self._handle_confirming(user, str(content), db)
        if state == "CORRECTING":
            return await self._handle_correcting(user, str(content), db)
        if state == "DELETING":
            return await self._handle_deleting(user, str(content), db)
        if state == "BACKDATING":
            return await self._handle_backdating(user, str(content), db)
        if state == "INVITE_PENDING":
            return await self._handle_invite_pending(user, str(content), db)
        if state == "REVOKING":
            return await self._handle_revoking(user, str(content), db)

        # IDLE
        if message_type == "text":
            txt_idle = str(content).strip().lower()
            if txt_idle.startswith("revogar"):
                name_hint = str(content).strip()[len("revogar"):].strip()
                return await self._iniciar_revogacao(user, name_hint or None, db)
            if self._is_water_message(txt_idle):
                ml = self._parse_water_ml(txt_idle) or 250
                return await self._log_water_and_reply(user, ml, db)
            return await self._process_text_meal(user, str(content), db)
        if message_type == "photo":
            return await self._process_photo_meal(user, bytes(content), caption, db)
        if message_type == "audio":
            return await self._process_audio_meal(user, bytes(content), db)

        return UNRECOGNIZED_RESPONSE

    async def handle_command(
        self,
        user: User,
        command: str,
        args: str | None = None,
        db: AsyncSession | None = None,
    ) -> str:
        cmd = command.lower().strip("/")

        handlers = {
            "start":          self._cmd_start,
            "ajuda":          self._cmd_ajuda,
            "hoje":           self._cmd_hoje,
            "historico":      self._cmd_historico,
            "relatorios":     self._cmd_relatorios,
            "relatorio":      self._cmd_relatorio_ondemand,
            "frequencia":     self._cmd_frequencia,
            "deletar":        self._cmd_deletar_refeicao,
            "desfazer":       self._cmd_desfazer,
            "meta":           self._cmd_meta,
            "agua":           self._cmd_agua,
            "silenciar":      self._cmd_silenciar,
            "premium":        self._cmd_premium,
            "plano":          self._cmd_plano,
            "alertas":        self._cmd_alertas,
            "cancelar":       self._cmd_cancelar,
            "deletar_dados":  self._cmd_deletar_dados,
            "exportar_dados": self._cmd_exportar_dados,
            "privacidade":    self._cmd_privacidade,
            "feedback":       self._cmd_feedback,
            "vincular":       self._cmd_vincular,
            "painel":         self._cmd_painel,
            "dashboard":      self._cmd_painel,
            "registrar":      self._cmd_registrar,
        }

        handler = handlers.get(cmd)
        reply = (
            await handler(user, args, db)
            if handler
            else f"Comando /{cmd} não reconhecido. Use /ajuda para ver os disponíveis."
        )
        return self._append_panel_link(reply, user)

    # ── Handlers de estado (núcleo) ────────────────────────────────────────────

    async def _handle_onboarding(self, user: User, text: str, db: AsyncSession) -> str:
        data = {**(user.state_data or {})}
        step = data.get("step", 0)

        if step == 0:
            name = text.strip().split()[0].capitalize() if text.strip() else "usuário"
            data["name"] = name
            data["step"] = 1
            user.state_data = data
            flag_modified(user, "state_data")
            user.first_name = name
            await db.commit()
            return (
                f"Prazer, {name}! 🎉\n\n"
                "Qual é o seu principal objetivo?\n\n"
                "1️⃣ Perder peso\n"
                "2️⃣ Manter o peso\n"
                "3️⃣ Ganhar massa muscular\n\n"
                "Responda com o número ou descreva seu objetivo."
            )

        if step == 1:
            raw = text.strip().lower()
            if "1" in raw or "perder" in raw or "emagrecer" in raw:
                goal_type = "perder_peso"
                goal_label = "perder peso"
                suggested_kcal = 1500
            elif "3" in raw or "ganhar" in raw or "massa" in raw or "hipertrofia" in raw:
                goal_type = "ganhar_massa"
                goal_label = "ganhar massa muscular"
                suggested_kcal = 2500
            else:
                goal_type = "manter"
                goal_label = "manter o peso"
                suggested_kcal = 2000

            data["goal_type"] = goal_type
            data["goal_label"] = goal_label
            data["suggested_kcal"] = suggested_kcal
            data["step"] = 2
            user.state_data = data
            flag_modified(user, "state_data")
            await db.commit()

            name = data.get("name", "")
            return (
                f"Ótimo, {name}! Registrei: *{goal_label}* 💪\n\n"
                f"Qual é a sua meta diária de calorias?\n"
                f"Sugestão para seu objetivo: *{suggested_kcal} kcal*\n\n"
                "Digite o número ou responda *ok* para usar a sugestão.\n\n"
                "📋 Ao continuar, você concorda com nossa "
                "[Política de Privacidade](https://nutri.bot/privacidade) "
                "e autoriza o processamento dos seus dados de saúde conforme a LGPD (Art. 11)."
            )

        if step == 2:
            raw = text.strip().lower()
            suggested = data.get("suggested_kcal", 2000)
            if raw in ("ok", "s", "sim", "yes"):
                kcal_goal = suggested
            else:
                digits = "".join(c for c in raw if c.isdigit())
                kcal_goal = int(digits) if digits else suggested

            user.daily_calorie_goal = kcal_goal
            user.goal_type = data.get("goal_type", "manter")
            user.onboarding_complete = True
            user.lgpd_consent_at = datetime.now(ZoneInfo("UTC"))
            user.conversation_state = "IDLE"
            user.state_data = None

            for name_w, start, end in [
                ("Café da manhã", "07:00", "10:00"),
                ("Almoço",        "11:30", "14:00"),
                ("Jantar",        "18:00", "21:00"),
            ]:
                db.add(MealWindow(user_id=user.id, name=name_w, start_time=start, end_time=end))

            await db.commit()
            analytics.onboarding_completed(user.channel_id, user.channel_type, kcal_goal)

            from app.config import settings as _cfg
            from app.utils.jwt import create_magic_token
            _magic = create_magic_token(user.id, minutes=1440)
            _base = (_cfg.app_url or self._APP_URL).rstrip("/")
            _link = f"{_base}/auth/magic?t={_magic}"

            name = data.get("name", "")
            return (
                f"🎊 *Tudo certo, {name}! Bem-vindo(a) ao NutriBot!*\n\n"
                f"✅ Meta diária: *{kcal_goal} kcal*\n"
                f"✅ Objetivo: *{data.get('goal_label', '')}*\n"
                f"✅ Lembretes: ☀️ 09:30 · 🍽️ 12:30 · 🌙 19:30\n\n"
                "Agora é simples — *me conte o que comeu!*\n\n"
                "💬 Texto: _'almocei arroz com feijão e frango grelhado'_\n"
                "📸 Foto do prato (Premium)\n"
                "🎤 Áudio descrevendo a refeição (Premium)\n\n"
                f"📊 *Seu painel web:* [Abrir agora]({_link})\n"
                "_Toque em 'Adicionar à tela inicial' para instalar como app!_ 📲\n\n"
                "Use /ajuda para ver todos os comandos. 🥗"
            )

        user.conversation_state = "IDLE"
        user.state_data = None
        await db.commit()
        return UNRECOGNIZED_RESPONSE

    async def _handle_deleting(self, user: User, text: str, db: AsyncSession) -> str:
        if text.strip() == "DELETAR":
            user.deleted_at = datetime.now(ZoneInfo("UTC"))
            user.conversation_state = "IDLE"
            user.state_data = None
            await db.commit()
            return (
                "✅ Seus dados foram marcados para exclusão.\n"
                "O processo será concluído em até 72 horas, conforme a LGPD."
            )
        user.conversation_state = "IDLE"
        user.state_data = None
        await db.commit()
        return "Exclusão cancelada. Seus dados permanecem salvos."

    async def _handle_backdating(self, user: User, text: str, db: AsyncSession) -> str:
        pending = user.state_data or {}
        target_date_str = pending.get("target_date")
        if not target_date_str:
            user.conversation_state = "IDLE"
            user.state_data = None
            await db.commit()
            return "Algo deu errado. Me conta o que comeu!"
        target = date.fromisoformat(target_date_str)
        return await self._run_meal_extraction(text, user, db, target_date=target)
