"""Source-agnostic text/value normalization helpers.

No source-specific logic belongs here -- see `ingestion/sources/<source>/normalize.py`
for field mapping decisions. Everything here is a pure function: same input, same
output, no I/O.
"""

from __future__ import annotations


def blank_to_none(value: object) -> str | None:
    """Coerce a non-string, empty, or whitespace-only value to None.

    Returns the original string unchanged (not trimmed) when it has non-whitespace
    content -- trimming is not assumed safe for every field (e.g. free text where
    leading/trailing whitespace could theoretically be meaningful), so this function
    only decides blank-vs-not, never reshapes the value itself.
    """
    if not isinstance(value, str):
        return None
    return value if value.strip() else None


def clean_string_list(value: object) -> list[str] | None:
    """Accept a non-empty list of non-blank strings verbatim, or None otherwise.

    Fails closed on the whole list rather than partially cleaning it: a value that
    isn't a list, an empty list, or a list containing any non-string or blank/
    whitespace-only element is rejected in full (-> None), never filtered down to
    "the entries that were fine." This function never reorders, deduplicates, splits,
    or rewrites individual entries -- it only decides whether the list, as a whole, is
    clean enough to copy verbatim.
    """
    if not isinstance(value, list) or not value:
        return None
    if any(not isinstance(item, str) or not item.strip() for item in value):
        return None
    return list(value)
