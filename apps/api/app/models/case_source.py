import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CaseSource(Base):
    """Traceability link between a canonical Case and the raw SourceRecord(s) it derives from.

    This is the join that lets every canonical case be traced back to one or more raw
    source records, and records how the link was established (e.g. deterministic key match).
    """

    __tablename__ = "case_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False, index=True
    )
    source_record_id: Mapped[int] = mapped_column(
        ForeignKey("source_records.id"), nullable=False, index=True
    )

    link_method: Mapped[str] = mapped_column(String(64), nullable=False)
    link_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # The exact normalized canonical field values *this* SourceRecord produced when it
    # was normalized -- independent of which of those values (if any) ended up as the
    # canonical value on the linked Case/Person. This is what lets two sources disagree
    # on a field without either one silently overwriting the other: each source's own
    # contribution stays inspectable here, keyed by this CaseSource row, forever. See
    # docs/architecture.md for the reconciliation rule this supports.
    contributed_fields: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
