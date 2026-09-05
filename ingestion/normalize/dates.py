"""Source-agnostic date-parsing helpers.

Fail closed throughout: any shape or format ambiguity returns None rather than
guessing (see docs/architecture.md). Pure functions, no I/O.
"""

from __future__ import annotations

from datetime import date, datetime


def parse_single_date_from_list(value: object, fmt: str) -> date | None:
    """Accept a date only when `value` is a list with exactly one string entry that
    parses cleanly against `fmt`.

    Any other shape -- missing, empty, more than one entry, wrong element type, or a
    string that doesn't match `fmt` -- returns None. This function must never choose
    among multiple candidate values; a multi-entry list is refused, not resolved by
    picking the first/last/any entry.
    """
    if not isinstance(value, list) or len(value) != 1:
        return None
    (entry,) = value
    if not isinstance(entry, str):
        return None
    try:
        return datetime.strptime(entry.strip(), fmt).date()
    except ValueError:
        return None
