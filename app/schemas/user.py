import uuid

from pydantic import BaseModel


class UserProfile(BaseModel):
    id: uuid.UUID
    name: str | None
    email: str | None
    plan: str
    daily_calorie_goal: int | None
    goal_type: str | None
    timezone: str

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    name: str | None = None
    daily_calorie_goal: int | None = None
    goal_type: str | None = None
    timezone: str | None = None
