"""add image_url to goods

Revision ID: c5d8e2f3a9b1
Revises: a3b4c5d6e7f8
Create Date: 2026-05-21 12:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c5d8e2f3a9b1'
down_revision: Union[str, None] = 'a3b4c5d6e7f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('goods', sa.Column('image_url', sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column('goods', 'image_url')
