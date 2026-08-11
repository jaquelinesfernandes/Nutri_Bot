"""
Script de teste: gera e envia relatório semanal para um usuário real do banco.
Uso:
    python scripts/testar_relatorio.py
    python scripts/testar_relatorio.py --channel-id tg:123456789
"""

import asyncio
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

# Garante que o root do projeto está no path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models.user import User
from app.models.meal_log import MealLog
from app.services.report import report_service
from app.services.notification import notification_service
from app.services.nutrition import nutrition_service


def _log(msg: str):
    from datetime import datetime
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


async def listar_usuarios():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.deleted_at.is_(None)).limit(20)
        )
        users = result.scalars().all()

        if not users:
            print("Nenhum usuário encontrado no banco.")
            return

        print(f"\n{'ID':36}  {'channel_id':25}  {'nome':15}  {'plano':10}  {'onboarding'}")
        print("-" * 110)
        for u in users:
            ok = "SIM" if u.onboarding_complete else "NAO"
            print(f"{u.id}  {u.channel_id:25}  {(u.first_name or '-'):15}  {u.plan:10}  {ok}")


async def testar_relatorio(channel_id: str | None = None):
    nutrition_service.load_data()

    async with AsyncSessionLocal() as db:
        # Buscar usuário
        if channel_id:
            result = await db.execute(
                select(User).where(User.channel_id == channel_id)
            )
        else:
            result = await db.execute(
                select(User)
                .where(User.deleted_at.is_(None), User.onboarding_complete.is_(True))
                .limit(1)
            )

        user = result.scalar_one_or_none()

        if not user:
            _log(f"Usuário não encontrado: {channel_id or 'primeiro disponível'}")
            return

        _log(f"Usuário: {user.first_name or '?'} | {user.channel_id} | plano={user.plan}")

        # Semana: últimos 7 dias
        today = date.today()
        week_start = today - timedelta(days=6)

        # Mostrar refeições do período
        result_logs = await db.execute(
            select(MealLog).where(
                MealLog.user_id == user.id,
                MealLog.confirmed.is_(True),
            ).order_by(MealLog.logged_at.desc()).limit(10)
        )
        logs = result_logs.scalars().all()
        _log(f"Refeições confirmadas no banco: {len(logs)}")
        for log in logs:
            _log(f"  • {log.meal_type} | {log.logged_at.strftime('%d/%m %H:%M')} | {log.total_calories_kcal:.0f} kcal")

        # Gerar relatório
        _log(f"Gerando relatório da semana {week_start.strftime('%d/%m')} a {today.strftime('%d/%m/%Y')}...")
        try:
            pdf_bytes, ext = await report_service.generate_weekly_pdf(user, week_start, db)
            _log(f"Relatório gerado: {len(pdf_bytes):,} bytes ({ext.upper()})")
        except Exception as e:
            _log(f"ERRO ao gerar relatório: {e}")
            import traceback; traceback.print_exc()
            return

        # Salvar cópia local
        output_path = Path(f"relatorio_teste_{today.strftime('%Y-%m-%d')}.{ext}")
        output_path.write_bytes(pdf_bytes)
        _log(f"Cópia salva localmente: {output_path.resolve()}")

        # Enviar via Telegram
        _log(f"Enviando para {user.channel_id}...")
        filename = f"nutribot_relatorio_{week_start.strftime('%Y-%m-%d')}.{ext}"
        caption = (
            f"📊 *Relatório semanal de teste — {user.first_name or 'Usuário'}!*\n"
            f"Semana: {week_start.strftime('%d/%m')} a {today.strftime('%d/%m/%Y')}"
        )

        sent = await notification_service.send_document(user, pdf_bytes, filename, caption)
        if sent:
            _log("[OK] Relatorio enviado com sucesso!")
        else:
            _log("[FALHA] Envio falhou -- verifique o TELEGRAM_BOT_TOKEN e se o usuario iniciou o bot.")


async def main():
    parser = argparse.ArgumentParser(description="Testa envio de relatório semanal NutriBot")
    parser.add_argument("--channel-id", help="Ex: tg:123456789 (padrão: primeiro usuário do banco)")
    parser.add_argument("--listar", action="store_true", help="Lista todos os usuários no banco")
    args = parser.parse_args()

    if args.listar:
        await listar_usuarios()
    else:
        await testar_relatorio(args.channel_id)


if __name__ == "__main__":
    asyncio.run(main())
