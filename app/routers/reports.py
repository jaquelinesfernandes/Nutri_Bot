"""Endpoints REST para relatórios nutricionais."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response as FastAPIResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User
from app.models.weekly_report import WeeklyReport
from app.utils.jwt import get_current_user

router = APIRouter(prefix="/api/reports", tags=["reports"])


class ReportSummary(BaseModel):
    id: uuid.UUID
    week_start_date: str
    period_type: str
    generated_at: str
    has_pdf: bool

    model_config = {"from_attributes": True}


class GenerateReportRequest(BaseModel):
    period: str  # "semana" | "mes" | "3meses" | "total"


class GenerateReportResponse(BaseModel):
    report_id: uuid.UUID
    period_type: str
    start_date: str
    end_date: str
    download_url: str


@router.get("", response_model=list[ReportSummary])
async def list_reports(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ReportSummary]:
    result = await db.execute(
        select(WeeklyReport)
        .where(WeeklyReport.user_id == current_user.id)
        .order_by(WeeklyReport.week_start_date.desc())
        .limit(20)
    )
    reports = result.scalars().all()
    return [
        ReportSummary(
            id=r.id,
            week_start_date=r.week_start_date.isoformat(),
            period_type=r.period_type,
            generated_at=r.generated_at.isoformat(),
            has_pdf=bool(r.pdf_storage_path),
        )
        for r in reports
    ]


@router.post("/generate", response_model=GenerateReportResponse, status_code=201)
async def generate_report(
    body: GenerateReportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GenerateReportResponse:
    """Gera um novo relatório sob demanda a partir do painel web."""
    from app.config import settings
    from app.services.report import report_service

    # Verifica acesso (7 dias de cadastro ou premium ou open_beta)
    if not current_user.can_access_reports and not settings.reports_open_beta:
        raise HTTPException(
            status_code=403,
            detail="Relatórios disponíveis após 7 dias de cadastro ou com plano Premium.",
        )

    today = date.today()
    period = body.period.strip().lower()

    if period in ("semana", "week", "7dias"):
        start = today - timedelta(days=7)
        end = today
        period_type = "weekly"
    elif period in ("mes", "mês", "month", "30dias"):
        start = today.replace(day=1)
        end = today
        period_type = "monthly"
    elif period in ("3meses", "trimestre", "90dias", "quarter"):
        m = today.month - 3
        y = today.year + (m - 1) // 12
        m = ((m - 1) % 12) + 1
        start = today.replace(year=y, month=m, day=1)
        end = today
        period_type = "quarterly"
    elif period in ("total", "all"):
        # Do início do cadastro até hoje
        start = current_user.created_at.date()
        end = today
        period_type = "custom"
    else:
        raise HTTPException(
            status_code=422,
            detail="Período inválido. Use: semana, mes, 3meses ou total.",
        )

    if start >= end:
        raise HTTPException(
            status_code=422,
            detail="Período sem dados suficientes. Comece a registrar refeições!",
        )

    try:
        _bytes, ext = await report_service.generate_report(
            user=current_user,
            start_date=start,
            end_date=end,
            period_type=period_type,
            db=db,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Erro ao gerar relatório. Tente novamente em instantes.",
        ) from exc

    # Recupera o WeeklyReport recém-criado para retornar o ID
    result = await db.execute(
        select(WeeklyReport)
        .where(
            WeeklyReport.user_id == current_user.id,
            WeeklyReport.week_start_date == start,
        )
        .order_by(WeeklyReport.generated_at.desc())
        .limit(1)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=500, detail="Relatório gerado mas não encontrado.")

    return GenerateReportResponse(
        report_id=report.id,
        period_type=period_type,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        download_url=f"/api/reports/{report.id}/download",
    )


@router.get("/{report_id}/download")
async def download_report(
    report_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FastAPIResponse:
    result = await db.execute(
        select(WeeklyReport).where(
            WeeklyReport.id == report_id,
            WeeklyReport.user_id == current_user.id,
        )
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Relatório não encontrado")

    from app.services.report import report_service
    file_bytes, ext = await report_service.generate_report(
        user=current_user,
        start_date=report.week_start_date,
        end_date=report.period_end_date or (report.week_start_date + timedelta(days=7)),
        period_type=report.period_type or "weekly",
        db=db,
    )
    media_type = "application/pdf" if ext == "pdf" else "text/html"
    filename = f"nutribot_relatorio_{report.week_start_date}.{ext}"
    return FastAPIResponse(
        content=file_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
