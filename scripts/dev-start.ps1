<#
.SYNOPSIS
    Inicia o ambiente de desenvolvimento local do NutriBot.

.DESCRIPTION
    Sobe todos os serviços via Docker Compose:
      - PostgreSQL 16       → localhost:5432
      - pgAdmin             → http://localhost:5050  (aurelianojsn@gmail.com / admin)
      - FastAPI (app)       → http://localhost:8000  (live reload via volume)

    Migrations são aplicadas automaticamente pelo container app na inicialização.

.PARAMETER Build
    Força o rebuild da imagem do app (necessário após mudanças em requirements.txt)

.PARAMETER Down
    Para e remove os containers (mantém os volumes/dados)

.PARAMETER Logs
    Exibe os logs em tempo real após subir os serviços
#>

param(
    [switch]$Build,
    [switch]$Down,
    [switch]$Logs
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

if ($Down) {
    Write-Host "`n[stop] Parando containers..." -ForegroundColor Yellow
    docker compose down
    Write-Host "[stop] Containers parados. Volumes preservados." -ForegroundColor Green
    return
}

Write-Host "`n=== NutriBot Dev Environment ===" -ForegroundColor Cyan

if ($Build) {
    Write-Host "`n[build] Rebuilding imagem do app..." -ForegroundColor Yellow
    docker compose build app
}

Write-Host "`n[up] Subindo servicos..." -ForegroundColor Yellow
docker compose up -d

Write-Host "`n  Aguardando app ficar pronto..." -ForegroundColor Gray
$tries = 0
do {
    Start-Sleep -Seconds 3
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -ErrorAction SilentlyContinue
        $health = $resp.Content | ConvertFrom-Json
        if ($health.db -eq "connected") { break }
    } catch {}
    $tries++
} while ($tries -lt 20)

if ($health.db -ne "connected") {
    Write-Host "`n[aviso] App pode ainda estar inicializando. Verifique: docker logs nutribot_app" -ForegroundColor Yellow
} else {
    Write-Host "`n  Status: $($health.status) | DB: $($health.db)" -ForegroundColor Green
}

Write-Host "`n=== Ambiente pronto ===" -ForegroundColor Cyan
Write-Host "  API:       http://localhost:8000" -ForegroundColor White
Write-Host "  Docs:      http://localhost:8000/docs" -ForegroundColor White
Write-Host "  Dashboard: http://localhost:8000/login" -ForegroundColor White
Write-Host "  Admin:     http://localhost:8000/admin" -ForegroundColor White
Write-Host "  pgAdmin:   http://localhost:5050  (aurelianojsn@gmail.com / admin)" -ForegroundColor White

Write-Host "`n  Para Telegram local (polling), abra outra janela:" -ForegroundColor Gray
Write-Host "    .venv\Scripts\python.exe scripts\run_bot_polling.py" -ForegroundColor Gray
Write-Host "`n  Para parar: .\scripts\dev-start.ps1 -Down" -ForegroundColor Gray
Write-Host "  Para logs:  docker logs -f nutribot_app`n" -ForegroundColor Gray

if ($Logs) {
    docker compose logs -f app
}
