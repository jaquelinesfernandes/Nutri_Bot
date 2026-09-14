"""add inactivity_alert_days to nutritionist_patients

Revision ID: f4a8b2c1d9e0
Revises: 67daccf9eee9
Create Date: 2026-09-14 00:00:00.000000

RF-PAINEL-11: Adiciona coluna inactivity_alert_days à tabela nutritionist_patients.
Permite que a nutricionista configure por paciente o limiar de inatividade (dias
sem registro) que dispara alertas visuais no painel dashboard.
Default: 3 dias (comportamento anterior preservado).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f4a8b2c1d9e0"
down_revision: Union[str, None] = "67daccf9eee9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Usa SQL direto para ser idempotente: IF NOT EXISTS evita falha se a coluna
    # já existir (ex: adicionada manualmente ou migration rodada parcialmente).
    op.execute(
        "ALTER TABLE nutritionist_patients "
        "ADD COLUMN IF NOT EXISTS inactivity_alert_days INTEGER NOT NULL DEFAULT 3"
    )


def downgrade() -> None:
    op.drop_column("nutritionist_patients", "inactivity_alert_days")
