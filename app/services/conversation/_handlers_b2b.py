"""B2BMixin — fluxos de convite e revogação de nutricionista."""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

from ._constants import CONFIRM_WORDS, DENY_WORDS

logger = logging.getLogger(__name__)


class B2BMixin:

    async def _iniciar_convite(self, user: User, token: str, db: AsyncSession) -> str:
        from app.models.nutritionist_patient import NutritionistPatient
        from sqlalchemy import select as sa_select

        result = await db.execute(
            sa_select(NutritionistPatient).where(NutritionistPatient.invite_token == token)
        )
        link = result.scalar_one_or_none()

        if not link:
            return (
                "❌ Link de convite inválido ou expirado.\n"
                "Peça à sua nutricionista um novo convite."
            )
        if link.status != "pending":
            status_msgs = {
                "active":   "Este convite já foi aceito anteriormente.",
                "declined": "Este convite já foi recusado.",
                "expired":  "Este convite expirou. Peça à sua nutricionista um novo link.",
                "revoked":  "Este vínculo foi revogado.",
            }
            return status_msgs.get(link.status, "Este convite não está mais disponível.")

        if datetime.utcnow() > link.expires_at.replace(tzinfo=None):
            link.status = "expired"
            await db.commit()
            return "⌛ Este convite expirou (válido por 7 dias). Peça à sua nutricionista um novo link."

        from sqlalchemy import select as _sel
        nutri_result = await db.execute(_sel(User).where(User.id == link.nutritionist_id))
        nutri = nutri_result.scalar_one_or_none()
        nutri_name = nutri.first_name or "Sua nutricionista" if nutri else "Sua nutricionista"
        crn = (nutri.state_data or {}).get("crn", "CRN não informado") if nutri else "CRN não informado"

        user.conversation_state = "INVITE_PENDING"
        user.state_data = {"invite_token": token, "nutri_name": nutri_name, "crn": crn}
        self._set_timed_state(user, "INVITE_PENDING")  # type: ignore[attr-defined]
        await db.commit()

        return (
            f"👩‍⚕️ *{nutri_name}* ({crn}) quer acompanhar sua alimentação pelo NutriBot.\n\n"
            "Ela poderá ver seus registros diários e relatórios.\n"
            "Você pode revogar esse acesso quando quiser digitando /privacidade.\n\n"
            "✅ Aceita? Responda *SIM* ou *NÃO*."
        )

    async def _handle_invite_pending(self, user: User, text: str, db: AsyncSession) -> str:
        from app.models.nutritionist_patient import NutritionistPatient
        from sqlalchemy import select as sa_select

        txt = text.strip().lower()
        data = user.state_data or {}
        token = data.get("invite_token", "")
        nutri_name = data.get("nutri_name", "nutricionista")

        user.conversation_state = "IDLE"
        user.state_data = None
        user.state_expires_at = None

        if not token:
            await db.commit()
            return "Ocorreu um erro ao processar o convite. Por favor, tente o link novamente."

        if txt in CONFIRM_WORDS:
            aceitar = True
        elif txt in DENY_WORDS:
            aceitar = False
        else:
            user.conversation_state = "INVITE_PENDING"
            user.state_data = data
            self._set_timed_state(user, "INVITE_PENDING")  # type: ignore[attr-defined]
            await db.commit()
            return "Não entendi. Responda *SIM* para aceitar ou *NÃO* para recusar."

        result = await db.execute(
            sa_select(NutritionistPatient).where(NutritionistPatient.invite_token == token)
        )
        link = result.scalar_one_or_none()

        if not link:
            logger.error(f"[INVITE] Token não encontrado ao processar resposta: {token!r}")
            await db.commit()
            return "Ocorreu um erro ao processar o convite. Por favor, tente o link novamente."

        if link.status != "pending":
            await db.commit()
            return "Este convite já foi processado anteriormente."

        if datetime.utcnow() > link.expires_at.replace(tzinfo=None):
            link.status = "expired"
            await db.commit()
            return "⌛ Este convite expirou. Peça à sua nutricionista um novo link."

        if aceitar:
            link.patient_id = user.id
            link.status = "active"
            link.consented_at = datetime.now(ZoneInfo("UTC"))
        else:
            link.status = "declined"

        await db.commit()
        logger.info(f"[INVITE] Token {token!r}: {'aceito' if aceitar else 'recusado'} por {user.channel_id}")

        if aceitar:
            return (
                f"✅ *Pronto!* {nutri_name} agora pode acompanhar sua alimentação.\n\n"
                "Você pode revogar esse acesso quando quiser digitando /privacidade.\n\n"
                "Continue usando o NutriBot normalmente — nada muda para você! 🥗"
            )
        else:
            return (
                f"❌ Convite de {nutri_name} recusado.\n\n"
                "Seus dados continuam 100% privados. "
                "Se mudar de ideia, peça à nutricionista um novo convite."
            )

    async def _iniciar_revogacao(
        self, user: User, name_hint: str | None, db: AsyncSession
    ) -> str:
        from app.models.nutritionist_patient import NutritionistPatient
        from app.models.user import User as _User
        from sqlalchemy import select as sa_select

        links_q = await db.execute(
            sa_select(NutritionistPatient).where(
                NutritionistPatient.patient_id == user.id,
                NutritionistPatient.status == "active",
            )
        )
        links = links_q.scalars().all()

        if not links:
            return (
                "Você não tem nenhuma nutricionista com acesso aos seus dados no momento.\n\n"
                "Use /privacidade para ver o resumo completo."
            )

        candidates = []
        for link in links:
            nutri_r = await db.execute(sa_select(_User).where(_User.id == link.nutritionist_id))
            nutri = nutri_r.scalar_one_or_none()
            nutri_name = nutri.first_name if nutri else link.patient_name or "Nutricionista"
            candidates.append((link, nutri_name))

        if name_hint:
            hint_low = name_hint.lower()
            matched = [(l, n) for l, n in candidates if hint_low in n.lower()]
            if len(matched) == 1:
                link, nutri_name = matched[0]
                user.conversation_state = "REVOKING"
                user.state_data = {"link_id": str(link.id), "nutri_name": nutri_name}
                self._set_timed_state(user, "REVOKING")  # type: ignore[attr-defined]
                await db.commit()
                return (
                    f"⚠️ Tem certeza que deseja revogar o acesso de *{nutri_name}*?\n\n"
                    "Ela não poderá mais ver seus registros.\n"
                    "Responda *SIM* para confirmar ou *NÃO* para cancelar."
                )
            elif len(matched) == 0:
                names = "\n".join(f"• {n}" for _, n in candidates)
                return (
                    f"Não encontrei nutricionista com esse nome.\n\nAcessos ativos:\n{names}\n\n"
                    "Responda com: *revogar [nome exato]*"
                )
            names = "\n".join(f"• {n}" for _, n in matched)
            return (
                f"Encontrei mais de uma nutricionista com esse nome:\n{names}\n\n"
                "Por favor, informe o nome completo: *revogar [nome completo]*"
            )

        if len(candidates) == 1:
            link, nutri_name = candidates[0]
            user.conversation_state = "REVOKING"
            user.state_data = {"link_id": str(link.id), "nutri_name": nutri_name}
            self._set_timed_state(user, "REVOKING")  # type: ignore[attr-defined]
            await db.commit()
            return (
                f"⚠️ Tem certeza que deseja revogar o acesso de *{nutri_name}*?\n\n"
                "Ela não poderá mais ver seus registros.\n"
                "Responda *SIM* para confirmar ou *NÃO* para cancelar."
            )

        names = "\n".join(f"• {n}" for _, n in candidates)
        return (
            f"Você tem {len(candidates)} nutricionistas com acesso:\n{names}\n\n"
            "Responda com: *revogar [nome da nutricionista]*"
        )

    async def _handle_revoking(self, user: User, text: str, db: AsyncSession) -> str:
        import uuid as _uuid
        from app.models.nutritionist_patient import NutritionistPatient
        from sqlalchemy import select as sa_select

        txt = text.strip().lower()
        data = user.state_data or {}
        nutri_name = data.get("nutri_name", "a nutricionista")
        link_id_str = data.get("link_id")

        def _reset():
            user.conversation_state = "IDLE"
            user.state_data = None

        if txt in CONFIRM_WORDS:
            aceitar = True
        elif txt in {"não", "nao", "n", "no", "cancelar", "cancela"}:
            aceitar = False
        else:
            user.conversation_state = "REVOKING"
            user.state_data = data
            self._set_timed_state(user, "REVOKING")  # type: ignore[attr-defined]
            await db.commit()
            return "Não entendi. Responda *SIM* para confirmar a revogação ou *NÃO* para cancelar."

        _reset()

        if not aceitar:
            await db.commit()
            return "Cancelado. O acesso de {} continua ativo.".format(nutri_name)

        if not link_id_str:
            await db.commit()
            return "Não consegui identificar o vínculo. Tente novamente com /privacidade."

        try:
            link_id = _uuid.UUID(link_id_str)
        except ValueError:
            await db.commit()
            return "Erro interno: ID de vínculo inválido. Use /privacidade e tente novamente."

        link_q = await db.execute(
            sa_select(NutritionistPatient).where(NutritionistPatient.id == link_id)
        )
        link = link_q.scalar_one_or_none()

        if not link or link.status != "active":
            await db.commit()
            return (
                f"O vínculo com {nutri_name} não está mais ativo "
                "(pode já ter sido revogado). Use /privacidade para verificar."
            )

        from datetime import datetime as _dt
        link.status = "revoked"
        link.revoked_at = _dt.now()
        await db.commit()

        return (
            f"✅ *Pronto!* Acesso de *{nutri_name}* revogado com sucesso.\n\n"
            "Ela não poderá mais ver seus dados no NutriBot.\n"
            "Se quiser restaurar o acesso no futuro, peça um novo convite.\n\n"
            "Seus dados continuam totalmente privados. 🔒"
        )
