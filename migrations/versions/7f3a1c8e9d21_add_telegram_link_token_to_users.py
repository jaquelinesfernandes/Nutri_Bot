"""add_telegram_link_token_to_users

Revision ID: 7f3a1c8e9d21
Revises: 4ed62c056085
Create Date: 2026-08-19 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7f3a1c8e9d21'
down_revision: Union[str, None] = '4ed62c056085'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('web_link_token', sa.String(length=8), nullable=True))
    op.add_column('users', sa.Column('web_link_token_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_users_web_link_token', 'users', ['web_link_token'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_users_web_link_token', table_name='users')
    op.drop_column('users', 'web_link_token_expires_at')
    op.drop_column('users', 'web_link_token')
