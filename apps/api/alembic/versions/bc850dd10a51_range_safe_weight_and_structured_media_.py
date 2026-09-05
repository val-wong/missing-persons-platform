"""range-safe weight and structured media schema

Revision ID: bc850dd10a51
Revises: c995585a2ffb
Create Date: 2026-09-05 04:17:22.931529

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'bc850dd10a51'
down_revision: Union[str, None] = 'c995585a2ffb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # height_cm / weight_kg: dropped, not renamed. Verified 0/104 canonical Person rows
    # populated either column before this migration was applied (see
    # docs/fbi-normalization.md) -- no data-preservation concern, a single scalar can't
    # losslessly become a min/max/raw/temporal_context group anyway.
    op.add_column('people', sa.Column('height_min_cm', sa.Float(), nullable=True))
    op.add_column('people', sa.Column('height_max_cm', sa.Float(), nullable=True))
    op.add_column('people', sa.Column('height_raw', sa.String(length=255), nullable=True))
    op.add_column('people', sa.Column('height_temporal_context', sa.String(length=64), nullable=True))
    op.add_column('people', sa.Column('weight_min_kg', sa.Float(), nullable=True))
    op.add_column('people', sa.Column('weight_max_kg', sa.Float(), nullable=True))
    op.add_column('people', sa.Column('weight_raw', sa.String(length=255), nullable=True))
    op.add_column('people', sa.Column('weight_temporal_context', sa.String(length=64), nullable=True))
    op.drop_column('people', 'height_cm')
    op.drop_column('people', 'weight_kg')

    # photo_urls -> photos: a genuine rename (same JSONB column, same 0-population
    # state), not a drop+add -- the shape contract changes (list[str] -> list of
    # {url, full_url, thumbnail_url, caption} objects) but that's an application-level
    # convention, not something Postgres enforces on a JSONB column either way.
    op.alter_column('people', 'photo_urls', new_column_name='photos')


def downgrade() -> None:
    op.alter_column('people', 'photos', new_column_name='photo_urls')

    op.add_column('people', sa.Column('weight_kg', sa.Float(), nullable=True))
    op.add_column('people', sa.Column('height_cm', sa.Float(), nullable=True))
    op.drop_column('people', 'weight_temporal_context')
    op.drop_column('people', 'weight_raw')
    op.drop_column('people', 'weight_max_kg')
    op.drop_column('people', 'weight_min_kg')
    op.drop_column('people', 'height_temporal_context')
    op.drop_column('people', 'height_raw')
    op.drop_column('people', 'height_max_cm')
    op.drop_column('people', 'height_min_cm')
