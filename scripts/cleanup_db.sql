-- ============================================================
-- NutriBot — Script de limpeza do banco Neon (free tier)
-- Executar via: psql $DATABASE_URL -f scripts/cleanup_db.sql
-- ou colar no Neon SQL Editor (console.neon.tech)
--
-- SEGURO: não apaga usuários, refeições recentes nem dados B2B.
-- Cada bloco é independente — execute por partes se quiser.
-- ============================================================

-- Antes de limpar, veja o tamanho de cada tabela:
SELECT
    relname                                           AS tabela,
    pg_size_pretty(pg_total_relation_size(relid))     AS tamanho_total,
    pg_size_pretty(pg_relation_size(relid))           AS dados,
    pg_size_pretty(pg_total_relation_size(relid)
                 - pg_relation_size(relid))           AS indices,
    n_live_tup                                        AS linhas_vivas,
    n_dead_tup                                        AS linhas_mortas
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(relid) DESC;

-- ============================================================
-- BLOCO 1 — audit_logs
-- Mantém últimos 90 dias. Logs mais velhos não têm valor operacional.
-- Impacto esperado: alto (tabela cresce rápido com ações do painel admin).
-- ============================================================
BEGIN;

DELETE FROM audit_logs
WHERE created_at < NOW() - INTERVAL '90 days';

-- Confirme quantas linhas foram apagadas antes de fazer COMMIT:
-- SELECT count(*) FROM audit_logs WHERE created_at < NOW() - INTERVAL '90 days';

COMMIT;

-- ============================================================
-- BLOCO 2 — water_logs
-- Mantém últimos 90 dias. Dados de hidratação mais velhos raramente
-- são consultados e o dashboard só exibe os últimos 7 dias.
-- ============================================================
BEGIN;

DELETE FROM water_logs
WHERE logged_at < NOW() - INTERVAL '90 days';

COMMIT;

-- ============================================================
-- BLOCO 3 — meal_logs + food_items de usuários deletados
-- Usuários com deleted_at preenchido tiveram dados anonimizados
-- (LGPD). Refeições órfãs deles podem ser removidas com segurança.
-- food_items têm CASCADE DELETE, então são removidos automaticamente.
-- ============================================================
BEGIN;

DELETE FROM meal_logs
WHERE user_id IN (
    SELECT id FROM users WHERE deleted_at IS NOT NULL
);

COMMIT;

-- ============================================================
-- BLOCO 4 — weekly_reports antigos
-- Mantém os últimos 6 meses por usuário. PDFs mais velhos
-- raramente são baixados e o texto comprimido ocupa bastante.
-- ============================================================
BEGIN;

DELETE FROM weekly_reports
WHERE created_at < NOW() - INTERVAL '180 days';

COMMIT;

-- ============================================================
-- BLOCO 5 — meal_logs não confirmados e muito antigos
-- Registros com confirmed=false há mais de 30 dias são pendências
-- que nunca foram aprovadas pelo usuário — podem ser descartadas.
-- ============================================================
BEGIN;

DELETE FROM meal_logs
WHERE confirmed = false
  AND logged_at < NOW() - INTERVAL '30 days';

COMMIT;

-- ============================================================
-- BLOCO 6 — VACUUM FULL (recupera espaço físico no disco)
-- ATENÇÃO: bloqueia escrita nas tabelas durante a execução.
-- Execute em horário de baixo uso (madrugada BRT).
-- No Neon free tier, o espaço só é devolvido após VACUUM.
-- ============================================================

VACUUM FULL ANALYZE audit_logs;
VACUUM FULL ANALYZE water_logs;
VACUUM FULL ANALYZE meal_logs;
VACUUM FULL ANALYZE food_items;
VACUUM FULL ANALYZE weekly_reports;

-- ============================================================
-- VERIFICAÇÃO FINAL — rode após o VACUUM para confirmar ganho
-- ============================================================
SELECT
    relname                                           AS tabela,
    pg_size_pretty(pg_total_relation_size(relid))     AS tamanho_total,
    n_live_tup                                        AS linhas_vivas
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(relid) DESC;
