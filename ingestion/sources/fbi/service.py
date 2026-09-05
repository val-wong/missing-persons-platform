"""Ingestion of FBI Wanted API items: raw layer, then canonical normalization.

Scope:
  - Raw layer (Source/SourceRecord/SourceSnapshot): unchanged from the original Phase 1
    raw-ingestion-only design (see docs/fbi-source.md) -- append-only, idempotent,
    never marks records inactive/removed.
  - Canonical layer (Person/Case/CaseSource): for items raw-ingested as NEW or CHANGED,
    classify (`classify_fbi_record`) -> normalize (`normalize_fbi_record`) -> validate
    -> persist (`ingestion.sources.base.persist_normalized_record`). Records the
    classifier does not mark IN_SCOPE never reach the canonical layer. See
    docs/fbi-normalization.md for exactly which fields are mapped and why.

Idempotency contract per FBI item, keyed by (source_id, external_id):
  - not seen before                -> create SourceRecord + SourceSnapshot, then
                                       classify/normalize/persist canonical if in scope
  - seen before, payload unchanged -> update last_seen_at only; canonical layer untouched
  - seen before, payload changed   -> update SourceRecord, create a NEW SourceSnapshot
                                       (existing snapshots are never modified), then
                                       re-run classify/normalize/persist canonical
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.source import Source
from app.models.source_record import SourceRecord
from app.models.source_snapshot import SourceSnapshot
from ingestion.sources.base import PersistOutcome, persist_normalized_record, validate_normalized_record
from ingestion.sources.fbi.classifier import ClassificationOutcome, classify_fbi_record
from ingestion.sources.fbi.client import FBIApiClient, FBIApiError
from ingestion.sources.fbi.normalize import normalize_fbi_record

logger = logging.getLogger("ingestion.fbi")

FBI_SOURCE_CODE = "fbi"
DEFAULT_MAX_PAGES = 1  # Never ingest the whole dataset unless explicitly requested.

# Identifies the deterministic Phase 1 field-mapping rules that produced a CaseSource
# link, in case this platform ever implements a different mapping strategy alongside it.
FBI_LINK_METHOD = "fbi_deterministic_normalization_v1"


class IngestOutcome(str, Enum):
    NEW = "new"
    CHANGED = "changed"
    UNCHANGED = "unchanged"


@dataclass
class IngestionStats:
    pages_fetched: int = 0
    items_received: int = 0
    records_new: int = 0
    records_changed: int = 0
    records_unchanged: int = 0
    snapshots_created: int = 0
    failures: int = 0
    errors: list[str] = field(default_factory=list)

    # Canonical layer (only attempted for raw NEW/CHANGED items).
    canonical_created: int = 0
    canonical_updated: int = 0
    canonical_unchanged: int = 0
    canonical_out_of_scope: int = 0
    canonical_validation_failed: int = 0
    canonical_failures: int = 0

    def as_summary(self) -> str:
        return (
            f"pages_fetched={self.pages_fetched} items_received={self.items_received} "
            f"new={self.records_new} changed={self.records_changed} "
            f"unchanged={self.records_unchanged} snapshots_created={self.snapshots_created} "
            f"failures={self.failures} | "
            f"canonical_created={self.canonical_created} canonical_updated={self.canonical_updated} "
            f"canonical_unchanged={self.canonical_unchanged} "
            f"canonical_out_of_scope={self.canonical_out_of_scope} "
            f"canonical_validation_failed={self.canonical_validation_failed} "
            f"canonical_failures={self.canonical_failures}"
        )


def canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    """Deterministic serialization used for hashing: sorted keys, fixed separators."""
    return json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode(
        "utf-8"
    )


def hash_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def extract_external_id(item: dict[str, Any]) -> str:
    """The FBI API's `uid` is a stable, opaque per-record identifier -- see docs/fbi-source.md."""
    uid = item.get("uid")
    if not isinstance(uid, str) or not uid.strip():
        raise ValueError("FBI item is missing a usable 'uid' field")
    return uid


def extract_source_url(item: dict[str, Any]) -> str:
    url = item.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ValueError("FBI item is missing a usable 'url' field")
    return url


def extract_source_modified_at(item: dict[str, Any]) -> datetime | None:
    modified = item.get("modified")
    if not isinstance(modified, str) or not modified.strip():
        return None
    try:
        return datetime.fromisoformat(modified)
    except ValueError:
        logger.warning("Could not parse FBI 'modified' timestamp value (unexpected format)")
        return None


def get_fbi_source(db: Session) -> Source:
    source = db.scalar(select(Source).where(Source.code == FBI_SOURCE_CODE))
    if source is None:
        raise RuntimeError(
            "No Source row with code='fbi' found. Run `python -m app.services.seed` first."
        )
    return source


