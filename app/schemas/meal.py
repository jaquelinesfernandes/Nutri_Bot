import uuid
from datetime import datetime

from pydantic import BaseModel


class FoodItemRead(BaseModel):
    name: str
    quantity_g: float
    calories_kcal: float
    protein_g: float
    carb_g: float
    fat_g: float
    source: str
    confidence_score: float

    model_config = {"from_attributes": True}


class MealLogRead(BaseModel):
    id: uuid.UUID
    meal_type: str
    logged_at: datetime
    total_calories_kcal: float
    total_protein_g: float
    total_carb_g: float
    total_fat_g: float
    food_items: list[FoodItemRead]

    model_config = {"from_attributes": True}


class DailyBalance(BaseModel):
    date: str
    total_calories_kcal: float
    total_protein_g: float
    total_carb_g: float
    total_fat_g: float
    goal_calories: int | None
    remaining_calories: float | None
    meals: list[MealLogRead]
