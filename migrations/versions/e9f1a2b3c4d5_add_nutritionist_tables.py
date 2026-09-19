"""add_nutritionist_tables

Revision ID: e9f1a2b3c4d5
Revises: 7f3a1c8e9d21
Create Date: 2026-09-12 00:00:00.000000

Sprint B2B-1 — Painel Nutricionista:
  - Adiciona trial_ends_at na tabela users
  - Cria tabela nutritionist_patients (vínculo nutricionista ↔ paciente)
  - Cria tabela clinical_notes (notas clínicas — B2B-2 usa; criada aqui para migração atômica)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e9f1a2b3c4d5"
down_revision: Union[str, None] = "7f3a1c8e9d21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users: trial nutricionista ─────────────────────────────────────────────
    op.add_column(
        "users",
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── nutritionist_patients ──────────────────────────────────────────────────
    op.create_table(
        "nutritionist_patients",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("nutritionist_id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=True),          # NULL enquanto pendente
        sa.Column("patient_phone", sa.String(length=20), nullable=True),
        sa.Column("patient_name", sa.String(length=100), nullable=True),
        sa.Column("invite_token", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "invited_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','active','revoked','declined','expired')",
            name="ck_np_status",
        ),
        sa.ForeignKeyConstraint(["nutritionist_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["patient_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("invite_token"),
    )
    op.create_index(
        "idx_nutritionist_patients_nutri",
        "nutritionist_patients",
        ["nutritionist_id"],
    )
    op.create_index(
        "idx_nutritionist_patients_patient",
        "nutritionist_patients",
        ["patient_id"],
    )
    op.create_index(
        "idx_nutritionist_patients_token",
        "nutritionist_patients",
        ["invite_token"],
        unique=True,
    )

    # ── clinical_notes ─────────────────────────────────────────────────────────
    op.create_table(
        "clinical_notes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("nutritionist_id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("note_text", sa.Text(), nullable=False),
        sa.Column("consultation_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["nutritionist_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["patient_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_clinical_notes_patient",
        "clinical_notes",
        ["patient_id", "consultation_date"],
    )


def downgrade() -> None:
    op.drop_index("idx_clinical_notes_patient", table_name="clinical_notes")
    op.drop_table("clinical_notes")

    op.drop_index("idx_nutritionist_patients_token", table_name="nutritionist_patients")
    op.drop_index("idx_nutritionist_patients_patient", table_name="nutritionist_patients")
    op.drop_index("idx_nutritionist_patients_nutri", table_name="nutritionist_patients")
    op.drop_table("nutritionist_patients")

    op.drop_column("users", "trial_ends_at")
