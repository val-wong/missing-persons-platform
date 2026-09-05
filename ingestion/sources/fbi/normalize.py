"""FBI -> canonical field normalization.

Implements exactly the mappings evidenced as safe in docs/fbi-normalization.md -- no
more. Every canonical field this module does not explicitly map is left unset, and
stays NULL on the resulting Person/Case row. This module is pure (no I/O, no DB access,
no randomness); the same raw item always normalizes to the same NormalizedRecord.

Only call this for items the Phase 1 classifier (`classify_fbi_record`) has already
marked IN_SCOPE / MISSING_PERSON -- normalization does not itself re-check scope.

Fields intentionally NOT mapped here (left NULL), per fbi-normalization.md's own
conclusions -- restated so a future edit to this module has to consciously override
these, not accidentally drift past them:
  - missing_date, missing_city/county/state/country: no field with an established
    "where/when this person went missing" meaning exists in the FBI schema.
  - agency_case_number: `ncic` is the only plausibly-matching field and is never
    populated.
  - age_at_missing: `age_min`/`age_max`/`age_range` don't resolve whether they mean
    age-at-disappearance or current estimated age.
  - case_status: `status` is constant across the sampled IN_SCOPE population, so it
    carries no per-record signal.
  - given_name/middle_name/family_name/suffix: no structured name-component field
    exists; only `title` (whole display name) is available.
  - height_cm, weight_kg, photo_urls: evidenced (see docs/fbi-normalization.md
    "Physical description / photo fields") but each has an unresolved unit, range, or
    per-image-shape policy question -- not a guess-at-field-names gap like the others
    above. Mapping these requires that policy decision first, not a normalization change.
  - `hair` / `eyes` / `race` (the FBI-normalized/controlled-vocabulary variants, as
    opposed to `hair_raw` / `eyes_raw` / `race_raw`): deliberately not used as the
    source for `hair_color` / `eye_color` below -- the field-evidence audit (see
    docs/fbi-normalization.md) proved `_raw` is a strict superset of the fuller,
    human-authored value FBI actually reports (100% of populated `hair`/`eyes` values
    are a lowercase prefix or substring of their `_raw` counterpart), and this
    platform's principle is to preserve exactly what the source reported rather than
    prefer the source's own downstream-normalized/bucketed variant.
  - race/race_raw: `Person` has no race field; adding one is a separate product
    decision (not merely a mapping), out of scope here.
"""

from __future__ import annotations

from typing import Any

from ingestion.normalize.dates import parse_single_date_from_list
from ingestion.normalize.text import blank_to_none, clean_string_list
from ingestion.sources.base import NormalizedRecord

FBI_INVESTIGATING_AGENCY = "Federal Bureau of Investigation"

_DOB_LIST_FIELD = "dates_of_birth_used"
_DOB_FORMAT = "%B %d, %Y"


def normalize_fbi_record(item: dict[str, Any]) -> NormalizedRecord:
    """Map one raw FBI Wanted API item to canonical Person/Case field values."""
    person_fields: dict[str, Any] = {
        "display_name": blank_to_none(item.get("title")),
        "sex": blank_to_none(item.get("sex")),
        "date_of_birth": parse_single_date_from_list(item.get(_DOB_LIST_FIELD), _DOB_FORMAT),
        # `_raw`, not the FBI-normalized `hair`/`eyes` bucket -- see module docstring.
        "hair_color": blank_to_none(item.get("hair_raw")),
        "eye_color": blank_to_none(item.get("eyes_raw")),
        "aliases": clean_string_list(item.get("aliases")),
        "distinguishing_characteristics": blank_to_none(item.get("scars_and_marks")),
    }
    case_fields: dict[str, Any] = {
        "circumstances": blank_to_none(item.get("description")),
        # Constant, derived from which Source produced this record -- not parsed from
        # any FBI-supplied field. See docs/fbi-normalization.md.
        "investigating_agency": FBI_INVESTIGATING_AGENCY,
    }
    return NormalizedRecord(person_fields=person_fields, case_fields=case_fields)
