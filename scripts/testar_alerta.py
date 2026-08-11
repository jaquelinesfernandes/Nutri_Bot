"""
Dispara um alerta de refeição imediatamente para testar o envio via Telegram.
Não precisa de webhook nem ngrok — envia diretamente pela API do Telegram.

Uso:
    python scripts/testar_alerta.py
    python scripts/testar_alerta.py --tipo almoco
    python scripts/testar_alerta.py --channel-id tg:123456789
    python scripts/testar_alerta.py --listar
"""

import asyncio
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Força UTF-8 no terminal Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()


def _log(msg: str):
    from datetime import datetime
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


async def listar_usuarios():
    from sqlalchemy import select
    from app.db.session import AsyncSessionLocal
    from app.models.user import User

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.deleted_at.is_(None)).limit(20)
        )
        users = result.scalars().all()
        if not users:
            print("Nenhum usuário no banco.")
            return
        print(f"\n{'channel_id':25}  {'nome':15}  {'alertas':8}  {'onboarding'}")
        print("-" * 70)
        for u in users:
            ok = "SIM" if u.onboarding_complete else "NAO"
            alerta = "ON" if u.alerts_enabled else "OFF"
            print(f"{u.channel_id:25}  {(u.first_name or '-'):15}  {alerta:8}  {ok}")


async def testar_alerta(tipo: str, channel_id: str | None):
    from sqlalchemy import select
    from app.db.session import AsyncSessionLocal
    from app.models.user import User
    from app.services.notification import notification_service
    from app.services.nutrition import nutrition_service

    nutrition_service.load_data()

    _MENSAGENS = {
        "cafe":   ("breakfast", "Bom dia, {name}! ☀️ Você já tomou café da manhã?\nMe conta o que comeu para eu registrar suas calorias! 🥣"),
        "almoco": ("lunch",    "Ei, {name}! 🍽️ Já passaram das 12h — você já almoçou?\nMe conta o que comeu! 🥗"),
        "jantar": ("dinner",   "Boa noite, {name}! 🌙 Hora de registrar o jantar.\nO que você comeu esta noite? 🍲"),
    }

    meal_type, template = _MENSAGENS[tipo]
    _log(f"Tipo de alerta: {tipo} ({meal_type})")

    async with AsyncSessionLocal() as db:
        if channel_id:
            result = await db.execute(select(User).where(User.channel_id == channel_id))
        else:
            result = await db.execute(
                select(User).where(
                    User.onboarding_complete.is_(True),
                    User.deleted_at.is_(None),
                ).limit(1)
            )

        user = result.scalar_one_or_none()

        if not user:
            _log("Usuário não encontrado. Use --listar para ver os disponíveis.")
            _log("Se não há usuários, inicie o bot e envie /start primeiro.")
            return

        _log(f"Usuário: {user.first_name or '?'} | {user.channel_id} | alertas={'ON' if user.alerts_enabled else 'OFF'}")

        name = user.first_name or "você"
        mensagem = template.format(name=name)
        _log(f"Mensagem: {mensagem[:60]}...")

        sent = await notification_service.send_text(user, mensagem)

        if sent:
            _log("[OK] Alerta enviado com sucesso! Verifique o Telegram.")
        else:
            _log("[FALHA] Envio falhou.")
            _log("  Verifique: TELEGRAM_BOT_TOKEN no .env e se o usuário já iniciou o bot.")


async def main():
    parser = argparse.ArgumentParser(description="Testa envio de alerta de refeição via Telegram")
    parser.add_argument("--tipo", choices=["cafe", "almoco", "jantar"], default="almoco",
                        help="Tipo de refeição (padrão: almoco)")
    parser.add_argument("--channel-id", help="Ex: tg:123456789 (padrão: primeiro usuário do banco)")
    parser.add_argument("--listar", action="store_true", help="Lista usuários no banco")
    args = parser.parse_args()

    if args.listar:
        await listar_usuarios()
    else:
        await testar_alerta(args.tipo, args.channel_id)


if __name__ == "__main__":
    asyncio.run(main())
