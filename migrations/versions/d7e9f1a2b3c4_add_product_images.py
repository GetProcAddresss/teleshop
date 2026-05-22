"""add product_images table

Revision ID: d7e9f1a2b3c4
Revises: c5d8e2f3a9b1
Create Date: 2026-05-22 18:45:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd7e9f1a2b3c4'
down_revision: Union[str, None] = 'c5d8e2f3a9b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'product_images',
        sa.Column('token', sa.String(48), primary_key=True),
        sa.Column('mime', sa.String(64), nullable=False),
        sa.Column('data', sa.LargeBinary(), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('product_images')
