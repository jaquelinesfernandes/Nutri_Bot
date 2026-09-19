"""
Limpeza de emergência do banco Neon (storage cheio).
Uso: python scripts/cleanup_db.py

Requer DATABASE_URL no .env ou variável de ambiente.
"""
import asyncio
import os
import sys

# Carrega .env se existir
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    print("ERRO: DATABASE_URL não definida.")
    sys.exit(1)

# Converte para asyncpg se necessário
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)

import asyncpg

# Extrai DSN puro (sem +asyncpg) para asyncpg
raw_dsn = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


async def run(conn, sql: str, label: str):
    try:
        result = await conn.execute(sql)
        print(f"  ✓ {label} — {result}")
    except Exception as e:
        print(f"  ✗ {label} — ERRO: {e}")


async def count(conn, table: str, where: str = "") -> int:
    sql = f"SELECT count(*) FROM {table}" + (f" WHERE {where}" if where else "")
    return await conn.fetchval(sql)


async def table_size(conn, table: str) -> str:
    return await conn.fetchval(
        "SELECT pg_size_pretty(pg_total_relation_size($1::regclass))", table
    )


async def main():
    print(f"\nConectando ao banco...")
    try:
        conn = await asyncpg.connect(raw_dsn)
    except Exception as e:
        print(f"ERRO ao conectar: {e}")
        sys.exit(1)
    print("Conectado.\n")

    # ── Diagnóstico inicial ───────────────────────────────────────────────────
    print("=" * 60)
    print("DIAGNÓSTICO — tamanho atual das tabelas")
    print("=" * 60)
    rows = await conn.fetch("""
        SELECT relname AS tabela,
               pg_size_pretty(pg_total_relation_size(relid)) AS total,
               n_live_tup AS linhas
        FROM pg_stat_user_tables
        ORDER BY pg_total_relation_size(relid) DESC
    """)
    for r in rows:
        print(f"  {r['tabela']:30s}  {r['total']:>10s}  ({r['linhas']} linhas)")

    # ── Estimativas de limpeza ────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("ESTIMATIVA — linhas que serão removidas")
    print("=" * 60)

    n1 = await count(conn, "audit_logs", "created_at < NOW() - INTERVAL '90 days'")
    n2 = await count(conn, "water_logs", "logged_at < NOW() - INTERVAL '90 days'")
    n3 = await count(conn, "meal_logs",
                     "user_id IN (SELECT id FROM users WHERE deleted_at IS NOT NULL)")
    n4 = await count(conn, "weekly_reports", "created_at < NOW() - INTERVAL '180 days'")
    n5 = await count(conn, "meal_logs",
                     "confirmed = false AND logged_at < NOW() - INTERVAL '30 days'")

    print(f"  audit_logs (>90d):              {n1:>6}")
    print(f"  water_logs (>90d):              {n2:>6}")
    print(f"  meal_logs (usuários deletados): {n3:>6}")
    print(f"  weekly_reports (>6 meses):      {n4:>6}")
    print(f"  meal_logs não confirmados >30d: {n5:>6}")
    total = n1 + n2 + n3 + n4 + n5
    print(f"\n  TOTAL estimado para remoção:    {total:>6} linhas")

    if total == 0:
        print("\nNada para limpar. Verifique outras causas do storage cheio.")
        await conn.close()
        return

    print("\nPressione ENTER para prosseguir com a limpeza, ou Ctrl+C para cancelar.")
    try:
        input()
    except KeyboardInterrupt:
        print("\nCancelado.")
        await conn.close()
        return

    # ── Limpeza ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("EXECUTANDO LIMPEZA")
    print("=" * 60)

    await run(conn,
        "DELETE FROM audit_logs WHERE created_at < NOW() - INTERVAL '90 days'",
        f"audit_logs >90d ({n1} linhas)")

    await run(conn,
        "DELETE FROM water_logs WHERE logged_at < NOW() - INTERVAL '90 days'",
        f"water_logs >90d ({n2} linhas)")

    await run(conn,
        "DELETE FROM meal_logs WHERE user_id IN (SELECT id FROM users WHERE deleted_at IS NOT NULL)",
        f"meal_logs de usuários deletados ({n3} linhas)")

    await run(conn,
        "DELETE FROM weekly_reports WHERE created_at < NOW() - INTERVAL '180 days'",
        f"weekly_reports >6 meses ({n4} linhas)")

    await run(conn,
        "DELETE FROM meal_logs WHERE confirmed = false AND logged_at < NOW() - INTERVAL '30 days'",
        f"meal_logs não confirmados >30d ({n5} linhas)")

    # ── VACUUM ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("VACUUM ANALYZE (devolve espaço ao disco)")
    print("=" * 60)
    # asyncpg exige autocommit para VACUUM
    for table in ["audit_logs", "water_logs", "meal_logs", "food_items", "weekly_reports"]:
        try:
            await conn.execute(f"VACUUM ANALYZE {table}")
            size = await table_size(conn, table)
            print(f"  ✓ VACUUM {table:30s} → {size}")
        except Exception as e:
            print(f"  ✗ VACUUM {table} — {e}")

    # ── Resultado final ───────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("RESULTADO FINAL — tamanho das tabelas após limpeza")
    print("=" * 60)
    rows = await conn.fetch("""
        SELECT relname AS tabela,
               pg_size_pretty(pg_total_relation_size(relid)) AS total,
               n_live_tup AS linhas
        FROM pg_stat_user_tables
        ORDER BY pg_total_relation_size(relid) DESC
    """)
    for r in rows:
        print(f"  {r['tabela']:30s}  {r['total']:>10s}  ({r['linhas']} linhas)")

    print("\nLimpeza concluída. Verifique o storage no Neon Console.")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
