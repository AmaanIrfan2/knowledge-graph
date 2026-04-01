"""add unique constraint to related_videos

Revision ID: f790b2477953
Revises: 0c5edf38d977
Create Date: 2026-03-26 17:52:36.421934

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f790b2477953'
down_revision: Union[str, Sequence[str], None] = '0c5edf38d977'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_unique_constraint(
        "uq_related_videos_video_related",
        "related_videos",
        ["video_id", "related_video_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_related_videos_video_related", "related_videos")