def ingest_item(db: Session, source: Source, item: dict[str, Any], now: datetime) -> IngestOutcome:
    """Apply the idempotency contract for a single FBI item. Raises on unusable items."""
    external_id = extract_external_id(item)
    payload_hash = hash_payload(item)

    existing = db.scalar(
        select(SourceRecord).where(
            SourceRecord.source_id == source.id,
            SourceRecord.external_id == external_id,
        )
    )

    if existing is None:
        record = SourceRecord(
            source_id=source.id,
            external_id=external_id,
            source_url=extract_source_url(item),
            first_seen_at=now,
            last_seen_at=now,
            source_modified_at=extract_source_modified_at(item),
            payload_hash=payload_hash,
            active=True,
        )
        db.add(record)
        db.flush()  # assign record.id for the snapshot FK
        db.add(
            SourceSnapshot(
                source_record_id=record.id,
                payload=item,
                payload_hash=payload_hash,
                fetched_at=now,
            )
        )
        return IngestOutcome.NEW

    if existing.payload_hash == payload_hash:
        existing.last_seen_at = now
        return IngestOutcome.UNCHANGED

    existing.payload_hash = payload_hash
    existing.last_seen_at = now
    existing.source_url = extract_source_url(item)
    existing.source_modified_at = extract_source_modified_at(item)
    db.add(
        SourceSnapshot(
            source_record_id=existing.id,
            payload=item,
            payload_hash=payload_hash,
            fetched_at=now,
        )
    )
    return IngestOutcome.CHANGED


def _normalize_and_persist_canonical(
    db: Session, source: Source, external_id: str, item: dict[str, Any], stats: IngestionStats
) -> None:
    """Classify, normalize, validate, and persist canonical fields for one item that was
    just raw-ingested as NEW or CHANGED. Never raises to the caller -- failures are
    counted/logged like raw-item failures, so one bad record can't abort the run.
    """
    classification = classify_fbi_record(item)
    if classification.outcome is not ClassificationOutcome.IN_SCOPE:
        stats.canonical_out_of_scope += 1
        return

    normalized = normalize_fbi_record(item)
    validation = validate_normalized_record(normalized)
    if not validation.valid:
        stats.canonical_validation_failed += 1
        logger.warning(
            "FBI item uid=%s failed canonical validation: %s",
            external_id,
            "; ".join(validation.errors),
        )
        return

    source_record = db.scalar(
        select(SourceRecord).where(
            SourceRecord.source_id == source.id,
            SourceRecord.external_id == external_id,
        )
    )
    if source_record is None:
        # Should be unreachable -- raw ingestion just created/updated this row in the
        # same transaction -- but fail closed rather than raise into the batch loop.
        logger.warning(
            "FBI item uid=%s has no SourceRecord after raw ingestion; skipping canonical persist",
            external_id,
        )
        return

    outcome = persist_normalized_record(db, source_record, normalized, link_method=FBI_LINK_METHOD)
    if outcome is PersistOutcome.CREATED:
        stats.canonical_created += 1
    elif outcome is PersistOutcome.UPDATED:
        stats.canonical_updated += 1
    else:
        stats.canonical_unchanged += 1


def _ingest_items(
    db: Session,
    source: Source,
    items: list[dict[str, Any]],
    stats: IngestionStats,
    now: datetime,
) -> None:
    for item in items:
        stats.items_received += 1
        uid = item.get("uid") if isinstance(item, dict) else None
        try:
            with db.begin_nested():
                outcome = ingest_item(db, source, item, now)
        except Exception as exc:  # noqa: BLE001 -- one bad item must not abort the run
            stats.failures += 1
            stats.errors.append(f"uid={uid or '<unknown>'}: {exc}")
            logger.warning("Failed to ingest FBI item uid=%s: %s", uid or "<unknown>", exc)
            continue

        if outcome is IngestOutcome.NEW:
            stats.records_new += 1
            stats.snapshots_created += 1
        elif outcome is IngestOutcome.CHANGED:
            stats.records_changed += 1
            stats.snapshots_created += 1
        else:
            stats.records_unchanged += 1
            continue  # payload unchanged: nothing new to (re)normalize

        try:
            with db.begin_nested():
                _normalize_and_persist_canonical(db, source, uid, item, stats)
        except Exception as exc:  # noqa: BLE001 -- one bad item must not abort the run
            stats.canonical_failures += 1
            logger.warning(
                "Failed to normalize/persist canonical record for FBI item uid=%s: %s",
                uid or "<unknown>",
                exc,
            )


def run_fbi_ingestion(
    db: Session,
    client: FBIApiClient,
    *,
    max_pages: int | None = DEFAULT_MAX_PAGES,
    page_size: int = 20,
    start_page: int = 1,
) -> IngestionStats:
    """Fetch up to `max_pages` pages from the FBI API and ingest them.

    `max_pages=None` fetches every page. Pass it deliberately -- see docs/fbi-source.md
    for why unattended full-database fetches are not the default anywhere in this module.
    Progress is committed after each page, so a failure on page N does not lose pages
    that were already ingested successfully.
    """
    source = get_fbi_source(db)
    stats = IngestionStats()
    now = datetime.now(timezone.utc)

    pages = client.iter_pages(start_page=start_page, page_size=page_size, max_pages=max_pages)
    while True:
        try:
            response = next(pages)
        except StopIteration:
            break
        except FBIApiError as exc:
            logger.error("Stopping FBI ingestion run after a page fetch failure: %s", exc)
            stats.failures += 1
            stats.errors.append(str(exc))
            break

        stats.pages_fetched += 1
        logger.info("Fetched FBI page %d with %d item(s)", response.page, len(response.items))

        _ingest_items(db, source, response.items, stats, now)
        db.commit()

    logger.info("FBI ingestion run complete: %s", stats.as_summary())
    return stats
