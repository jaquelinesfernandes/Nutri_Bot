"""Diagnóstico de storage do Neon — apenas SELECTs (funciona em read-only)."""
import asyncio
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import asyncpg

raw_dsn = (
    os.environ.get("DATABASE_URL", "")
    .replace("postgresql+asyncpg://", "postgresql://")
    .replace("postgres://", "postgresql://")
)
if not raw_dsn:
    print("DATABASE_URL não definida"); sys.exit(1)


async def main():
    print("Conectando...")
    conn = await asyncpg.connect(raw_dsn)
    print("OK\n")

    # Tamanho total do banco
    db_bytes = await conn.fetchval("SELECT pg_database_size(current_database())")
    db_pretty = await conn.fetchval("SELECT pg_size_pretty(pg_database_size(current_database()))")
    limite = 536_870_912  # 512 MB
    pct = db_bytes / limite * 100
    print("=== TAMANHO DO BANCO ===")
    print(f"  Total:   {db_pretty}  ({db_bytes:,} bytes)")
    print(f"  Limite:  512 MB free tier")
    print(f"  Uso:     {pct:.1f}%")
    print()

    # Por tabela
    print("=== POR TABELA ===")
    rows = await conn.fetch("""
        SELECT relname,
               pg_size_pretty(pg_total_relation_size(relid)) AS total,
               pg_size_pretty(pg_relation_size(relid))       AS dados,
               pg_size_pretty(pg_indexes_size(relid))        AS indices,
               n_live_tup, n_dead_tup
        FROM pg_stat_user_tables
        ORDER BY pg_total_relation_size(relid) DESC
    """)
    for r in rows:
        print(f"  {r['relname']:30s}  {r['total']:>9}  "
              f"dados={r['dados']:>9}  idx={r['indices']:>9}  "
              f"vivas={r['n_live_tup']:>6}  mortas={r['n_dead_tup']:>6}")
    print()

    # Estimativa de limpeza (só COUNT — read-only safe)
    print("=== LINHAS LIMPÁVEIS ===")
    checks = [
        ("audit_logs >90d",
         "SELECT count(*) FROM audit_logs WHERE created_at < NOW() - INTERVAL '90 days'"),
        ("water_logs >90d",
         "SELECT count(*) FROM water_logs WHERE logged_at < NOW() - INTERVAL '90 days'"),
        ("meal_logs (users deletados)",
         "SELECT count(*) FROM meal_logs WHERE user_id IN (SELECT id FROM users WHERE deleted_at IS NOT NULL)"),
        ("weekly_reports >6 meses",
         "SELECT count(*) FROM weekly_reports WHERE created_at < NOW() - INTERVAL '180 days'"),
        ("meal_logs nao confirmados >30d",
         "SELECT count(*) FROM meal_logs WHERE confirmed = false AND logged_at < NOW() - INTERVAL '30 days'"),
    ]
    for label, sql in checks:
        n = await conn.fetchval(sql)
        print(f"  {label:35s}  {n:>6} linhas")

    await conn.close()
    print("\nDiagnóstico concluído.")


asyncio.run(main())
