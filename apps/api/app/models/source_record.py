from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SourceRecord(Base):
    """One raw, immutable-identity record as it exists at a source (identified by external_id).

    A SourceRecord tracks the lifecycle of a record at the source (first/last seen, removal),
    while the actual raw payload over time is captured in SourceSnapshot rows.
    """

    __tablename__ = "source_records"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_source_records_source_id_external_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
