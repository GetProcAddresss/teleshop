"""drop unique constraint on item_values(item_id, value)

Revision ID: e8a1b2c3d4e5
Revises: d7e9f1a2b3c4
Create Date: 2026-05-22 20:15:00.000000
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


revision: str = 'e8a1b2c3d4e5'
down_revision: Union[str, None] = 'd7e9f1a2b3c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _constraint_exists(inspector, table: str, name: str) -> bool:
    try:
        for c in inspector.get_unique_constraints(table):
            if c.get("name") == name:
                return True
    except Exception:
        return False
    return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    for name in ("uq_item_value_per_item_new", "uq_item_value_per_item"):
        if _constraint_exists(inspector, "item_values", name):
            op.drop_constraint(name, "item_values", type_="unique")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not _constraint_exists(inspector, "item_values", "uq_item_value_per_item"):
        op.create_unique_constraint(
            "uq_item_value_per_item", "item_values", ["item_id", "value"]
        )
