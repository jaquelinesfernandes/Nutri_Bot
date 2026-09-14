"""
Diagnóstico do fluxo de convite nutricionista.

Uso:
    python scripts/diagnose_invite.py
    python scripts/diagnose_invite.py --fix-token SEU_TOKEN   # aceita manualmente
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix-token", metavar="TOKEN", help="Aceita manualmente um convite pelo token")
    parser.add_argument("--patient-id", metavar="UUID", help="UUID do paciente (obrigatório com --fix-token)")
    args = parser.parse_args()

    from sqlalchemy import select, text
    from app.db.session import AsyncSessionLocal
    from app.models.nutritionist_patient import NutritionistPatient
    from app.models.user import User

    async with AsyncSessionLocal() as db:

        # ── 1. Lista todos os vínculos ─────────────────────────────────────────
        result = await db.execute(
            select(NutritionistPatient).order_by(NutritionistPatient.invited_at.desc()).limit(20)
        )
        links = result.scalars().all()

        print("\n" + "="*65)
        print("VÍNCULOS NUTRICIONISTA ↔ PACIENTE (últimos 20)")
        print("="*65)

        if not links:
            print("⚠️  Nenhum vínculo encontrado no banco.")
        else:
            for lk in links:
                # Busca nome da nutricionista
                nr = await db.execute(select(User).where(User.id == lk.nutritionist_id))
                nutri = nr.scalar_one_or_none()
                nutri_name = nutri.first_name if nutri else "?"

                # Busca nome do paciente (se já vinculado)
                patient_name = lk.patient_name or "—"
                if lk.patient_id:
                    pr = await db.execute(select(User).where(User.id == lk.patient_id))
                    pat = pr.scalar_one_or_none()
                    if pat:
                        patient_name = pat.first_name or patient_name

                expired_flag = ""
                if lk.status == "pending":
                    if datetime.utcnow() > lk.expires_at.replace(tzinfo=None):
                        expired_flag = " ⏰ EXPIRADO"
                    else:
                        diff = (lk.expires_at.replace(tzinfo=None) - datetime.utcnow()).days
                        expired_flag = f" (expira em {diff}d)"

                print(
                    f"  [{lk.status.upper():10}]{expired_flag}\n"
                    f"   Nutricionista : {nutri_name} (id={lk.nutritionist_id})\n"
                    f"   Paciente nome : {patient_name}\n"
                    f"   patient_id    : {lk.patient_id or '❌ NULL — não vinculado'}\n"
                    f"   Token         : {lk.invite_token[:16]}...\n"
                    f"   Convidado em  : {lk.invited_at}\n"
                )

        # ── 2. Mostra usuários com canal Telegram ──────────────────────────────
        print("="*65)
        print("USUÁRIOS TELEGRAM (onboarding completo)")
        print("="*65)
        ur = await db.execute(
            select(User)
            .where(User.channel_type == "telegram", User.onboarding_complete.is_(True), User.deleted_at.is_(None))
            .order_by(User.created_at.desc())
            .limit(15)
        )
        users = ur.scalars().all()
        for u in users:
            print(f"  {u.first_name:20} | {u.channel_id:20} | plan={u.plan:14} | id={u.id}")

        # ── 3. Aceite manual (--fix-token) ────────────────────────────────────
        if args.fix_token:
            if not args.patient_id:
                print("\n❌ --patient-id é obrigatório para --fix-token")
                print("   Copie o id do paciente da lista acima.")
                return

            import uuid as _uuid
            from zoneinfo import ZoneInfo

            r = await db.execute(
                select(NutritionistPatient).where(
                    NutritionistPatient.invite_token == args.fix_token
                )
            )
            lk = r.scalar_one_or_none()

            if not lk:
                print(f"\n❌ Token não encontrado: {args.fix_token}")
                return

            print(f"\n🔧 Forçando aceite do convite {args.fix_token[:16]}...")
            print(f"   Status atual: {lk.status} | patient_id: {lk.patient_id}")

            lk.patient_id = _uuid.UUID(args.patient_id)
            lk.status = "active"
            lk.consented_at = datetime.now(ZoneInfo("UTC"))
            await db.commit()

            print(f"   ✅ Vínculo criado! patient_id={lk.patient_id}")
            print("   Recarregue o painel da nutricionista.")


if __name__ == "__main__":
    asyncio.run(main())
