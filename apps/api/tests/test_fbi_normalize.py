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
    assert record.person_fields["height_min_cm"] is None
    assert record.person_fields["height_max_cm"] is None
    assert record.person_fields["weight_min_kg"] is None
    assert record.person_fields["weight_max_kg"] is None
    assert record.person_fields["weight_raw"] is None
    assert record.person_fields["weight_temporal_context"] is None
    assert record.person_fields["photos"] is None


# --- height (inches -> cm, range-preserving; no raw/temporal_context for FBI) -------


def test_normalize_height_point_value_converts_inches_to_cm():
    record = normalize_fbi_record(_item(height_min=66, height_max=66))
    assert record.person_fields["height_min_cm"] == 167.6
    assert record.person_fields["height_max_cm"] == 167.6
    assert record.person_fields["height_min_cm"] == record.person_fields["height_max_cm"]


def test_normalize_height_range_preserves_both_endpoints_without_collapsing():
    record = normalize_fbi_record(_item(height_min=64, height_max=65))
    assert record.person_fields["height_min_cm"] == 162.6
    assert record.person_fields["height_max_cm"] == 165.1
    assert record.person_fields["height_min_cm"] != record.person_fields["height_max_cm"]


def test_normalize_height_uses_exact_2_54_conversion_constant():
    # 1 inch = 2.54 cm exactly; a value chosen so any rounding-constant drift would show.
    record = normalize_fbi_record(_item(height_min=58, height_max=58))
    assert record.person_fields["height_min_cm"] == 147.3  # 58 * 2.54 = 147.32 -> 147.3


def test_normalize_height_stores_one_decimal_place_precision():
    record = normalize_fbi_record(_item(height_min=59, height_max=59))
    # 59 * 2.54 = 149.86 -> rounds to 149.9, not truncated or stored at full precision.
    assert record.person_fields["height_min_cm"] == 149.9


def test_normalize_height_missing_fields_are_none():
    record = normalize_fbi_record(_item())
    assert record.person_fields["height_min_cm"] is None
    assert record.person_fields["height_max_cm"] is None

    record2 = normalize_fbi_record(_item(height_min=66))  # height_max absent
    assert record2.person_fields["height_min_cm"] is None
    assert record2.person_fields["height_max_cm"] is None


def test_normalize_height_malformed_numeric_fields_fail_closed():
    """height_min/height_max as non-int must never be guessed at -- both endpoints are
    refused together, mirroring weight's convention."""
    record = normalize_fbi_record(_item(height_min="66", height_max=66))
    assert record.person_fields["height_min_cm"] is None
    assert record.person_fields["height_max_cm"] is None


def test_normalize_height_outliers_are_preserved_not_rejected():
    """No plausibility threshold -- an implausible-looking value is still converted and
    preserved, per docs/fbi-normalization.md."""
    record = normalize_fbi_record(_item(height_min=96, height_max=96))
    assert record.person_fields["height_min_cm"] == 243.8


def test_normalize_height_raw_is_always_absent_for_fbi():
    """Absent, not merely None -- FBI has no free-text height field to copy from, so
    `persist_normalized_record` never touches `Person.height_raw` at all, leaving any
    existing value (or the column default) untouched rather than overwriting with NULL."""
    record = normalize_fbi_record(_item(height_min=66, height_max=66))
    assert "height_raw" not in record.person_fields


def test_normalize_height_temporal_context_is_always_absent_for_fbi():
    record = normalize_fbi_record(_item(height_min=66, height_max=66))
    assert "height_temporal_context" not in record.person_fields


def test_normalize_never_constructs_inferred_height_raw_text():
    """Regression test: a canonical `_raw` field must contain source-provided wording
    only. Normalization must never synthesize a human-readable string like "5 ft 6 in"
    or "66 inches" from the numeric height_min/height_max fields, even though it would
    be technically derivable -- FBI provides no such wording itself, so height_raw is
    never even set (see test_normalize_height_raw_is_always_absent_for_fbi) -- this test
    additionally guards that if it ever were set, it must never be platform-generated."""
    record = normalize_fbi_record(_item(height_min=66, height_max=66))
    assert record.person_fields.get("height_raw") is None
    assert record.person_fields.get("height_raw") != "5 ft 6 in"
    assert record.person_fields.get("height_raw") != "66 inches"


# --- weight (pounds -> kg, range-preserving, temporal-context phrase match) ---------


def test_normalize_weight_point_value_converts_pounds_to_kg():
    record = normalize_fbi_record(_item(weight="130 pounds", weight_min=130, weight_max=130))
    assert record.person_fields["weight_min_kg"] == 59.0
    assert record.person_fields["weight_max_kg"] == 59.0
    assert record.person_fields["weight_min_kg"] == record.person_fields["weight_max_kg"]


def test_normalize_weight_range_preserves_both_endpoints_without_collapsing():
    record = normalize_fbi_record(
        _item(weight="130 to 140 pounds", weight_min=130, weight_max=140)
    )
    assert record.person_fields["weight_min_kg"] == 59.0
    assert record.person_fields["weight_max_kg"] == 63.5
    assert record.person_fields["weight_min_kg"] != record.person_fields["weight_max_kg"]


def test_normalize_weight_raw_preserved_verbatim():
    record = normalize_fbi_record(
        _item(weight="130 to 140 pounds", weight_min=130, weight_max=140)
    )
    assert record.person_fields["weight_raw"] == "130 to 140 pounds"


