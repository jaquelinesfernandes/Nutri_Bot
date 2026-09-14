"""ensure inactivity_alert_days column exists (safety net)

Revision ID: a1b2c3d4e5f6
Revises: f4a8b2c1d9e0
Create Date: 2026-09-14 12:00:00.000000

Safety net migration: garante que a coluna inactivity_alert_days existe
mesmo que a migration f4a8b2c1d9e0 tenha falhado silenciosamente.
Usa ADD COLUMN IF NOT EXISTS — seguro para rodar múltiplas vezes.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f4a8b2c1d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotente: se a coluna já existe, não faz nada.
    op.execute(
        "ALTER TABLE nutritionist_patients "
        "ADD COLUMN IF NOT EXISTS inactivity_alert_days INTEGER NOT NULL DEFAULT 3"
    )


def downgrade() -> None:
    # Não remove aqui — a downgrade real está em f4a8b2c1d9e0
    pass
