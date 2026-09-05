from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.models.source import Source
from app.models.source_record import SourceRecord
from app.models.source_snapshot import SourceSnapshot
from ingestion.sources.fbi.classifier import (
    FBI_POSTER_CLASSIFICATION_MISSING,
    FBI_SUBJECT_VICAP_MISSING_PERSONS,
    FBI_VICAP_UNIDENTIFIED_OUT_OF_SCOPE,
)
from ingestion.sources.fbi.classifier_report import build_classifier_report

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


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


def _add_record(db_session, source, external_id, payload):
    record = SourceRecord(
        source_id=source.id,
        external_id=external_id,
        source_url=f"https://www.fbi.gov/wanted/kidnap/{external_id}",
        payload_hash="irrelevant-for-this-test",
        active=True,
    )
    db_session.add(record)
    db_session.flush()
    db_session.add(
        SourceSnapshot(
            source_record_id=record.id,
            payload=payload,
            payload_hash="irrelevant-for-this-test",
            fetched_at=NOW,
        )
    )
    db_session.flush()


def test_build_classifier_report_aggregates_correctly(db_session, fbi_source):
    _add_record(db_session, fbi_source, "r1", {"poster_classification": "missing"})
    _add_record(db_session, fbi_source, "r2", {"subjects": ["ViCAP Missing Persons"]})
    _add_record(db_session, fbi_source, "r3", {"subjects": ["ViCAP Unidentified Persons"]})
    _add_record(db_session, fbi_source, "r4", {"poster_classification": "totally-new-value"})
    db_session.commit()

    report = build_classifier_report(db_session, fbi_source)

    assert report.total_records == 4
    assert report.outcome_counts["IN_SCOPE"] == 2
    assert report.outcome_counts["OUT_OF_SCOPE"] == 1
    assert report.outcome_counts["UNCLASSIFIED"] == 1
    assert report.record_type_counts["MISSING_PERSON"] == 2
    assert report.record_type_counts["OTHER"] == 1
    assert report.record_type_counts["UNKNOWN"] == 1
    assert report.reason_code_counts[FBI_POSTER_CLASSIFICATION_MISSING] == 1
    assert report.reason_code_counts[FBI_SUBJECT_VICAP_MISSING_PERSONS] == 1
    assert report.reason_code_counts[FBI_VICAP_UNIDENTIFIED_OUT_OF_SCOPE] == 1


def test_build_classifier_report_does_not_write_anything(db_session, fbi_source):
    _add_record(db_session, fbi_source, "r1", {"poster_classification": "missing"})
    db_session.commit()

    before = db_session.execute(select(func.count()).select_from(SourceSnapshot)).scalar_one()

    build_classifier_report(db_session, fbi_source)
    db_session.commit()

    after = db_session.execute(select(func.count()).select_from(SourceSnapshot)).scalar_one()

    assert before == after