def test_normalize_weight_known_at_disappearance_qualifier_sets_temporal_context():
    record = normalize_fbi_record(
        _item(
            weight="38 pounds (at the time of her disappearance)",
            weight_min=38,
            weight_max=38,
        )
    )
    assert record.person_fields["weight_temporal_context"] == "at_disappearance"
    # The other observed phrasing must also match.
    record2 = normalize_fbi_record(
        _item(weight="60 pounds (at time of disappearance)", weight_min=60, weight_max=60)
    )
    assert record2.person_fields["weight_temporal_context"] == "at_disappearance"


def test_normalize_weight_unqualified_value_has_null_temporal_context():
    """Absence of a qualifier means unstated -- never defaulted to "current"."""
    record = normalize_fbi_record(_item(weight="130 pounds", weight_min=130, weight_max=130))
    assert record.person_fields["weight_temporal_context"] is None


def test_normalize_weight_unrecognized_wording_has_null_temporal_context():
    """A real observed qualifier ("approximately") that is NOT one of the two
    documented at-disappearance phrasings must not be matched."""
    record = normalize_fbi_record(
        _item(weight="150 pounds (approximately)", weight_min=150, weight_max=150)
    )
    assert record.person_fields["weight_temporal_context"] is None


def test_normalize_weight_missing_fields_are_none():
    item = _item()
    record = normalize_fbi_record(item)
    assert record.person_fields["weight_min_kg"] is None
    assert record.person_fields["weight_max_kg"] is None
    assert record.person_fields["weight_raw"] is None
    assert record.person_fields["weight_temporal_context"] is None


def test_normalize_weight_malformed_numeric_fields_fail_closed():
    """weight_min/weight_max as non-int (e.g. one missing, or a string) must never be
    guessed at -- both endpoints are refused together."""
    record = normalize_fbi_record(_item(weight="130 pounds", weight_min="130", weight_max=130))
    assert record.person_fields["weight_min_kg"] is None
    assert record.person_fields["weight_max_kg"] is None

    record2 = normalize_fbi_record(_item(weight="130 pounds", weight_min=130))  # weight_max absent
    assert record2.person_fields["weight_min_kg"] is None
    assert record2.person_fields["weight_max_kg"] is None


def test_normalize_weight_conflicting_unit_marker_fails_closed_but_keeps_raw():
    """Real discovered case: weight="90 kg (198 pounds)" with weight_min=90,
    weight_max=198 -- NOT a pounds range, the same weight in two units. Converting
    both as pounds would silently corrupt the value, so both are refused -- but the
    verbatim string is still safely preserved."""
    record = normalize_fbi_record(
        _item(weight="90 kg (198 pounds)", weight_min=90, weight_max=198)
    )
    assert record.person_fields["weight_min_kg"] is None
    assert record.person_fields["weight_max_kg"] is None
    assert record.person_fields["weight_raw"] == "90 kg (198 pounds)"


# --- photos (from FBI images[], generic key mapping, order preserved) --------------


def test_normalize_maps_single_image():
    record = normalize_fbi_record(
        _item(
            images=[
                {
                    "large": "https://example.gov/large.jpg",
                    "original": "https://example.gov/original.jpg",
                    "thumb": "https://example.gov/thumb.jpg",
                    "caption": "A caption.",
                }
            ]
        )
    )
    assert record.person_fields["photos"] == [
        {
            "url": "https://example.gov/large.jpg",
            "full_url": "https://example.gov/original.jpg",
            "thumbnail_url": "https://example.gov/thumb.jpg",
            "caption": "A caption.",
        }
    ]


def test_normalize_maps_multiple_images_preserving_order():
    record = normalize_fbi_record(
        _item(
            images=[
                {"large": "https://example.gov/1-large.jpg"},
                {"large": "https://example.gov/2-large.jpg"},
                {"large": "https://example.gov/3-large.jpg"},
            ]
        )
    )
    urls = [photo["url"] for photo in record.person_fields["photos"]]
    assert urls == [
        "https://example.gov/1-large.jpg",
        "https://example.gov/2-large.jpg",
        "https://example.gov/3-large.jpg",
    ]


def test_normalize_image_missing_caption_is_none():
    record = normalize_fbi_record(_item(images=[{"large": "https://example.gov/large.jpg"}]))
    assert record.person_fields["photos"][0]["caption"] is None


def test_normalize_images_absent_or_empty_is_none():
    record = normalize_fbi_record(_item())
    assert record.person_fields["photos"] is None

    record2 = normalize_fbi_record(_item(images=[]))
    assert record2.person_fields["photos"] is None


def test_normalize_malformed_image_entries_are_skipped_not_fatal():
    """A non-dict entry is skipped; well-formed siblings are still mapped -- one bad
    image doesn't call the rest of the list into question (unlike aliases)."""
    record = normalize_fbi_record(
        _item(
            images=[
                {"large": "https://example.gov/good.jpg"},
                "not-a-dict",
                None,
                123,
            ]
        )
    )
    assert record.person_fields["photos"] == [
        {
            "url": "https://example.gov/good.jpg",
            "full_url": None,
            "thumbnail_url": None,
            "caption": None,
        }
    ]


def test_normalize_images_all_malformed_is_none():
    record = normalize_fbi_record(_item(images=["not-a-dict", 123, None]))
    assert record.person_fields["photos"] is None
