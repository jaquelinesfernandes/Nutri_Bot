"""increase_food_item_taco_code_to_32

Revision ID: 67daccf9eee9
Revises: e9f1a2b3c4d5
Create Date: 2026-09-12 17:02:52.217581

Motivação: códigos TACO têm 3 dígitos ("001"), mas códigos TBCA têm 13 chars
("tbca_BRC0001D"). O limite anterior de VARCHAR(10) causava falha de commit ao
salvar refeições identificadas via TBCA, resultando em "erro inesperado" no bot.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '67daccf9eee9'
down_revision: Union[str, None] = 'e9f1a2b3c4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'food_items',
        'taco_code',
        existing_type=sa.VARCHAR(length=10),
        type_=sa.String(length=32),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        'food_items',
        'taco_code',
        existing_type=sa.String(length=32),
        type_=sa.VARCHAR(length=10),
        existing_nullable=True,
    )
