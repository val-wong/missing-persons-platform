import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Person(Base):
    """A canonical person entity, derived from and traceable to one or more source records.

    Canonical fields here represent what authoritative sources report, never inferred or
    speculative identification. Every field is nullable except `display_name`: sources
    frequently omit most of these, and a missing value must never be guessed or defaulted.
    """

    __tablename__ = "people"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    given_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    middle_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    family_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    suffix: Mapped[str | None] = mapped_column(String(32), nullable=True)
    display_name: Mapped[str] = mapped_column(String(512), nullable=False)
    aliases: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Current/estimated age, as reported -- distinct from Case.age_at_missing (age at
    # time of disappearance). Sources do not always distinguish the two; see
    # docs/fbi-normalization.md for why this platform treats them as separate fields
    # rather than guessing which one a source's "age" field represents.
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sex: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Flat, typed columns rather than a single scalar or a nested JSON object -- keeps
    # this model consistent with every other Person field, keeps native Postgres types/
    # indexing available, and requires no changes to the generic contributed_fields()
    # provenance machinery in ingestion/sources/base.py. The public API composes these
    # into nested height/weight objects (see app/schemas/person.py); see
    # docs/fbi-normalization.md for the full design rationale.
    #
    # `*_raw` preserves the source's literal reported text (when a source provides
    # one) -- same "preserve exactly reported, not just a derived number" principle
    # already applied to hair_color/eye_color. `*_temporal_context` records what point
    # in time a value applies to (e.g. "at_disappearance") ONLY when a source
    # explicitly states it; NULL means unstated, never guessed as "current."
    height_min_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    height_max_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    height_raw: Mapped[str | None] = mapped_column(String(255), nullable=True)
    height_temporal_context: Mapped[str | None] = mapped_column(String(64), nullable=True)

    weight_min_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_max_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_raw: Mapped[str | None] = mapped_column(String(255), nullable=True)
    weight_temporal_context: Mapped[str | None] = mapped_column(String(64), nullable=True)

    hair_color: Mapped[str | None] = mapped_column(String(64), nullable=True)
    eye_color: Mapped[str | None] = mapped_column(String(64), nullable=True)
    distinguishing_characteristics: Mapped[str | None] = mapped_column(Text, nullable=True)

    # List of {url, full_url, thumbnail_url, caption} objects, order preserved exactly
    # as the source reported it. Every key may be null where a source doesn't
    # distinguish that variant. These are source-owned URLs, never mirrored/downloaded
    # locally -- see docs/fbi-normalization.md.
    photos: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
