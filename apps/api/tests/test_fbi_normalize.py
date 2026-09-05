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
        "age",
        "height_cm",
        "weight_kg",
        "photo_urls",
    ):
        assert field_name not in record.person_fields


# --- hair_color (from hair_raw, never the FBI-normalized `hair` bucket) -------------


def test_normalize_maps_hair_raw_verbatim_to_hair_color():
    record = normalize_fbi_record(_item(hair="black", hair_raw="Black (shoulder length)"))
    assert record.person_fields["hair_color"] == "Black (shoulder length)"


def test_normalize_richer_hair_raw_value_is_not_collapsed_to_controlled_vocabulary():
    """`hair` (FBI's own bucketed value) and `hair_raw` (fuller source text) can differ
    -- normalization must preserve the fuller `hair_raw` text, not fall back to or
    collapse onto the shorter controlled-vocabulary `hair` value."""
    record = normalize_fbi_record(
        _item(hair="brown", hair_raw="Brown, Curly, dyed red at the tips")
    )
    assert record.person_fields["hair_color"] == "Brown, Curly, dyed red at the tips"
    assert record.person_fields["hair_color"] != "brown"


def test_normalize_hair_raw_blank_is_none():
    record = normalize_fbi_record(_item(hair="black", hair_raw="   "))
    assert record.person_fields["hair_color"] is None


def test_normalize_hair_raw_absent_is_none_even_when_hair_is_present():
    """The controlled-vocabulary `hair` field must never be used as a fallback."""
    item = _item(hair="black")
    record = normalize_fbi_record(item)
    assert record.person_fields["hair_color"] is None


# --- eye_color (from eyes_raw, never the FBI-normalized `eyes` bucket) -------------


def test_normalize_maps_eyes_raw_verbatim_to_eye_color():
    record = normalize_fbi_record(_item(eyes="blue", eyes_raw="Blue, wears glasses"))
    assert record.person_fields["eye_color"] == "Blue, wears glasses"


def test_normalize_richer_eyes_raw_value_is_not_collapsed_to_controlled_vocabulary():
    record = normalize_fbi_record(_item(eyes="hazel", eyes_raw="Green/Hazel"))
    assert record.person_fields["eye_color"] == "Green/Hazel"
    assert record.person_fields["eye_color"] != "hazel"


def test_normalize_eyes_raw_blank_is_none():
    record = normalize_fbi_record(_item(eyes="blue", eyes_raw=""))
    assert record.person_fields["eye_color"] is None


def test_normalize_eyes_raw_absent_is_none_even_when_eyes_is_present():
    item = _item(eyes="blue")
    record = normalize_fbi_record(item)
    assert record.person_fields["eye_color"] is None


# --- aliases (deterministic list[str] copy) -----------------------------------------


def test_normalize_aliases_list_copied_verbatim():
    record = normalize_fbi_record(_item(aliases=["Johnny", "J.D."]))
    assert record.person_fields["aliases"] == ["Johnny", "J.D."]


def test_normalize_aliases_absent_is_none():
    record = normalize_fbi_record(_item())
    assert record.person_fields["aliases"] is None


def test_normalize_aliases_empty_list_is_none():
    record = normalize_fbi_record(_item(aliases=[]))
    assert record.person_fields["aliases"] is None


def test_normalize_aliases_with_non_string_element_fails_closed_to_none():
    record = normalize_fbi_record(_item(aliases=["Johnny", 123]))
    assert record.person_fields["aliases"] is None


# --- distinguishing_characteristics (from scars_and_marks) --------------------------


def test_normalize_scars_and_marks_verbatim_to_distinguishing_characteristics():
    record = normalize_fbi_record(_item(scars_and_marks="Scar on left forearm."))
    assert record.person_fields["distinguishing_characteristics"] == "Scar on left forearm."


def test_normalize_scars_and_marks_blank_is_none():
    record = normalize_fbi_record(_item(scars_and_marks="   "))
    assert record.person_fields["distinguishing_characteristics"] is None


def test_normalize_scars_and_marks_absent_is_none():
    record = normalize_fbi_record(_item())
    assert record.person_fields["distinguishing_characteristics"] is None


def test_normalize_new_fields_remain_none_when_source_fields_absent():
    """No new mapping should ever fabricate a value when its source field is missing."""
    record = normalize_fbi_record(_item())
    assert record.person_fields["hair_color"] is None
    assert record.person_fields["eye_color"] is None
    assert record.person_fields["aliases"] is None
    assert record.person_fields["distinguishing_characteristics"] is None
