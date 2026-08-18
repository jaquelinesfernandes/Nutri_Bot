from typing import Literal

from pydantic import BaseModel, Field


class ExtractedFoodItem(BaseModel):
    name: str
    original_term: str = ""
    quantity_g: float = Field(gt=0)
    taco_code: str | None = None
    confidence_score: float = Field(default=0.8, ge=0.0, le=1.0)
    # Estimativas por 100g fornecidas pelo Claude como fallback
    est_calories_kcal: float | None = None
    est_protein_g: float | None = None
    est_carb_g: float | None = None
    est_fat_g: float | None = None


class FoodExtractionResponse(BaseModel):
    foods: list[ExtractedFoodItem]
    meal_type: Literal[
        "breakfast", "morning_snack", "lunch", "afternoon_snack", "dinner", "snack", "other"
    ] = "other"
    meal_time_hint: str | None = None
    unrecognized_terms: list[str] = []
    image_has_food: bool = True
    image_quality: Literal["good", "poor", "unreadable"] = "good"
    overall_confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ReportSuggestion(BaseModel):
    category: Literal["proteina", "carboidrato", "gordura", "hidratacao", "horario", "variedade"]
    text: str
    priority: Literal["high", "medium", "low"] = "medium"


class ReportSuggestionsResponse(BaseModel):
    highlights: list[str]
    suggestions: list[ReportSuggestion]
    weekly_insight: str
