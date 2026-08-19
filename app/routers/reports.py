"""Endpoints REST para relatórios nutricionais."""
from __future__ import annotations

import json
import uuid

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

    # Gera o relatório sob demanda usando o ReportService
    from app.services.report import report_service
    file_bytes, ext = await report_service.generate_for_user(
        user=current_user,
        week_start=report.week_start_date,
        db=db,
    )
    media_type = "application/pdf" if ext == "pdf" else "text/html"
    filename = f"nutribot_relatorio_{report.week_start_date}.{ext}"
    return FastAPIResponse(
        content=file_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
