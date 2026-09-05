from datetime import date

from ingestion.sources.fbi.normalize import FBI_INVESTIGATING_AGENCY, normalize_fbi_record


def _item(**overrides) -> dict:
    base = {
        "uid": "abc123",
        "url": "https://www.fbi.gov/wanted/kidnap/abc123",
        "title": "JANE DOE",
        "sex": "Female",
        "description": "Jane was last seen wearing a red jacket.",
        "dates_of_birth_used": ["January 1, 2000"],
    }
    base.update(overrides)
    return base


def test_normalize_maps_safe_direct_fields():
    record = normalize_fbi_record(_item())

    assert record.person_fields["display_name"] == "JANE DOE"
    assert record.person_fields["sex"] == "Female"
    assert record.person_fields["date_of_birth"] == date(2000, 1, 1)
    assert record.case_fields["circumstances"] == "Jane was last seen wearing a red jacket."
    assert record.case_fields["investigating_agency"] == FBI_INVESTIGATING_AGENCY


def test_normalize_blank_title_yields_none_not_empty_string():
    record = normalize_fbi_record(_item(title="   "))
    assert record.person_fields["display_name"] is None


def test_normalize_missing_sex_and_description_are_none():
    item = _item()
    del item["sex"]
    del item["description"]
    record = normalize_fbi_record(item)
    assert record.person_fields["sex"] is None
    assert record.case_fields["circumstances"] is None


def test_normalize_dob_fails_closed_on_multiple_entries():
    record = normalize_fbi_record(
        _item(dates_of_birth_used=["January 1, 2000", "January 1, 2001"])
    )
    assert record.person_fields["date_of_birth"] is None


def test_normalize_dob_fails_closed_on_unrecognized_format():
    record = normalize_fbi_record(_item(dates_of_birth_used=["01/01/2000"]))
    assert record.person_fields["date_of_birth"] is None


def test_normalize_dob_absent_is_none():
    item = _item()
    del item["dates_of_birth_used"]
    record = normalize_fbi_record(item)
    assert record.person_fields["date_of_birth"] is None


def test_investigating_agency_is_constant_regardless_of_item_content():
    record = normalize_fbi_record(_item(title="ANYONE ELSE"))
    assert record.case_fields["investigating_agency"] == "Federal Bureau of Investigation"


def test_normalize_never_maps_fields_not_yet_evidenced_as_safe():
    """Per docs/fbi-normalization.md, these stay unmapped (NULL) for Phase 1 -- this
    test exists so a future edit accidentally adding one of them has to consciously
    delete this assertion, not just miss it."""
    record = normalize_fbi_record(_item())
    for field_name in (
        "missing_date",
        "missing_city",
        "missing_county",
        "missing_state",
        "missing_country",
        "case_status",
        "agency_case_number",
        "age_at_missing",
    ):
        assert field_name not in record.case_fields
    for field_name in (
        "given_name",
        "middle_name",
        "family_name",
        "suffix",
        "aliases",
        "age",
        "height_cm",
        "weight_kg",
        "hair_color",
        "eye_color",
        "distinguishing_characteristics",
        "photo_urls",
    ):
        assert field_name not in record.person_fields
