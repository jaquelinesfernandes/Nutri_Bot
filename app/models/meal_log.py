import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.food_item import FoodItem
    from app.models.user import User


class MealLog(Base):
    __tablename__ = "meal_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    logged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    meal_type: Mapped[str] = mapped_column(String(20), nullable=False)  # breakfast|morning_snack|lunch|afternoon_snack|dinner|snack|other
    raw_input_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)  # AES-256
    input_type: Mapped[str] = mapped_column(String(10), default="text")  # text|photo|audio
    total_calories_kcal: Mapped[float] = mapped_column(Float, default=0.0)
    total_protein_g: Mapped[float] = mapped_column(Float, default=0.0)
    total_carb_g: Mapped[float] = mapped_column(Float, default=0.0)
    total_fat_g: Mapped[float] = mapped_column(Float, default=0.0)
    total_fiber_g: Mapped[float] = mapped_column(Float, default=0.0)
    confirmed: Mapped[bool] = mapped_column(default=False)

    user: Mapped["User"] = relationship(back_populates="meal_logs")
    food_items: Mapped[list["FoodItem"]] = relationship(
        back_populates="meal_log", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<MealLog {self.meal_type} {self.total_calories_kcal:.0f}kcal>"
