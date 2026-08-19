"""Endpoints de perfil do usuário web."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User
from app.schemas.user import UserProfile, UserUpdate
from app.utils.jwt import get_current_user

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/me", response_model=UserProfile)
async def get_me(current_user: User = Depends(get_current_user)) -> UserProfile:
    return UserProfile.model_validate(current_user)


@router.put("/me", response_model=UserProfile)
async def update_me(
    body: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserProfile:
    if body.name is not None:
        current_user.first_name = body.name
    if body.daily_calorie_goal is not None:
        current_user.daily_calorie_goal = body.daily_calorie_goal
    if body.goal_type is not None:
        current_user.goal_type = body.goal_type
    if body.timezone is not None:
        current_user.timezone = body.timezone

    await db.commit()
    await db.refresh(current_user)
    return UserProfile.model_validate(current_user)
