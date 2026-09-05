import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.person import Person


class Case(Base):
    """A missing-person case, as reported by an investigating agency / source.

    Case facts (status, location, circumstances) reflect what sources report and are
    always traceable back to source records via CaseSource.
    """

    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("people.id"), nullable=False, index=True
    )
    person: Mapped[Person] = relationship()

    # Nullable: not every source reports a usable case-status value (e.g. FBI's
    # `status` field carries no per-record signal today -- see docs/fbi-normalization.md).
    case_status: Mapped[str | None] = mapped_column(String(64), nullable=True)

    missing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    missing_city: Mapped[str | None] = mapped_column(String(255), nullable=True)
    missing_county: Mapped[str | None] = mapped_column(String(255), nullable=True)
    missing_state: Mapped[str | None] = mapped_column(String(255), nullable=True)
    missing_country: Mapped[str | None] = mapped_column(String(255), nullable=True)
    age_at_missing: Mapped[int | None] = mapped_column(Integer, nullable=True)
    circumstances: Mapped[str | None] = mapped_column(Text, nullable=True)

    investigating_agency: Mapped[str | None] = mapped_column(String(255), nullable=True)
    agency_case_number: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
