"""Modelo de vínculo entre nutricionista e paciente (LGPD-aware)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class NutritionistPatient(Base):
    """Vínculo nutricionista ↔ paciente com controle de consentimento LGPD.

    status:
      pending  — convite enviado, aguardando resposta
      active   — paciente aceitou, nutricionista tem acesso
      revoked  — paciente revogou o acesso (LGPD)
      declined — paciente recusou o convite
      expired  — convite expirou antes de ser respondido
    """

    __tablename__ = "nutritionist_patients"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','active','revoked','declined','expired')",
            name="ck_np_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    nutritionist_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    patient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    patient_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    patient_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    invite_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    invited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # LGPD — Art. 11: consentimento explícito obrigatório para dados sensíveis de saúde
    consented_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # RF-PAINEL-11: limiar de inatividade (dias sem registro) para alertas no dashboard
    # Nutricionista pode configurar por paciente; default 3 dias
    inactivity_alert_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )

    nutritionist: Mapped["User"] = relationship(
        "User",
        foreign_keys=[nutritionist_id],
        back_populates="patients_as_nutritionist",
    )
    patient: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[patient_id],
        back_populates="links_as_patient",
    )

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    @property
    def is_expired(self) -> bool:
        return self.status == "expired" or (
            self.status == "pending"
            and datetime.utcnow() > self.expires_at.replace(tzinfo=None)
        )

    def __repr__(self) -> str:
        return (
            f"<NutritionistPatient nutri={self.nutritionist_id} "
            f"patient={self.patient_id} status={self.status}>"
        )
