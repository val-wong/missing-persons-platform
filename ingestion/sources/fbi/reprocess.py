"""Historical reprocessing (backfill) of already-stored FBI SourceRecords through the
canonical pipeline, entirely from stored SourceSnapshots -- never the live FBI API.

Why this exists: FBI raw ingestion (Source/SourceRecord/SourceSnapshot) predates the
canonical normalization pipeline (Person/Case/CaseSource) -- see docs/fbi-source.md and
docs/fbi-normalization.md. Records raw-ingested before canonical normalization existed,
or before a classifier/normalizer fix, were never classified/normalized/persisted. This
module lets that catch-up happen by replaying stored snapshots, per the
"reprocessing never requires re-fetching" principle in docs/architecture.md.

Flow per stored FBI SourceRecord -- identical stages to live ingestion, and the exact
same functions, never reimplemented:

    latest SourceSnapshot -> classify_fbi_record -> normalize_fbi_record
        -> validate_normalized_record -> persist_normalized_record

Differences from live ingestion (`ingestion.sources.fbi.service.run_fbi_ingestion`):
  - Never calls the FBI API or `FBIApiClient` -- input is exclusively already-stored
    `SourceSnapshot` rows.
  - Never creates/updates a `SourceRecord` or `SourceSnapshot` -- the raw layer is
    read-only here; reprocessing must never alter provenance.
  - Iterates every stored `SourceRecord` for the source (not just ones raw-ingested as
    NEW/CHANGED in the current run), since the point is to catch up records the
    canonical pipeline never saw the first time.

Idempotency and persistence semantics are otherwise unchanged: persistence is delegated
entirely to `ingestion.sources.base.persist_normalized_record`, which keys off
`source_record_id`, so re-running reprocessing (or mixing it with live ingestion) can
never merge two different SourceRecords into one Case, and a record whose normalized
output hasn't changed is always a no-op.

This module is intentionally FBI-specific, mirroring `ingestion.sources.fbi.service`
rather than introducing a generic cross-source "reprocessor" abstraction -- with a
single source implemented there is nothing real to generalize yet (see
`ingestion/sources/base.py`'s own rationale). A second source can reuse the same shape
(latest-snapshot selection + classify/normalize/validate/persist replay) by writing its
own `ingestion/sources/<source>/reprocess.py` the same way it writes its own `service.py`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.source import Source
from app.models.source_record import SourceRecord
from app.models.source_snapshot import SourceSnapshot
from ingestion.sources.base import PersistOutcome, persist_normalized_record, validate_normalized_record
from ingestion.sources.fbi.classifier import ClassificationOutcome, classify_fbi_record
from ingestion.sources.fbi.normalize import normalize_fbi_record
from ingestion.sources.fbi.service import FBI_LINK_METHOD

logger = logging.getLogger("ingestion.fbi.reprocess")


class _DryRunRollback(Exception):
    """Internal-only signal used to force a SAVEPOINT rollback after computing what
    `persist_normalized_record` would do. Always caught inside `_reprocess_one`; never
    escapes this module."""


@dataclass
class ReprocessStats:
    """Aggregate counters for one reprocessing run. In dry-run mode, `created`/
    `updated`/`unchanged` describe what *would* happen -- computed by actually invoking
    `persist_normalized_record` inside a SAVEPOINT that is then rolled back, never by a
    separate prediction of its logic."""

    dry_run: bool = False
    records_inspected: int = 0
    snapshots_missing: int = 0
    in_scope: int = 0
    out_of_scope: int = 0
    validation_failed: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    failures: int = 0
    errors: list[str] = field(default_factory=list)

    def as_summary(self) -> str:
        verb = "would_" if self.dry_run else ""
        return (
            f"dry_run={self.dry_run} records_inspected={self.records_inspected} "
            f"snapshots_missing={self.snapshots_missing} in_scope={self.in_scope} "
            f"out_of_scope={self.out_of_scope} validation_failed={self.validation_failed} "
            f"{verb}created={self.created} {verb}updated={self.updated} "
            f"{verb}unchanged={self.unchanged} failures={self.failures}"
        )


def _latest_snapshot(db: Session, source_record_id: int) -> SourceSnapshot | None:
    """Deterministic latest-snapshot selection: most recent `fetched_at`, tie-broken by
    the highest `id` (insertion order) so two snapshots sharing a `fetched_at` timestamp
    always resolve to the same row on every run."""
    return db.scalar(
        select(SourceSnapshot)
        .where(SourceSnapshot.source_record_id == source_record_id)
        .order_by(SourceSnapshot.fetched_at.desc(), SourceSnapshot.id.desc())
        .limit(1)
    )


def _reprocess_one(db: Session, record: SourceRecord, stats: ReprocessStats, *, dry_run: bool) -> None:
    snapshot = _latest_snapshot(db, record.id)
    if snapshot is None:
        stats.snapshots_missing += 1
        return

    classification = classify_fbi_record(snapshot.payload)
    if classification.outcome is not ClassificationOutcome.IN_SCOPE:
        stats.out_of_scope += 1
        return
    stats.in_scope += 1

    normalized = normalize_fbi_record(snapshot.payload)
    validation = validate_normalized_record(normalized)
    if not validation.valid:
        stats.validation_failed += 1
        logger.warning(
            "FBI SourceRecord id=%s external_id=%s failed canonical validation: %s",
            record.id,
            record.external_id,
            "; ".join(validation.errors),
        )
        return

    outcome: PersistOutcome
    try:
        with db.begin_nested():
            outcome = persist_normalized_record(db, record, normalized, link_method=FBI_LINK_METHOD)
            if dry_run:
                # Force a ROLLBACK TO SAVEPOINT of the write we just made, so dry-run
                # verifies "no canonical writes" at the transaction level rather than by
                # convention (e.g. "we just didn't call persist"). We still call the
                # real persist function so the created/updated/unchanged decision is
                # never duplicated.
                raise _DryRunRollback()
    except _DryRunRollback:
        pass

    if outcome is PersistOutcome.CREATED:
        stats.created += 1
    elif outcome is PersistOutcome.UPDATED:
        stats.updated += 1
    else:
        stats.unchanged += 1


def reprocess_fbi_source_records(db: Session, source: Source, *, dry_run: bool = True) -> ReprocessStats:
    """Reprocess every stored FBI `SourceRecord` for `source` through the canonical
    pipeline, using each record's latest stored `SourceSnapshot`. Never contacts the FBI
    API; never mutates `SourceRecord`/`SourceSnapshot` rows.

    `dry_run=True` (the default -- callers must opt into writing) computes exactly what
    live persistence would do, including actually running `persist_normalized_record`,
    but every write happens inside a SAVEPOINT that is rolled back before this function
    returns, so canonical tables (`Person`/`Case`/`CaseSource`) are left byte-for-byte
    unchanged regardless of what persistence logic does internally.

    A single record whose classification/normalization/persistence fails unexpectedly
    is recorded in `stats.failures` and does not abort the run, matching the failure
    isolation live ingestion already uses in
    `ingestion.sources.fbi.service._ingest_items`.

    The caller owns the session's outer commit/rollback in both modes (mirroring
    `run_fbi_ingestion`, which does not commit internally either). This function never
    calls `db.commit()` or a whole-session `db.rollback()` itself -- for `dry_run=True`,
    "zero canonical writes" is guaranteed per-record by the SAVEPOINT rollback above,
    not by rolling back the whole session, so this function is safe to call on a
    session that already holds other pending, unrelated work.
    """
    stats = ReprocessStats(dry_run=dry_run)
    records = db.scalars(
        select(SourceRecord).where(SourceRecord.source_id == source.id).order_by(SourceRecord.id)
    ).all()

    for record in records:
        stats.records_inspected += 1
        try:
            _reprocess_one(db, record, stats, dry_run=dry_run)
        except Exception as exc:  # noqa: BLE001 -- one bad record must not abort the run
            stats.failures += 1
            stats.errors.append(f"source_record_id={record.id} external_id={record.external_id}: {exc}")
            logger.warning(
                "Failed to reprocess FBI SourceRecord id=%s external_id=%s: %s",
                record.id,
                record.external_id,
                exc,
            )

    logger.info("FBI reprocessing run complete: %s", stats.as_summary())
    return stats
