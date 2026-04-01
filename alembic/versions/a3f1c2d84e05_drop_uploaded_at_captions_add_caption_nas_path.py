"""drop uploaded_at and captions, add caption_nas_path

Revision ID: a3f1c2d84e05
Revises: f790b2477953
Create Date: 2026-04-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a3f1c2d84e05'
down_revision: Union[str, Sequence[str], None] = 'f790b2477953'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('videos', 'uploaded_at')
    op.drop_column('videos', 'captions')
    op.add_column('videos', sa.Column(
        'caption_nas_path',
        postgresql.JSONB(astext_type=sa.Text()),
        nullable=True,
    ))


def downgrade() -> None:
    op.drop_column('videos', 'caption_nas_path')
    op.add_column('videos', sa.Column(
        'captions',
        postgresql.JSONB(astext_type=sa.Text()),
        nullable=True,
    ))
    op.add_column('videos', sa.Column('uploaded_at', sa.DateTime(), nullable=True))
