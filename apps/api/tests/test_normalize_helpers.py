from datetime import date

from ingestion.normalize.dates import parse_single_date_from_list
from ingestion.normalize.text import blank_to_none, clean_string_list


def test_blank_to_none_rejects_non_strings():
    assert blank_to_none(None) is None
    assert blank_to_none(123) is None
    assert blank_to_none(["not", "a", "string"]) is None


def test_blank_to_none_rejects_empty_and_whitespace_only():
    assert blank_to_none("") is None
    assert blank_to_none("   ") is None
    assert blank_to_none("\t\n") is None


def test_blank_to_none_preserves_non_blank_value_verbatim():
    assert blank_to_none("Jane") == "Jane"
    assert blank_to_none("  Jane  ") == "  Jane  "  # not trimmed -- verbatim copy


def test_parse_single_date_from_list_accepts_matching_single_entry():
    assert parse_single_date_from_list(["January 1, 2000"], "%B %d, %Y") == date(2000, 1, 1)


def test_parse_single_date_from_list_rejects_multiple_entries():
    assert parse_single_date_from_list(["January 1, 2000", "February 2, 2001"], "%B %d, %Y") is None


def test_parse_single_date_from_list_rejects_empty_list():
    assert parse_single_date_from_list([], "%B %d, %Y") is None


def test_parse_single_date_from_list_rejects_non_list_input():
    assert parse_single_date_from_list("January 1, 2000", "%B %d, %Y") is None
    assert parse_single_date_from_list(None, "%B %d, %Y") is None


def test_parse_single_date_from_list_rejects_non_string_entry():
    assert parse_single_date_from_list([2000], "%B %d, %Y") is None


def test_parse_single_date_from_list_rejects_format_mismatch():
    assert parse_single_date_from_list(["2000-01-01"], "%B %d, %Y") is None


def test_clean_string_list_accepts_list_of_strings_verbatim():
    assert clean_string_list(["Johnny", "J.D."]) == ["Johnny", "J.D."]


def test_clean_string_list_does_not_reorder_or_dedupe():
    assert clean_string_list(["B", "A", "B"]) == ["B", "A", "B"]


def test_clean_string_list_rejects_non_list_input():
    assert clean_string_list("Johnny") is None
    assert clean_string_list(None) is None


def test_clean_string_list_rejects_empty_list():
    assert clean_string_list([]) is None


def test_clean_string_list_rejects_whole_list_on_any_non_string_element():
    assert clean_string_list(["Johnny", 123]) is None


def test_clean_string_list_rejects_whole_list_on_any_blank_element():
    assert clean_string_list(["Johnny", "   "]) is None
