import uuid
from datetime import date, datetime

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

    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    hair_color: Mapped[str | None] = mapped_column(String(64), nullable=True)
    eye_color: Mapped[str | None] = mapped_column(String(64), nullable=True)
    distinguishing_characteristics: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_urls: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
