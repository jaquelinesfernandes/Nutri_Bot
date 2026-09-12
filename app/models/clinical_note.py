"""Notas clínicas — escrita exclusiva da nutricionista, privada por par nutricionista/paciente."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class ClinicalNote(Base):
    """Nota clínica vinculada a uma data de consulta.

    Privacidade: um segundo nutricionista vinculado ao mesmo paciente
    NÃO vê as notas de outro nutricionista — a query sempre filtra por
    nutritionist_id além de patient_id.
    """

    __tablename__ = "clinical_notes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    nutritionist_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    note_text: Mapped[str] = mapped_column(Text, nullable=False)
    consultation_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    nutritionist: Mapped["User"] = relationship(
        "User", foreign_keys=[nutritionist_id]
    )
    patient: Mapped["User"] = relationship(
        "User", foreign_keys=[patient_id]
    )

    def __repr__(self) -> str:
        return (
            f"<ClinicalNote nutri={self.nutritionist_id} "
            f"patient={self.patient_id} date={self.consultation_date}>"
        )
