"""add custom_emoji_id to goods

Revision ID: a3b4c5d6e7f8
Revises: e5f6a7b8c9d0
Create Date: 2026-05-20 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('goods', sa.Column('custom_emoji_id', sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column('goods', 'custom_emoji_id')
