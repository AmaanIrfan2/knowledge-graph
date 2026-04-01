"""add unique constraint to linked_articles

Revision ID: 0c5edf38d977
Revises: dd921eae144a
Create Date: 2026-03-26 17:35:53.194726

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0c5edf38d977'
down_revision: Union[str, Sequence[str], None] = 'dd921eae144a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_unique_constraint(
        "uq_linked_articles_video_url",
        "linked_articles",
        ["video_id", "url"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_linked_articles_video_url", "linked_articles")
