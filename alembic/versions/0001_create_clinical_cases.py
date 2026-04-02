"""create clinical_cases table

Revision ID: 0001
Revises:
Create Date: 2026-03-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "clinical_cases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("caso_clinico", sa.String(), nullable=False),
        sa.Column("agentes_sugeridos", sa.JSON(), nullable=True),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("findings", sa.JSON(), nullable=False),
        sa.Column("red_flags", sa.JSON(), nullable=False),
        sa.Column("recommendations", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("agentes_activados", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("clinical_cases")
