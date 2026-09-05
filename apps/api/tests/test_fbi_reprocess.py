"""Tests for historical FBI reprocessing (`ingestion.sources.fbi.reprocess`): replaying
already-stored SourceSnapshots through classify -> normalize -> validate -> persist
without touching the FBI API or the live ingestion path. Raw ingestion / live canonical
wiring is already covered by test_fbi_service.py and test_fbi_canonical_ingestion.py and
is not re-tested here -- these tests build SourceRecord/SourceSnapshot fixtures directly
to simulate records collected before the canonical pipeline existed.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.case import Case
from app.models.case_source import CaseSource
from app.models.person import Person
from app.models.source import Source
from app.models.source_record import SourceRecord
from app.models.source_snapshot import SourceSnapshot
from ingestion.sources.fbi.reprocess import reprocess_fbi_source_records
from ingestion.sources.fbi.service import hash_payload


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


def _in_scope_item(uid: str = "m1", title: str = "JANE DOE", description: str = "Last seen near the river.") -> dict:
    return {
        "uid": uid,
        "url": f"https://www.fbi.gov/wanted/kidnap/{uid}",
        "modified": "2026-01-01T00:00:00+00:00",
        "title": title,
        "sex": "Female",
        "description": description,
        "dates_of_birth_used": ["January 1, 2000"],
        "poster_classification": "missing",
        "subjects": ["ViCAP Missing Persons"],
    }


def _out_of_scope_item(uid: str = "w1") -> dict:
    return {
        "uid": uid,
        "url": f"https://www.fbi.gov/wanted/fugitives/{uid}",
        "modified": "2026-01-01T00:00:00+00:00",
        "title": "JOHN SMITH",
        "poster_classification": "ten",
        "subjects": ["Ten Most Wanted Fugitives"],
    }


def _make_source_record(db_session, source: Source, external_id: str, *, active: bool = True) -> SourceRecord:
    now = datetime.now(timezone.utc)
    record = SourceRecord(
        source_id=source.id,
        external_id=external_id,
        source_url=f"https://www.fbi.gov/wanted/kidnap/{external_id}",
        first_seen_at=now,
        last_seen_at=now,
        payload_hash="placeholder",
        active=active,
    )
    db_session.add(record)
    db_session.flush()
    return record


def _add_snapshot(db_session, record: SourceRecord, payload: dict, *, fetched_at: datetime) -> SourceSnapshot:
    snapshot = SourceSnapshot(
        source_record_id=record.id,
        payload=payload,
        payload_hash=hash_payload(payload),
        fetched_at=fetched_at,
    )
    db_session.add(snapshot)
    db_session.flush()
    return snapshot


NOW = datetime.now(timezone.utc)


def test_historical_record_creates_canonical_person_case_and_link(db_session, fbi_source):
    record = _make_source_record(db_session, fbi_source, "hist-1")
    _add_snapshot(db_session, record, _in_scope_item(uid="hist-1"), fetched_at=NOW)

    stats = reprocess_fbi_source_records(db_session, fbi_source, dry_run=False)
    db_session.commit()

    assert stats.records_inspected == 1
    assert stats.in_scope == 1
    assert stats.created == 1
    person = db_session.query(Person).one()
    case = db_session.query(Case).one()
    link = db_session.query(CaseSource).one()
    assert person.display_name == "JANE DOE"
    assert link.source_record_id == record.id
    assert case.person_id == person.id


def test_already_canonical_record_reports_unchanged(db_session, fbi_source):
    record = _make_source_record(db_session, fbi_source, "hist-2")
    _add_snapshot(db_session, record, _in_scope_item(uid="hist-2"), fetched_at=NOW)

    reprocess_fbi_source_records(db_session, fbi_source, dry_run=False)
    db_session.commit()

    stats = reprocess_fbi_source_records(db_session, fbi_source, dry_run=False)
    db_session.commit()

    assert stats.created == 0
    assert stats.updated == 0
    assert stats.unchanged == 1
    assert db_session.query(Person).count() == 1
    assert db_session.query(Case).count() == 1
    assert db_session.query(CaseSource).count() == 1


def test_normalization_change_updates_same_canonical_record_not_a_new_one(db_session, fbi_source):
    record = _make_source_record(db_session, fbi_source, "hist-3")
    _add_snapshot(
        db_session, record, _in_scope_item(uid="hist-3", description="Original circumstances."), fetched_at=NOW
    )
    reprocess_fbi_source_records(db_session, fbi_source, dry_run=False)
    db_session.commit()

    original_person_id = db_session.query(Person).one().id
    original_case_id = db_session.query(Case).one().id

    # A later, changed snapshot for the *same* SourceRecord (e.g. the source updated
    # its listing) -- reprocessing must update the same Person/Case, not create a new one.
    _add_snapshot(
        db_session,
        record,
        _in_scope_item(uid="hist-3", description="Updated circumstances."),
        fetched_at=NOW + timedelta(hours=1),
    )
    stats = reprocess_fbi_source_records(db_session, fbi_source, dry_run=False)
    db_session.commit()

    assert stats.updated == 1
    assert stats.created == 0
    assert db_session.query(Person).count() == 1
    assert db_session.query(Case).count() == 1
    case = db_session.query(Case).one()
    assert case.id == original_case_id
    assert db_session.query(Person).one().id == original_person_id
    assert case.circumstances == "Updated circumstances."


def test_out_of_scope_record_is_skipped(db_session, fbi_source):
    record = _make_source_record(db_session, fbi_source, "hist-4")
    _add_snapshot(db_session, record, _out_of_scope_item(uid="hist-4"), fetched_at=NOW)

    stats = reprocess_fbi_source_records(db_session, fbi_source, dry_run=False)
    db_session.commit()

    assert stats.out_of_scope == 1
    assert stats.created == 0
    assert db_session.query(Person).count() == 0
    assert db_session.query(Case).count() == 0
    assert db_session.query(CaseSource).count() == 0


def test_malformed_record_fails_validation_without_aborting_batch(db_session, fbi_source):
    good = _make_source_record(db_session, fbi_source, "hist-good")
    _add_snapshot(db_session, good, _in_scope_item(uid="hist-good"), fetched_at=NOW)

    bad = _make_source_record(db_session, fbi_source, "hist-bad")
    _add_snapshot(db_session, bad, _in_scope_item(uid="hist-bad", title="   "), fetched_at=NOW)

    stats = reprocess_fbi_source_records(db_session, fbi_source, dry_run=False)
    db_session.commit()

    assert stats.records_inspected == 2
    assert stats.created == 1
    assert stats.validation_failed == 1
    assert db_session.query(Person).count() == 1


def test_record_with_no_snapshot_is_handled_safely(db_session, fbi_source):
    _make_source_record(db_session, fbi_source, "hist-no-snapshot")

    stats = reprocess_fbi_source_records(db_session, fbi_source, dry_run=False)
    db_session.commit()

    assert stats.records_inspected == 1
    assert stats.snapshots_missing == 1
    assert stats.failures == 0
    assert db_session.query(Person).count() == 0


def test_multiple_snapshots_selects_latest_by_fetched_at(db_session, fbi_source):
    record = _make_source_record(db_session, fbi_source, "hist-multi")
    _add_snapshot(
        db_session, record, _in_scope_item(uid="hist-multi", description="Oldest."), fetched_at=NOW - timedelta(days=2)
    )
    _add_snapshot(
        db_session, record, _in_scope_item(uid="hist-multi", description="Middle."), fetched_at=NOW - timedelta(days=1)
    )
    _add_snapshot(db_session, record, _in_scope_item(uid="hist-multi", description="Newest."), fetched_at=NOW)

    reprocess_fbi_source_records(db_session, fbi_source, dry_run=False)
    db_session.commit()

    case = db_session.query(Case).one()
    assert case.circumstances == "Newest."


def test_snapshots_with_identical_fetched_at_break_ties_deterministically(db_session, fbi_source):
    record = _make_source_record(db_session, fbi_source, "hist-tie")
    tie_time = NOW
    _add_snapshot(db_session, record, _in_scope_item(uid="hist-tie", description="First inserted."), fetched_at=tie_time)
    second = _add_snapshot(
        db_session, record, _in_scope_item(uid="hist-tie", description="Second inserted."), fetched_at=tie_time
    )
    assert second.fetched_at == tie_time  # sanity: genuinely tied timestamps

    stats_1 = reprocess_fbi_source_records(db_session, fbi_source, dry_run=False)
    db_session.commit()
    case = db_session.query(Case).one()

    # Re-running must resolve the same tie the same way every time (highest snapshot id
    # wins), so nothing flip-flops between runs.
    stats_2 = reprocess_fbi_source_records(db_session, fbi_source, dry_run=False)
    db_session.commit()

    assert case.circumstances == "Second inserted."
    assert stats_1.created == 1
    assert stats_2.updated == 0 and stats_2.unchanged == 1


def test_dry_run_makes_zero_canonical_database_writes(db_session, fbi_source):
    record = _make_source_record(db_session, fbi_source, "hist-dry")
    _add_snapshot(db_session, record, _in_scope_item(uid="hist-dry"), fetched_at=NOW)

    stats = reprocess_fbi_source_records(db_session, fbi_source, dry_run=True)

    assert stats.in_scope == 1
    assert stats.created == 1  # reports what WOULD happen
    # Verified at the transaction level: the SAVEPOINT that made this write was rolled
    # back inside reprocess_fbi_source_records, so nothing is visible even without an
    # explicit commit/rollback here.
    assert db_session.query(Person).count() == 0
    assert db_session.query(Case).count() == 0
    assert db_session.query(CaseSource).count() == 0
    assert db_session.query(SourceRecord).count() == 1  # raw layer untouched
    assert db_session.query(SourceSnapshot).count() == 1


def test_dry_run_against_mixed_data_reports_all_counters_without_writing(db_session, fbi_source):
    in_scope_record = _make_source_record(db_session, fbi_source, "mix-in-scope")
    _add_snapshot(db_session, in_scope_record, _in_scope_item(uid="mix-in-scope"), fetched_at=NOW)

    out_of_scope_record = _make_source_record(db_session, fbi_source, "mix-out-of-scope")
    _add_snapshot(db_session, out_of_scope_record, _out_of_scope_item(uid="mix-out-of-scope"), fetched_at=NOW)

    bad_record = _make_source_record(db_session, fbi_source, "mix-bad")
    _add_snapshot(db_session, bad_record, _in_scope_item(uid="mix-bad", title="   "), fetched_at=NOW)

    no_snapshot_record = _make_source_record(db_session, fbi_source, "mix-no-snapshot")

    stats = reprocess_fbi_source_records(db_session, fbi_source, dry_run=True)

    assert stats.records_inspected == 4
    # "mix-bad" IS classified IN_SCOPE (classification looks at poster_classification /
    # subjects, not title) -- it separately fails validation for its blank title.
    assert stats.in_scope == 2
    assert stats.out_of_scope == 1
    assert stats.validation_failed == 1
    assert stats.snapshots_missing == 1
    assert stats.created == 1
    assert db_session.query(Person).count() == 0
    assert db_session.query(Case).count() == 0
    assert db_session.query(CaseSource).count() == 0


def test_reprocessing_maps_physical_detail_fields_and_stays_idempotent(db_session, fbi_source):
    item = _in_scope_item(uid="hist-physical")
    item.update(
        hair="black",
        hair_raw="Black (shoulder length)",
        eyes="brown",
        eyes_raw="Brown",
        aliases=["Johnny", "J.D."],
        scars_and_marks="Scar on left forearm.",
    )
    record = _make_source_record(db_session, fbi_source, "hist-physical")
    _add_snapshot(db_session, record, item, fetched_at=NOW)

    first = reprocess_fbi_source_records(db_session, fbi_source, dry_run=False)
    db_session.commit()

    assert first.created == 1
    person = db_session.query(Person).one()
    link = db_session.query(CaseSource).one()
    assert person.hair_color == "Black (shoulder length)"
    assert person.eye_color == "Brown"
    assert person.aliases == ["Johnny", "J.D."]
    assert person.distinguishing_characteristics == "Scar on left forearm."
    assert link.contributed_fields["hair_color"] == "Black (shoulder length)"
    assert link.contributed_fields["eye_color"] == "Brown"
    assert link.contributed_fields["aliases"] == ["Johnny", "J.D."]
    assert link.contributed_fields["distinguishing_characteristics"] == "Scar on left forearm."

    second = reprocess_fbi_source_records(db_session, fbi_source, dry_run=False)
    db_session.commit()

    assert second.created == 0
    assert second.updated == 0
    assert second.unchanged == 1
    assert db_session.query(Person).count() == 1
    assert db_session.query(Case).count() == 1
    assert db_session.query(CaseSource).count() == 1


def test_actual_backfill_then_second_run_is_idempotent(db_session, fbi_source):
    for i in range(5):
        record = _make_source_record(db_session, fbi_source, f"idem-{i}")
        _add_snapshot(db_session, record, _in_scope_item(uid=f"idem-{i}"), fetched_at=NOW)
    _make_source_record(db_session, fbi_source, "idem-out-of-scope")
    _add_snapshot(
        db_session,
        db_session.query(SourceRecord).filter_by(external_id="idem-out-of-scope").one(),
        _out_of_scope_item(uid="idem-out-of-scope"),
        fetched_at=NOW,
    )

    first = reprocess_fbi_source_records(db_session, fbi_source, dry_run=False)
    db_session.commit()

    assert first.created == 5
    assert first.out_of_scope == 1
    person_count = db_session.query(Person).count()
    case_count = db_session.query(Case).count()
    link_count = db_session.query(CaseSource).count()
    assert (person_count, case_count, link_count) == (5, 5, 5)

    second = reprocess_fbi_source_records(db_session, fbi_source, dry_run=False)
    db_session.commit()

    assert second.created == 0
    assert second.updated == 0
    assert second.unchanged == 5
    assert db_session.query(Person).count() == person_count
    assert db_session.query(Case).count() == case_count
    assert db_session.query(CaseSource).count() == link_count
