"""Endpoints REST para histórico de refeições."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.models.food_item import FoodItem
from app.models.meal_log import MealLog
from app.models.user import User
from app.schemas.meal import DailyBalance, MealLogCreate, MealLogRead
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
    tz = ZoneInfo(current_user.timezone or "America/Sao_Paulo")
    today = datetime.now(tz).date()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    result = []
    for d in days:
        meals = await _meals_for_date(current_user, d, db)
        result.append(_build_daily_balance(d, meals, current_user))
    return result


@router.post("", response_model=MealLogRead, status_code=201)
async def create_meal(
    body: MealLogCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MealLogRead:
    """Cria um registro de refeição manual via painel web.

    Usa o mesmo pipeline de IA do bot: descrição em linguagem natural →
    Claude extrai alimentos → lookup TACO/USDA → salva com logged_at correto.
    """
    from app.services.ai_service import ai_service
    from app.services.conversation import _MEAL_DEFAULT_HOURS
    from app.services.nutrition import nutrition_service
    from app.utils.crypto import encrypt

    tz = ZoneInfo(current_user.timezone or "America/Sao_Paulo")
    today = datetime.now(tz).date()

    # ── Valida data ────────────────────────────────────────────────────────────
    try:
        target = date.fromisoformat(body.logged_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="Data inválida — use o formato YYYY-MM-DD.")

    if target > today:
        raise HTTPException(status_code=422, detail="Não é possível registrar refeições para datas futuras.")

    # Restrição de dias retroativos removida temporariamente — qualquer data passada é aceita

    # ── Extração via IA ────────────────────────────────────────────────────────
    try:
        extraction = await ai_service.extract_foods_from_text(body.description)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Serviço de IA temporariamente indisponível. Tente novamente em instantes.",
        ) from exc

    if not extraction.foods:
        raise HTTPException(
            status_code=422,
            detail="Não foi possível identificar alimentos na descrição. "
                   "Seja mais específico (ex: 'arroz, feijão e frango grelhado').",
        )

    # ── Enriquece com TACO/USDA ────────────────────────────────────────────────
    foods_raw = [
        {
            "name": f.name,
            "quantity_g": f.quantity_g,
            "est_calories_kcal": f.est_calories_kcal,
            "est_protein_g": f.est_protein_g,
            "est_carb_g": f.est_carb_g,
            "est_fat_g": f.est_fat_g,
        }
        for f in extraction.foods
    ]
    enriched = nutrition_service.enrich_foods(foods_raw)

    # Prefere o meal_type explicitado pelo usuário; usa o da IA como fallback
    meal_type = body.meal_type if body.meal_type != "other" else extraction.meal_type

    # ── logged_at: data alvo + hora padrão da refeição ────────────────────────
    default_hour = _MEAL_DEFAULT_HOURS.get(meal_type, 12)
    logged_at = datetime(
        target.year, target.month, target.day,
        default_hour, 0, 0,
        tzinfo=tz,
    )

    # ── Persistência ──────────────────────────────────────────────────────────
    meal_log = MealLog(
        user_id=current_user.id,
        meal_type=meal_type,
        raw_input_encrypted=encrypt(body.description),
        input_type="text",
        logged_at=logged_at,
        total_calories_kcal=round(sum(e.calories_kcal for e in enriched), 1),
        total_protein_g=round(sum(e.protein_g for e in enriched), 1),
        total_carb_g=round(sum(e.carb_g for e in enriched), 1),
        total_fat_g=round(sum(e.fat_g for e in enriched), 1),
        total_fiber_g=round(sum(e.fiber_g for e in enriched), 1),
        confirmed=True,
    )
    db.add(meal_log)
    await db.flush()

    for e in enriched:
        db.add(FoodItem(
            meal_log_id=meal_log.id,
            name=e.name,
            original_term=e.original_term,
            quantity_g=e.quantity_g,
            calories_kcal=e.calories_kcal,
            protein_g=e.protein_g,
            carb_g=e.carb_g,
            fat_g=e.fat_g,
            fiber_g=e.fiber_g,
            source=e.source,
            confidence_score=e.confidence_score,
            taco_code=e.taco_code,
        ))

    await db.commit()

    # Recarrega com food_items para o response
    result = await db.execute(
        select(MealLog)
        .options(selectinload(MealLog.food_items))
        .where(MealLog.id == meal_log.id)
    )
    return MealLogRead.model_validate(result.scalar_one())


@router.delete("/{meal_id}", status_code=204)
async def delete_meal(
    meal_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove um registro de refeição do usuário autenticado."""
    result = await db.execute(
        select(MealLog).where(
            MealLog.id == meal_id,
            MealLog.user_id == current_user.id,
        )
    )
    meal = result.scalar_one_or_none()
    if not meal:
        raise HTTPException(status_code=404, detail="Refeição não encontrada.")
    await db.delete(meal)
    await db.commit()
