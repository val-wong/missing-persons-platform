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
