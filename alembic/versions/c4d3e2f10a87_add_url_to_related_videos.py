"""add url to related_videos

Revision ID: c4d3e2f10a87
Revises: b7e2a1f93c06
Create Date: 2026-04-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c4d3e2f10a87'
down_revision: Union[str, Sequence[str], None] = 'b7e2a1f93c06'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('related_videos', sa.Column('url', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('related_videos', 'url')
