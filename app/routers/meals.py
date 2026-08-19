"""Endpoints REST para histórico de refeições."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.models.meal_log import MealLog
from app.models.user import User
from app.schemas.meal import DailyBalance, MealLogRead
from app.utils.jwt import get_current_user

router = APIRouter(prefix="/api/meals", tags=["meals"])


async def _meals_for_date(
    user: User, target_date: date, db: AsyncSession
) -> list[MealLog]:
    """Retorna MealLogs confirmados do usuário para uma data (no fuso do usuário)."""
    tz = ZoneInfo(user.timezone or "America/Sao_Paulo")
    day_start = datetime(target_date.year, target_date.month, target_date.day, 0, 0, tzinfo=tz)
    day_end = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59, tzinfo=tz)

    result = await db.execute(
        select(MealLog)
        .options(selectinload(MealLog.food_items))
        .where(
            MealLog.user_id == user.id,
            MealLog.confirmed == True,  # noqa: E712
            MealLog.logged_at >= day_start,
            MealLog.logged_at <= day_end,
        )
        .order_by(MealLog.logged_at)
    )
    return list(result.scalars().all())


def _build_daily_balance(
    target_date: date, meals: list[MealLog], user: User
) -> DailyBalance:
    total_kcal = sum(m.total_calories_kcal for m in meals)
    total_prot = sum(m.total_protein_g for m in meals)
    total_carb = sum(m.total_carb_g for m in meals)
    total_fat = sum(m.total_fat_g for m in meals)
    goal = user.daily_calorie_goal
    return DailyBalance(
        date=target_date.isoformat(),
        total_calories_kcal=total_kcal,
        total_protein_g=total_prot,
        total_carb_g=total_carb,
        total_fat_g=total_fat,
        goal_calories=goal,
        remaining_calories=(goal - total_kcal) if goal else None,
        meals=[MealLogRead.model_validate(m) for m in meals],
    )


@router.get("/today", response_model=DailyBalance)
async def get_today(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DailyBalance:
    tz = ZoneInfo(current_user.timezone or "America/Sao_Paulo")
    today = datetime.now(tz).date()
    meals = await _meals_for_date(current_user, today, db)
    return _build_daily_balance(today, meals, current_user)


@router.get("", response_model=DailyBalance)
async def get_meals_by_date(
    date_str: str = Query(default=None, alias="date", description="YYYY-MM-DD"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DailyBalance:
    tz = ZoneInfo(current_user.timezone or "America/Sao_Paulo")
    if date_str:
        try:
            target_date = date.fromisoformat(date_str)
        except ValueError:
            target_date = datetime.now(tz).date()
    else:
        target_date = datetime.now(tz).date()

    meals = await _meals_for_date(current_user, target_date, db)
    return _build_daily_balance(target_date, meals, current_user)


@router.get("/week", response_model=list[DailyBalance])
async def get_week(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DailyBalance]:
    """Retorna os últimos 7 dias para o gráfico semanal."""
    from datetime import timedelta
    tz = ZoneInfo(current_user.timezone or "America/Sao_Paulo")
    today = datetime.now(tz).date()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    result = []
    for d in days:
        meals = await _meals_for_date(current_user, d, db)
        result.append(_build_daily_balance(d, meals, current_user))
    return result
