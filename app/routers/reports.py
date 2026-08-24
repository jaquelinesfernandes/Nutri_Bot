"""Endpoints REST para relatórios nutricionais."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response as FastAPIResponse
from pydantic import BaseModel
from sqlalchemy import delete, select
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


def _resolve_period(period: str, created_at_date: date) -> tuple[date, date, str]:
    """Converte o slug de período em (start, end, period_type)."""
    today = date.today()
    if period in ("semana", "week", "7dias"):
        return today - timedelta(days=7), today, "weekly"
    if period in ("mes", "mês", "month", "30dias"):
        return today.replace(day=1), today, "monthly"
    if period in ("3meses", "trimestre", "90dias", "quarter"):
        m = today.month - 3
        y = today.year + (m - 1) // 12
        m = ((m - 1) % 12) + 1
        return today.replace(year=y, month=m, day=1), today, "quarterly"
    if period in ("total", "all"):
        return created_at_date, today, "custom"
    raise ValueError(period)


@router.post("/generate", status_code=201)
async def generate_report(
    body: GenerateReportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FastAPIResponse:
    """Gera um novo relatório sob demanda e retorna o PDF diretamente."""
    from app.config import settings
    from app.services.report import report_service

    if not current_user.can_access_reports and not settings.reports_open_beta:
        raise HTTPException(
            status_code=403,
            detail="Relatórios disponíveis após 7 dias de cadastro ou com plano Premium.",
        )

    try:
        start, end, period_type = _resolve_period(
            body.period.strip().lower(),
            current_user.created_at.date(),
        )
    except ValueError:
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
        # save=True → salva o WeeklyReport no DB (único registro criado)
        file_bytes, ext = await report_service.generate_report(
            user=current_user,
            start_date=start,
            end_date=end,
            period_type=period_type,
            db=db,
            save=True,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Erro ao gerar relatório. Tente novamente em instantes.",
        ) from exc

    media_type = "application/pdf" if ext == "pdf" else "text/html"
    filename = f"nutribot_relatorio_{start}_{period_type}.{ext}"
    # Retorna o arquivo diretamente — sem segunda requisição, sem duplicata
    return FastAPIResponse(
        content=file_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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
    # save=False: apenas re-renderiza o PDF sem criar novo registro no DB
    file_bytes, ext = await report_service.generate_report(
        user=current_user,
        start_date=report.week_start_date,
        end_date=report.period_end_date or (report.week_start_date + timedelta(days=7)),
        period_type=report.period_type or "weekly",
        db=db,
        save=False,
    )
    media_type = "application/pdf" if ext == "pdf" else "text/html"
    filename = f"nutribot_relatorio_{report.week_start_date}.{ext}"
    return FastAPIResponse(
        content=file_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("", status_code=200)
async def clear_reports(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Remove todos os relatórios do usuário logado."""
    result = await db.execute(
        delete(WeeklyReport).where(WeeklyReport.user_id == current_user.id)
    )
    await db.commit()
    deleted = result.rowcount
    return {"deleted": deleted, "message": f"{deleted} relatório(s) removido(s)."}
