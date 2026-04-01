"""drop like_count from comments

Revision ID: b7e2a1f93c06
Revises: a3f1c2d84e05
Create Date: 2026-04-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b7e2a1f93c06'
down_revision: Union[str, Sequence[str], None] = 'a3f1c2d84e05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('comments', 'like_count')


def downgrade() -> None:
    op.add_column('comments', sa.Column('like_count', sa.BigInteger(), nullable=True))
