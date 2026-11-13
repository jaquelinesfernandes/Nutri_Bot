<#
.SYNOPSIS
    Aplica migrations Alembic via docker exec psql (contorna bug asyncpg/psycopg2 no Windows).

.DESCRIPTION
    Gera SQL offline com alembic --sql e executa dentro do container Docker,
    evitando problemas de socket e encoding do asyncpg/psycopg2 no Windows.
#>

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$python = "$root\.venv\Scripts\python.exe"

Write-Host "`n[migrate] Verificando container PostgreSQL..." -ForegroundColor Yellow
$health = docker inspect --format='{{.State.Health.Status}}' nutribot_db 2>$null
if ($health -ne "healthy") {
    throw "Container nutribot_db nao esta healthy. Execute: docker compose up -d"
}

Write-Host "[migrate] Gerando SQL das migrations..." -ForegroundColor Yellow
$sql = & $python -m alembic upgrade head --sql 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Falha ao gerar SQL: $sql"
}

# Filtra apenas linhas SQL (remove linhas INFO do alembic)
$sqlLines = $sql | Where-Object { $_ -notmatch "^INFO" }
$sqlContent = $sqlLines -join "`n"

Write-Host "[migrate] Executando SQL no banco local..." -ForegroundColor Yellow
$sqlContent | docker exec -i nutribot_db psql -U nutribot -d nutribot 2>&1

if ($LASTEXITCODE -ne 0) {
    throw "Falha ao executar SQL no banco"
}

Write-Host "[migrate] Migrations aplicadas com sucesso!" -ForegroundColor Green
