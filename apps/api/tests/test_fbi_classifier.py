from ingestion.sources.fbi.classifier import (
    FBI_KIDNAPPING_OUT_OF_SCOPE,
    FBI_NO_CLASSIFICATION_SIGNAL,
    FBI_POSTER_CLASSIFICATION_MISSING,
    FBI_SUBJECT_ECAP_OUT_OF_SCOPE,
    FBI_SUBJECT_KIDNAPPINGS_AND_MISSING_PERSONS_INSUFFICIENT,
    FBI_SUBJECT_KNOWN_NON_MISSING_PERSON,
    FBI_SUBJECT_VICAP_MISSING_PERSONS,
    FBI_UNKNOWN_CLASSIFICATION,
    FBI_VICAP_UNIDENTIFIED_OUT_OF_SCOPE,
    ClassificationOutcome,
    RecordType,
    classify_fbi_record,
)


def _payload(poster_classification=None, subjects=None, **extra) -> dict:
    payload = {"uid": "test-uid", "title": "SHOULD NEVER BE READ", "details": "SHOULD NEVER BE READ"}
    if poster_classification is not None:
        payload["poster_classification"] = poster_classification
    if subjects is not None:
        payload["subjects"] = subjects
    payload.update(extra)
    return payload


# ----------------------------------------------------------------------------------
# Required cases (task item 8)
# ----------------------------------------------------------------------------------


def test_poster_classification_missing_is_in_scope():
    result = classify_fbi_record(_payload(poster_classification="missing"))

    assert result.outcome is ClassificationOutcome.IN_SCOPE
    assert result.record_type is RecordType.MISSING_PERSON
    assert result.reason_codes == (FBI_POSTER_CLASSIFICATION_MISSING,)


def test_subjects_vicap_missing_persons_is_in_scope():
    result = classify_fbi_record(_payload(subjects=["ViCAP Missing Persons"]))

    assert result.outcome is ClassificationOutcome.IN_SCOPE
    assert result.record_type is RecordType.MISSING_PERSON
    assert result.reason_codes == (FBI_SUBJECT_VICAP_MISSING_PERSONS,)


def test_both_positive_signals_simultaneously():
    result = classify_fbi_record(
        _payload(poster_classification="missing", subjects=["ViCAP Missing Persons"])
    )

    assert result.outcome is ClassificationOutcome.IN_SCOPE
    assert result.record_type is RecordType.MISSING_PERSON
    assert set(result.reason_codes) == {
        FBI_POSTER_CLASSIFICATION_MISSING,
        FBI_SUBJECT_VICAP_MISSING_PERSONS,
    }


def test_kidnappings_and_missing_persons_with_poster_missing_is_in_scope():
    result = classify_fbi_record(
        _payload(poster_classification="missing", subjects=["Kidnappings and Missing Persons"])
    )

    assert result.outcome is ClassificationOutcome.IN_SCOPE
    assert result.record_type is RecordType.MISSING_PERSON
    # The deciding signal is poster_classification; the KMP subject alone is retained
    # as an informational, non-decisive reason code (rule 6: "retain all applicable").
    assert FBI_POSTER_CLASSIFICATION_MISSING in result.reason_codes
    assert FBI_SUBJECT_KIDNAPPINGS_AND_MISSING_PERSONS_INSUFFICIENT in result.reason_codes


def test_kidnappings_and_missing_persons_with_poster_kidnapping_is_out_of_scope():
    result = classify_fbi_record(
        _payload(poster_classification="kidnapping", subjects=["Kidnappings and Missing Persons"])
    )

    assert result.outcome is ClassificationOutcome.OUT_OF_SCOPE
    assert result.record_type is RecordType.OTHER
    assert set(result.reason_codes) == {
        FBI_KIDNAPPING_OUT_OF_SCOPE,
        FBI_SUBJECT_KIDNAPPINGS_AND_MISSING_PERSONS_INSUFFICIENT,
    }


def test_vicap_unidentified_persons_is_out_of_scope():
    result = classify_fbi_record(_payload(subjects=["ViCAP Unidentified Persons"]))

    assert result.outcome is ClassificationOutcome.OUT_OF_SCOPE
    assert result.record_type is RecordType.OTHER
    assert result.reason_codes == (FBI_VICAP_UNIDENTIFIED_OUT_OF_SCOPE,)


def test_ecap_is_out_of_scope():
    result = classify_fbi_record(_payload(subjects=["ECAP"]))

    assert result.outcome is ClassificationOutcome.OUT_OF_SCOPE
    assert result.record_type is RecordType.OTHER
    assert result.reason_codes == (FBI_SUBJECT_ECAP_OUT_OF_SCOPE,)


def test_unknown_poster_classification_is_unclassified():
    result = classify_fbi_record(_payload(poster_classification="brand-new-value-never-seen"))

    assert result.outcome is ClassificationOutcome.UNCLASSIFIED
    assert result.record_type is RecordType.UNKNOWN
    assert result.reason_codes == (FBI_UNKNOWN_CLASSIFICATION,)


def test_unknown_subject_value_is_unclassified():
    result = classify_fbi_record(_payload(subjects=["Some Brand New Category"]))

    assert result.outcome is ClassificationOutcome.UNCLASSIFIED
    assert result.record_type is RecordType.UNKNOWN
    assert result.reason_codes == (FBI_UNKNOWN_CLASSIFICATION,)


def test_unknown_classification_does_not_silently_become_out_of_scope():
    # A record with one known-negative subject AND one never-seen subject must not be
    # auto-classified OUT_OF_SCOPE -- the unrecognized value must win (rule 5).
    result = classify_fbi_record(_payload(subjects=["Seeking Information", "Something New"]))

    assert result.outcome is ClassificationOutcome.UNCLASSIFIED
    assert result.record_type is RecordType.UNKNOWN
    assert FBI_UNKNOWN_CLASSIFICATION in result.reason_codes


