"""extend canonical schema for full field set + per-source field provenance

Revision ID: c995585a2ffb
Revises: 08cbf41a4cf2
Create Date: 2026-09-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c995585a2ffb'
down_revision: Union[str, None] = '08cbf41a4cf2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('people', sa.Column('aliases', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('people', sa.Column('age', sa.Integer(), nullable=True))
    op.add_column('people', sa.Column('height_cm', sa.Float(), nullable=True))
    op.add_column('people', sa.Column('weight_kg', sa.Float(), nullable=True))
    op.add_column('people', sa.Column('hair_color', sa.String(length=64), nullable=True))
    op.add_column('people', sa.Column('eye_color', sa.String(length=64), nullable=True))
    op.add_column('people', sa.Column('distinguishing_characteristics', sa.Text(), nullable=True))
    op.add_column('people', sa.Column('photo_urls', postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    op.alter_column('cases', 'case_status', existing_type=sa.String(length=64), nullable=True)

    op.add_column(
        'case_sources',
        sa.Column('contributed_fields', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('case_sources', 'contributed_fields')

    # Will fail with a NotNullViolation if any Case row already has case_status=NULL
    # (expected once real data exists -- FBI's own case_status is never populated, see
    # docs/fbi-normalization.md). That failure is correct: this downgrade cannot restore
    # data it never had, and must not silently invent a placeholder value.
    op.alter_column('cases', 'case_status', existing_type=sa.String(length=64), nullable=False)

    op.drop_column('people', 'photo_urls')
    op.drop_column('people', 'distinguishing_characteristics')
    op.drop_column('people', 'eye_color')
    op.drop_column('people', 'hair_color')
    op.drop_column('people', 'weight_kg')
    op.drop_column('people', 'height_cm')
    op.drop_column('people', 'age')
    op.drop_column('people', 'aliases')
