import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.meal_log import MealLog
    from app.models.meal_window import MealWindow
    from app.models.payment_subscription import PaymentSubscription
    from app.models.water_log import WaterLog
    from app.models.weekly_report import WeeklyReport


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    channel_type: Mapped[str] = mapped_column(String(20), nullable=False)  # telegram | whatsapp | web
    # Campos de autenticação web (nullable — usuários bot não têm senha)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    timezone: Mapped[str] = mapped_column(String(50), default="America/Sao_Paulo")
    daily_calorie_goal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    goal_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    plan: Mapped[str] = mapped_column(String(20), default="free")
    plan_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    conversation_state: Mapped[str] = mapped_column(String(30), default="IDLE")
    state_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    state_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    alerts_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    alerts_paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    report_frequency: Mapped[str] = mapped_column(String(20), default="weekly")  # weekly|monthly|quarterly|none
    onboarding_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    onboarding_step: Mapped[int] = mapped_column(Integer, default=0)
    lgpd_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    meal_logs: Mapped[list["MealLog"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    meal_windows: Mapped[list["MealWindow"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    weekly_reports: Mapped[list["WeeklyReport"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    water_logs: Mapped[list["WaterLog"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    payment_subscriptions: Mapped[list["PaymentSubscription"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def is_premium(self) -> bool:
        if self.plan == "free":
            return False
        if self.plan_expires_at is None:
            return True
        return datetime.utcnow() < self.plan_expires_at.replace(tzinfo=None)

    def __repr__(self) -> str:
        return f"<User channel_id={self.channel_id} plan={self.plan}>"