def test_missing_subjects_key_with_no_poster_classification_is_unclassified():
    result = classify_fbi_record(_payload())

    assert result.outcome is ClassificationOutcome.UNCLASSIFIED
    assert result.record_type is RecordType.UNKNOWN
    assert result.reason_codes == (FBI_NO_CLASSIFICATION_SIGNAL,)


def test_missing_subjects_key_does_not_block_poster_classification_signal():
    result = classify_fbi_record(_payload(poster_classification="missing"))

    assert result.outcome is ClassificationOutcome.IN_SCOPE
    assert result.reason_codes == (FBI_POSTER_CLASSIFICATION_MISSING,)


def test_empty_subjects_list_with_no_poster_classification_is_unclassified():
    result = classify_fbi_record(_payload(subjects=[]))

    assert result.outcome is ClassificationOutcome.UNCLASSIFIED
    assert result.reason_codes == (FBI_NO_CLASSIFICATION_SIGNAL,)


def test_empty_subjects_list_does_not_block_poster_classification_signal():
    result = classify_fbi_record(_payload(poster_classification="missing", subjects=[]))

    assert result.outcome is ClassificationOutcome.IN_SCOPE


def test_multiple_subjects_one_positive_one_known_negative():
    result = classify_fbi_record(_payload(subjects=["Indian Country", "ViCAP Missing Persons"]))

    assert result.outcome is ClassificationOutcome.IN_SCOPE
    assert result.record_type is RecordType.MISSING_PERSON
    assert set(result.reason_codes) == {
        FBI_SUBJECT_VICAP_MISSING_PERSONS,
        FBI_SUBJECT_KNOWN_NON_MISSING_PERSON,
    }


def test_malformed_non_list_subjects_never_substring_matched():
    # subjects is a bare string containing the exact positive label -- this must NOT
    # be treated as a match. Rule 2: membership is tested against normalized list
    # values, never by substring/serialized-JSON matching.
    result = classify_fbi_record(_payload(subjects="ViCAP Missing Persons"))

    assert result.outcome is ClassificationOutcome.UNCLASSIFIED
    assert result.reason_codes == (FBI_NO_CLASSIFICATION_SIGNAL,)


def test_malformed_non_list_subjects_types_all_yield_no_signal():
    for malformed in (123, {"subjects": "x"}, True, 4.5):
        result = classify_fbi_record(_payload(subjects=malformed))
        assert result.outcome is ClassificationOutcome.UNCLASSIFIED
        assert result.reason_codes == (FBI_NO_CLASSIFICATION_SIGNAL,)


# ----------------------------------------------------------------------------------
# Documented normalization policy: whitespace trimmed everywhere; poster_classification
# compared case-insensitively; subjects entries compared case-sensitively.
# ----------------------------------------------------------------------------------


def test_poster_classification_whitespace_is_trimmed():
    result = classify_fbi_record(_payload(poster_classification="  missing  "))

    assert result.outcome is ClassificationOutcome.IN_SCOPE
    assert result.reason_codes == (FBI_POSTER_CLASSIFICATION_MISSING,)


def test_poster_classification_comparison_is_case_insensitive():
    result = classify_fbi_record(_payload(poster_classification="MISSING"))

    assert result.outcome is ClassificationOutcome.IN_SCOPE
    assert result.reason_codes == (FBI_POSTER_CLASSIFICATION_MISSING,)


def test_subject_whitespace_is_trimmed():
    result = classify_fbi_record(_payload(subjects=["  ViCAP Missing Persons  "]))

    assert result.outcome is ClassificationOutcome.IN_SCOPE
    assert result.reason_codes == (FBI_SUBJECT_VICAP_MISSING_PERSONS,)


def test_subject_comparison_is_case_sensitive():
    # Differently-cased variant of the exact positive label must NOT match: per the
    # documented policy, subject labels are compared case-sensitively so an
    # unexpected casing surfaces as "unknown" rather than being silently accepted.
    result = classify_fbi_record(_payload(subjects=["vicap missing persons"]))

    assert result.outcome is ClassificationOutcome.UNCLASSIFIED
    assert result.reason_codes == (FBI_UNKNOWN_CLASSIFICATION,)


def test_blank_string_poster_classification_yields_no_signal():
    result = classify_fbi_record(_payload(poster_classification="   "))

    assert result.outcome is ClassificationOutcome.UNCLASSIFIED
    assert result.reason_codes == (FBI_NO_CLASSIFICATION_SIGNAL,)


def test_blank_string_subject_entries_are_ignored():
    result = classify_fbi_record(_payload(subjects=["   ", "ViCAP Missing Persons"]))

    assert result.outcome is ClassificationOutcome.IN_SCOPE
    assert result.reason_codes == (FBI_SUBJECT_VICAP_MISSING_PERSONS,)


# ----------------------------------------------------------------------------------
# Purity / determinism
# ----------------------------------------------------------------------------------


def test_classifier_is_pure_and_deterministic():
    payload = _payload(poster_classification="missing", subjects=["Kidnappings and Missing Persons"])

    first = classify_fbi_record(payload)
    second = classify_fbi_record(dict(payload))  # a fresh, equal-but-not-identical dict

    assert first == second


def test_person_classification_field_never_influences_outcome():
    base = _payload(subjects=["Indian Country"])
    with_main = {**base, "person_classification": "Main"}
    with_victim = {**base, "person_classification": "Victim"}

    assert classify_fbi_record(with_main) == classify_fbi_record(with_victim)
