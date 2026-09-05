from datetime import datetime, timezone

import pytest

from app.models.source import Source
from app.models.source_record import SourceRecord
from app.models.source_snapshot import SourceSnapshot
from ingestion.sources.fbi.normalization_report import (
    build_normalization_report,
    field_structural_report,
    get_in_scope_payloads,
    investigate_agency_fields,
    investigate_dob_field,
    investigate_location_fields,
    investigate_multi_person_signal,
    investigate_name_fields,
    render_normalization_report,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


# ----------------------------------------------------------------------------------
# field_structural_report
# ----------------------------------------------------------------------------------


def test_field_structural_report_counts_present_null_empty_populated():
    payloads = [
        {"sex": "Male", "aliases": []},
        {"sex": None, "aliases": ["Johnny"]},
        {"aliases": []},  # sex key absent entirely
    ]

    report = field_structural_report(payloads)

    assert report["sex"].count_present == 2
    assert report["sex"].count_null == 1
    assert report["sex"].count_populated == 1
    assert report["sex"].total == 3
    assert report["sex"].percentage_populated == round(100 / 3, 1)

    assert report["aliases"].count_present == 3
    assert report["aliases"].count_empty == 2
    assert report["aliases"].count_populated == 1


def test_field_structural_report_records_observed_types():
    payloads = [{"age_min": 5}, {"age_min": None}, {"age_min": "unexpected-string"}]

    report = field_structural_report(payloads)

    assert set(report["age_min"].observed_types) == {"int", "NoneType", "str"}


def test_field_structural_report_never_exposes_raw_values():
    payloads = [{"title": "A REAL NAME SHOULD NOT APPEAR", "details": "SENSITIVE DETAILS"}]

    report = field_structural_report(payloads)
    rendered = repr(report)

    assert "A REAL NAME SHOULD NOT APPEAR" not in rendered
    assert "SENSITIVE DETAILS" not in rendered


# ----------------------------------------------------------------------------------
# name field investigation
# ----------------------------------------------------------------------------------


def test_name_investigation_reports_no_structured_components_when_absent():
    payloads = [{"title": "SOMEONE", "aliases": ["Alt Name"]}, {"title": "SOMEONE ELSE"}]

    result = investigate_name_fields(payloads)

    assert result.title_present_count == 2
    assert result.aliases_present_count == 1
    assert result.structured_name_fields_found == ()
    assert result.structured_name_components_available is False


def test_name_investigation_detects_structured_components_if_present():
    payloads = [{"title": "SOMEONE", "given_name": "Someone"}]

    result = investigate_name_fields(payloads)

    assert "given_name" in result.structured_name_fields_found
    assert result.structured_name_components_available is True


# ----------------------------------------------------------------------------------
# DOB investigation
# ----------------------------------------------------------------------------------


def test_dob_investigation_single_value_is_safe():
    payloads = [
        {"dates_of_birth_used": ["January 1, 2000"]},
        {"dates_of_birth_used": ["February 2, 1999"]},
        {"dates_of_birth_used": None},
    ]

    result = investigate_dob_field(payloads)

    assert result.null_or_absent_count == 1
    assert result.exactly_one_value_count == 2
    assert result.multiple_values_count == 0
    assert result.safe_to_accept_when_exactly_one is True
    assert result.format_matches_known_pattern == 2
    assert result.format_does_not_match_known_pattern == 0


def test_dob_investigation_multiple_values_marks_unsafe():
    payloads = [
        {"dates_of_birth_used": ["January 1, 2000", "January 1, 2001"]},
        {"dates_of_birth_used": ["February 2, 1999"]},
    ]

    result = investigate_dob_field(payloads)

    assert result.list_length_counts == {2: 1, 1: 1}
    assert result.multiple_values_count == 1
    assert result.exactly_one_value_count == 1
    assert result.safe_to_accept_when_exactly_one is False


def test_dob_investigation_reports_format_mismatches():
    payloads = [
        {"dates_of_birth_used": ["January 1, 2000"]},
        {"dates_of_birth_used": ["circa 1990s"]},
    ]

    result = investigate_dob_field(payloads)

    assert result.format_matches_known_pattern == 1
    assert result.format_does_not_match_known_pattern == 1


def test_dob_investigation_empty_list_counts_as_absent():
    payloads = [{"dates_of_birth_used": []}]

    result = investigate_dob_field(payloads)

    assert result.null_or_absent_count == 1
    assert result.list_length_counts == {}


def test_dob_investigation_never_returns_raw_date_strings():
    payloads = [{"dates_of_birth_used": ["SHOULD NOT LEAK, 2000"]}]

    result = investigate_dob_field(payloads)

    assert "SHOULD NOT LEAK" not in repr(result)


# ----------------------------------------------------------------------------------
# location field investigation
# ----------------------------------------------------------------------------------


def test_location_investigation_counts_non_empty_per_field():
    payloads = [
        {"place_of_birth": "Somewhere", "locations": None, "field_offices": ["honolulu"]},
        {"place_of_birth": None, "locations": None, "field_offices": []},
    ]

    result = investigate_location_fields(payloads)

    assert result.per_field_non_empty_counts["place_of_birth"] == 1
    assert result.per_field_non_empty_counts["locations"] == 0
    assert result.per_field_non_empty_counts["field_offices"] == 1


def test_location_investigation_never_returns_raw_values():
    payloads = [{"place_of_birth": "A SPECIFIC CITY THAT SHOULD NOT LEAK"}]

    result = investigate_location_fields(payloads)

    assert "SHOULD NOT LEAK" not in repr(result)


# ----------------------------------------------------------------------------------
# agency field investigation
# ----------------------------------------------------------------------------------


def test_agency_investigation_reports_ncic_and_field_offices():
    payloads = [{"ncic": "12345", "field_offices": ["honolulu"]}, {"ncic": None, "field_offices": None}]

    result = investigate_agency_fields(payloads)

    assert result.ncic_populated_count == 1
    assert result.field_offices_populated_count == 1
    assert result.dedicated_case_number_field_found is False


# ----------------------------------------------------------------------------------
# multi-person structural signal
# ----------------------------------------------------------------------------------


def test_multi_person_signal_counts_dob_and_image_shapes():
    payloads = [
        {"dates_of_birth_used": ["Jan 1, 2000", "Jan 1, 2001"], "images": [{}, {}]},
        {"dates_of_birth_used": ["Jan 1, 2000"], "images": [{}]},
        {"images": []},
    ]

    result = investigate_multi_person_signal(payloads)

    assert result.dob_multi_value_count == 1
    assert result.image_count_distribution == {0: 1, 1: 1, 2: 1}


# ----------------------------------------------------------------------------------
# DB-backed: only IN_SCOPE payloads are selected; full report renders safely
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


def _add_record(db_session, source, external_id, payload, active=True):
    record = SourceRecord(
        source_id=source.id,
        external_id=external_id,
        source_url=f"https://www.fbi.gov/wanted/kidnap/{external_id}",
        payload_hash="irrelevant-for-this-test",
        active=active,
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


def test_get_in_scope_payloads_filters_to_in_scope_only(db_session, fbi_source):
    _add_record(db_session, fbi_source, "in-1", {"poster_classification": "missing", "title": "X"})
    _add_record(db_session, fbi_source, "out-1", {"poster_classification": "fraudster", "title": "Y"})
    _add_record(db_session, fbi_source, "unclassified-1", {"poster_classification": "brand-new", "title": "Z"})
    db_session.commit()

    payloads = get_in_scope_payloads(db_session, fbi_source)

    assert len(payloads) == 1
    assert payloads[0]["title"] == "X"


def test_build_and_render_normalization_report_end_to_end(db_session, fbi_source):
    _add_record(
        db_session,
        fbi_source,
        "mp-1",
        {
            "poster_classification": "missing",
            "title": "A NAME THAT SHOULD NOT LEAK",
            "dates_of_birth_used": ["January 1, 2000"],
            "place_of_birth": "SHOULD NOT LEAK CITY",
            "details": "SHOULD NOT LEAK DETAILS",
            "images": [{}],
        },
    )
    db_session.commit()

    report = build_normalization_report(db_session, fbi_source)
    rendered = render_normalization_report(report)

    assert report.total_in_scope_records == 1
    assert "title" in report.field_stats
    assert "A NAME THAT SHOULD NOT LEAK" not in rendered
    assert "SHOULD NOT LEAK CITY" not in rendered
    assert "SHOULD NOT LEAK DETAILS" not in rendered


def test_build_normalization_report_does_not_write_anything(db_session, fbi_source):
    _add_record(db_session, fbi_source, "mp-1", {"poster_classification": "missing", "title": "X"})
    db_session.commit()

    from sqlalchemy import func, select

    before = db_session.execute(select(func.count()).select_from(SourceSnapshot)).scalar_one()
    build_normalization_report(db_session, fbi_source)
    db_session.commit()
    after = db_session.execute(select(func.count()).select_from(SourceSnapshot)).scalar_one()

    assert before == after
