from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.models.source import Source
from app.models.source_record import SourceRecord
from app.models.source_snapshot import SourceSnapshot
from ingestion.sources.fbi.classification_report import (
    MISSING_PERSONS_SUBJECT,
    analyze_combinations,
    analyze_scalar_field,
    analyze_subjects_shape,
    analyze_subjects_values,
    build_classification_report,
    count_missing_persons_subject,
    field_presence_and_types,
    get_latest_snapshots,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


# ----------------------------------------------------------------------------------
# subjects shape: list / null / empty / missing key / non-list / multi-valued
# ----------------------------------------------------------------------------------


def test_subjects_shape_handles_all_observed_variants():
    payloads = [
        {"subjects": ["Kidnappings and Missing Persons"]},  # single-value list
        {"subjects": ["Seeking Information", "Kidnappings and Missing Persons"]},  # multi-value
        {"subjects": None},  # null
        {"subjects": []},  # empty list
        {"other_field": "x"},  # subjects key missing entirely
        {"subjects": "Kidnappings and Missing Persons"},  # unexpected non-list type
    ]

    shape = analyze_subjects_shape(payloads)

    assert shape.total == 6
    assert shape.single_value_count == 1
    assert shape.multi_value_count == 1
    assert shape.null_count == 1
    assert shape.empty_list_count == 1
    assert shape.missing_key_count == 1
    assert shape.non_list_type_count == 1
    assert shape.max_len == 2
    assert shape.can_be_multi_valued is True
    # A non-list value was observed, so "always a list" must be False.
    assert shape.always_list_when_present is False


def test_subjects_shape_reports_always_list_when_no_non_list_values_seen():
    payloads = [
        {"subjects": ["A"]},
        {"subjects": ["A", "B"]},
        {"subjects": None},
    ]

    shape = analyze_subjects_shape(payloads)

    assert shape.non_list_type_count == 0
    assert shape.always_list_when_present is True


def test_analyze_subjects_values_counts_each_label_once_per_record():
    payloads = [
        {"subjects": ["A", "A", "B"]},  # duplicate label within one record counts once
        {"subjects": ["A"]},
        {"subjects": None},
        {"subjects": "not-a-list"},
    ]

    counts = analyze_subjects_values(payloads)

    assert counts["A"] == 2
    assert counts["B"] == 1


def test_count_missing_persons_subject_ignores_null_and_non_list():
    payloads = [
        {"subjects": [MISSING_PERSONS_SUBJECT]},
        {"subjects": ["Seeking Information", MISSING_PERSONS_SUBJECT]},
        {"subjects": ["Seeking Information"]},
        {"subjects": None},
        {"subjects": MISSING_PERSONS_SUBJECT},  # non-list -- must not false-positive
    ]

    assert count_missing_persons_subject(payloads) == 2


# ----------------------------------------------------------------------------------
# scalar field / combination / presence-and-type analysis
# ----------------------------------------------------------------------------------


def test_analyze_scalar_field_counts_values_and_treats_blank_and_null_as_missing():
    payloads = [
        {"status": "na"},
        {"status": "na"},
        {"status": "captured"},
        {"status": None},
        {"status": ""},
        {"other": 1},  # key absent
    ]

    report = analyze_scalar_field(payloads, "status")

    assert report.present_count == 3
    assert report.missing_count == 3
    assert report.value_counts["na"] == 2
    assert report.value_counts["captured"] == 1


def test_analyze_combinations_labels_missing_values_with_sentinel():
    payloads = [
        {"poster_classification": "missing", "person_classification": "Main", "status": "na"},
        {"poster_classification": "missing", "person_classification": "Main", "status": "na"},
        {"poster_classification": None, "person_classification": "Main", "status": "na"},
    ]

    combos = analyze_combinations(payloads)

    assert combos[("missing", "Main", "na")] == 2
    assert combos[("<missing>", "Main", "na")] == 1


def test_field_presence_and_types_never_captures_values_only_structure():
    payloads = [
        {"age_min": 5, "title": "SHOULD NOT APPEAR"},
        {"age_min": None, "title": "ALSO SHOULD NOT APPEAR"},
        {"title": "STILL SHOULD NOT APPEAR"},  # age_min key absent
    ]

    presence = field_presence_and_types(payloads)

    assert presence["age_min"].key_present_count == 2
    assert presence["age_min"].non_null_count == 1
    assert presence["age_min"].observed_types == ("int",)
    assert presence["title"].key_present_count == 3
    assert presence["title"].non_null_count == 3
    assert presence["title"].observed_types == ("str",)
    # Structural report must never contain the raw string values themselves.
    rendered = repr(presence)
    assert "SHOULD NOT APPEAR" not in rendered


# ----------------------------------------------------------------------------------
# DB-backed: latest-snapshot selection and end-to-end report assembly
# ----------------------------------------------------------------------------------


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


def _add_record_with_snapshots(db_session, source, external_id, payloads, active=True):
    record = SourceRecord(
        source_id=source.id,
        external_id=external_id,
        source_url=f"https://www.fbi.gov/wanted/kidnap/{external_id}",
        payload_hash="irrelevant-for-this-test",
        active=active,
    )
    db_session.add(record)
    db_session.flush()
    for i, payload in enumerate(payloads):
        db_session.add(
            SourceSnapshot(
                source_record_id=record.id,
                payload=payload,
                payload_hash=f"hash-{external_id}-{i}",
                fetched_at=NOW + timedelta(hours=i),
            )
        )
    db_session.flush()
    return record


def test_get_latest_snapshots_returns_only_the_newest_per_active_record(db_session, fbi_source):
    _add_record_with_snapshots(
        db_session,
        fbi_source,
        "rec-a",
        [{"title": "old"}, {"title": "new"}],
    )
    _add_record_with_snapshots(db_session, fbi_source, "rec-b", [{"title": "only"}])
    _add_record_with_snapshots(
        db_session, fbi_source, "rec-inactive", [{"title": "should not appear"}], active=False
    )
    db_session.commit()

    snapshots = get_latest_snapshots(db_session, fbi_source)

    payload_titles = {s.payload["title"] for s in snapshots}
    assert payload_titles == {"new", "only"}


def test_build_classification_report_end_to_end(db_session, fbi_source):
    _add_record_with_snapshots(
        db_session,
        fbi_source,
        "mp-1",
        [
            {
                "subjects": [MISSING_PERSONS_SUBJECT],
                "poster_classification": "missing",
                "person_classification": "Main",
                "status": "na",
            }
        ],
    )
    _add_record_with_snapshots(
        db_session,
        fbi_source,
        "mp-2",
        [
            {
                "subjects": ["Seeking Information", MISSING_PERSONS_SUBJECT],
                "poster_classification": "missing",
                "person_classification": "Victim",
                "status": "na",
            }
        ],
    )
    _add_record_with_snapshots(
        db_session,
        fbi_source,
        "other-1",
        [
            {
                "subjects": ["Most Wanted Fraudster"],
                "poster_classification": "fraudster",
                "person_classification": "Main",
                "status": "na",
            }
        ],
    )
    db_session.commit()

    report = build_classification_report(db_session, fbi_source)

    assert report.total_records == 3
    assert report.missing_persons_subject_count == 2
    assert report.subjects_value_counts[MISSING_PERSONS_SUBJECT] == 2
    assert report.subjects_value_counts["Most Wanted Fraudster"] == 1
    assert report.missing_persons_subset.total_records == 2
    assert report.missing_persons_subset.poster_classification.value_counts["missing"] == 2
    assert report.missing_persons_subset.person_classification.value_counts["Main"] == 1
    assert report.missing_persons_subset.person_classification.value_counts["Victim"] == 1


def test_build_classification_report_does_not_write_anything(db_session, fbi_source):
    _add_record_with_snapshots(
        db_session, fbi_source, "readonly-1", [{"subjects": [MISSING_PERSONS_SUBJECT]}]
    )
    db_session.commit()

    before = db_session.execute(select(func.count()).select_from(SourceSnapshot)).scalar_one()

    build_classification_report(db_session, fbi_source)
    db_session.commit()

    after = db_session.execute(select(func.count()).select_from(SourceSnapshot)).scalar_one()

    assert before == after
