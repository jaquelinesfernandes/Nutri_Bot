import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.meal_log import MealLog


class FoodItem(Base):
    __tablename__ = "food_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meal_log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meal_logs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    original_term: Mapped[str | None] = mapped_column(String(200), nullable=True)
    quantity_g: Mapped[float] = mapped_column(Float, nullable=False)
    calories_kcal: Mapped[float] = mapped_column(Float, default=0.0)
    protein_g: Mapped[float] = mapped_column(Float, default=0.0)
    carb_g: Mapped[float] = mapped_column(Float, default=0.0)
    fat_g: Mapped[float] = mapped_column(Float, default=0.0)
    fiber_g: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(20), default="taco")  # taco|taco_alias|taco_fuzzy|usda_fuzzy|gpt_estimated
    confidence_score: Mapped[float] = mapped_column(Float, default=1.0)
    taco_code: Mapped[str | None] = mapped_column(String(10), nullable=True)

    meal_log: Mapped["MealLog"] = relationship(back_populates="food_items")

    def __repr__(self) -> str:
        return f"<FoodItem {self.name} {self.quantity_g}g {self.calories_kcal:.0f}kcal>"
