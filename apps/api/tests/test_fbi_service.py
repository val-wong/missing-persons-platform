from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.source import Source
from app.models.source_record import SourceRecord
from app.models.source_snapshot import SourceSnapshot
from ingestion.sources.fbi.client import FBIApiError, FBIListResponse
from ingestion.sources.fbi.service import (
    IngestOutcome,
    hash_payload,
    ingest_item,
    run_fbi_ingestion,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
LATER = NOW + timedelta(hours=1)


def _fbi_item(uid: str = "abc123", title: str = "SAMPLE SUBJECT", modified: str = "2026-01-01T00:00:00+00:00") -> dict:
    return {
        "uid": uid,
        "url": f"https://www.fbi.gov/wanted/kidnap/{uid}",
        "modified": modified,
        "title": title,
        "status": "na",
    }


@pytest.fixture()
def fbi_source(db_session) -> Source:
    source = Source(
        code="fbi",
        name="Federal Bureau of Investigation",
        base_url="https://api.fbi.gov",
        source_type="government_agency",
    )
    db_session.add(source)
    db_session.flush()
    return source


class FakeFBIClient:
    """Test double standing in for FBIApiClient: yields pre-built pages, can fail mid-run."""

    def __init__(self, pages: list[FBIListResponse], fail_at_page: int | None = None):
        self._pages = pages
        self._fail_at_page = fail_at_page

    def iter_pages(self, start_page: int = 1, page_size: int = 20, max_pages: int | None = None):
        yielded = 0
        for index, page in enumerate(self._pages, start=1):
            if max_pages is not None and yielded >= max_pages:
                return
            if self._fail_at_page == index:
                raise FBIApiError(f"simulated failure fetching page {index}")
            yield page
            yielded += 1


def test_ingest_item_creates_new_record_and_snapshot(db_session, fbi_source):
    item = _fbi_item()

    outcome = ingest_item(db_session, fbi_source, item, NOW)
    db_session.commit()

    assert outcome is IngestOutcome.NEW
    record = db_session.scalar(select(SourceRecord).where(SourceRecord.external_id == "abc123"))
    assert record is not None
    assert record.source_url == item["url"]
    assert record.payload_hash == hash_payload(item)
    assert record.active is True
    assert record.first_seen_at == NOW
    assert record.last_seen_at == NOW

    snapshots = db_session.scalars(
        select(SourceSnapshot).where(SourceSnapshot.source_record_id == record.id)
    ).all()
    assert len(snapshots) == 1
    assert snapshots[0].payload["title"] == "SAMPLE SUBJECT"
    assert snapshots[0].payload_hash == hash_payload(item)


def test_ingesting_unchanged_payload_twice_does_not_duplicate_snapshot(db_session, fbi_source):
    item = _fbi_item()

    first_outcome = ingest_item(db_session, fbi_source, item, NOW)
    db_session.commit()
    second_outcome = ingest_item(db_session, fbi_source, dict(item), LATER)
    db_session.commit()

    assert first_outcome is IngestOutcome.NEW
    assert second_outcome is IngestOutcome.UNCHANGED

    record = db_session.scalar(select(SourceRecord).where(SourceRecord.external_id == "abc123"))
    assert record.last_seen_at == LATER
    assert record.first_seen_at == NOW  # unchanged

    snapshots = db_session.scalars(
        select(SourceSnapshot).where(SourceSnapshot.source_record_id == record.id)
    ).all()
    assert len(snapshots) == 1


def test_changed_payload_creates_new_snapshot_and_preserves_old_one(db_session, fbi_source):
    original = _fbi_item(title="ORIGINAL TITLE")
    ingest_item(db_session, fbi_source, original, NOW)
    db_session.commit()

    changed = _fbi_item(title="UPDATED TITLE", modified="2026-01-02T00:00:00+00:00")
    outcome = ingest_item(db_session, fbi_source, changed, LATER)
    db_session.commit()

    assert outcome is IngestOutcome.CHANGED

    record = db_session.scalar(select(SourceRecord).where(SourceRecord.external_id == "abc123"))
    assert record.payload_hash == hash_payload(changed)
    assert record.last_seen_at == LATER

    snapshots = db_session.scalars(
        select(SourceSnapshot)
        .where(SourceSnapshot.source_record_id == record.id)
        .order_by(SourceSnapshot.fetched_at)
    ).all()
    assert len(snapshots) == 2
    assert snapshots[0].payload["title"] == "ORIGINAL TITLE"
    assert snapshots[1].payload["title"] == "UPDATED TITLE"


def test_source_record_uniqueness_enforced_at_db_level(db_session, fbi_source):
    db_session.add(
        SourceRecord(
            source_id=fbi_source.id,
            external_id="dup-id",
            source_url="https://www.fbi.gov/wanted/kidnap/dup-id",
            payload_hash="hash1",
        )
    )
    db_session.commit()

    db_session.add(
        SourceRecord(
            source_id=fbi_source.id,
            external_id="dup-id",
            source_url="https://www.fbi.gov/wanted/kidnap/dup-id",
            payload_hash="hash2",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_item_missing_uid_is_skipped_without_aborting_the_batch(db_session, fbi_source):
    good_item = _fbi_item(uid="good-1")
    bad_item = {"url": "https://www.fbi.gov/wanted/kidnap/no-uid", "title": "NO UID"}
    page = FBIListResponse(total=2, page=1, items=[good_item, bad_item])
    client = FakeFBIClient(pages=[page])

    stats = run_fbi_ingestion(db_session, client, max_pages=1)

    assert stats.items_received == 2
    assert stats.records_new == 1
    assert stats.failures == 1
    record = db_session.scalar(select(SourceRecord).where(SourceRecord.external_id == "good-1"))
    assert record is not None


def test_page_fetch_failure_does_not_corrupt_previously_ingested_pages(db_session, fbi_source):
    page1 = FBIListResponse(total=4, page=1, items=[_fbi_item("p1-a"), _fbi_item("p1-b")])
    page2 = FBIListResponse(total=4, page=2, items=[_fbi_item("p2-a"), _fbi_item("p2-b")])
    client = FakeFBIClient(pages=[page1, page2], fail_at_page=2)

    stats = run_fbi_ingestion(db_session, client, max_pages=None)

    assert stats.pages_fetched == 1
    assert stats.records_new == 2
    assert stats.failures == 1

    records = db_session.scalars(
        select(SourceRecord).where(SourceRecord.source_id == fbi_source.id)
    ).all()
    assert {r.external_id for r in records} == {"p1-a", "p1-b"}


def test_run_fbi_ingestion_aggregates_across_multiple_pages(db_session, fbi_source):
    page1 = FBIListResponse(total=4, page=1, items=[_fbi_item("m1"), _fbi_item("m2")])
    page2 = FBIListResponse(total=4, page=2, items=[_fbi_item("m3"), _fbi_item("m4")])
    client = FakeFBIClient(pages=[page1, page2])

    stats = run_fbi_ingestion(db_session, client, max_pages=None)

    assert stats.pages_fetched == 2
    assert stats.items_received == 4
    assert stats.records_new == 4
    assert stats.snapshots_created == 4

    records = db_session.scalars(
        select(SourceRecord).where(SourceRecord.source_id == fbi_source.id)
    ).all()
    assert len(records) == 4


def test_run_fbi_ingestion_respects_max_pages(db_session, fbi_source):
    page1 = FBIListResponse(total=4, page=1, items=[_fbi_item("x1")])
    page2 = FBIListResponse(total=4, page=2, items=[_fbi_item("x2")])
    client = FakeFBIClient(pages=[page1, page2])

    stats = run_fbi_ingestion(db_session, client, max_pages=1)

    assert stats.pages_fetched == 1
    assert stats.records_new == 1
