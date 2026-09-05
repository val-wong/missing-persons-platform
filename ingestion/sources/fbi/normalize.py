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
  - height_min_cm, height_max_cm, height_raw, height_temporal_context: the schema
    supports height (see docs/fbi-normalization.md), but FBI's `height_min`/
    `height_max` unit was only ever confirmed to MEDIUM confidence (no sibling
    free-text field to cross-check against, unlike weight) -- left NULL until that
    improves. Do not populate these from FBI data; this is a deliberate policy
    decision, not an oversight (see the regression test in test_fbi_normalize.py).
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

# Exact international avoirdupois pound, per the 1959 international yard-and-pound
# agreement -- not an approximation. FBI's `weight_min`/`weight_max` are proven pounds
# with HIGH confidence (the free-text `weight` field states "pounds" directly and its
# number matches these fields exactly -- see docs/fbi-normalization.md). Stored to 1
# decimal place: finer than the source's own precision (whole pounds, ~0.45 kg per
# unit), so no meaningful distinction between adjacent source values is lost.
_LB_TO_KG = 0.45359237
_WEIGHT_KG_PRECISION = 1

# A `weight` string containing any of these signals the numeric weight_min/weight_max
# fields cannot be safely assumed to be pounds for THIS record -- discovered directly in
# the stored data: one record reads weight="90 kg (198 pounds)" with weight_min=90,
# weight_max=198, i.e. the SAME weight in two units, not a pounds range. Converting both
# as pounds would silently corrupt it. See docs/fbi-normalization.md.
_CONFLICTING_WEIGHT_UNIT_MARKERS = ("kg", "kilogram")

# The ONLY two literal phrasings observed across every populated `weight` string in the
# stored 104 IN_SCOPE FBI records (see docs/fbi-normalization.md for the full
# enumeration). Deliberately not extended with unobserved variants (e.g. a "his
# disappearance" counterpart) -- built from evidence, not anticipated symmetry.
_AT_DISAPPEARANCE_PHRASES = (
    "at the time of her disappearance",
    "at time of disappearance",
)

_FBI_IMAGE_KEY_MAP = {
    "large": "url",
    "original": "full_url",
    "thumb": "thumbnail_url",
    "caption": "caption",
}


def _pounds_to_kg(value: int) -> float:
    return round(value * _LB_TO_KG, _WEIGHT_KG_PRECISION)


def _weight_kg_range(
    weight_min: object, weight_max: object, weight_raw: object
) -> tuple[float | None, float | None]:
    """Convert FBI's weight_min/weight_max (pounds) to kg, preserving both endpoints
    separately -- never collapsed to a midpoint/min/max. Fails closed (both None) when
    either endpoint isn't an int, or when `weight_raw` mentions a conflicting unit (see
    `_CONFLICTING_WEIGHT_UNIT_MARKERS`)."""
    if not isinstance(weight_min, int) or not isinstance(weight_max, int):
        return None, None
    if isinstance(weight_raw, str) and any(
        marker in weight_raw.lower() for marker in _CONFLICTING_WEIGHT_UNIT_MARKERS
    ):
        return None, None
    return _pounds_to_kg(weight_min), _pounds_to_kg(weight_max)


def _weight_temporal_context(weight_raw: object) -> str | None:
    """Only ever returns "at_disappearance", via an exact, documented literal-phrase
    match against `weight_raw` -- never inferred from narrative text, missing_date, or
    an unqualified value's absence of a phrase (which means "unstated", not "current")."""
    if not isinstance(weight_raw, str):
        return None
    lowered = weight_raw.lower()
    if any(phrase in lowered for phrase in _AT_DISAPPEARANCE_PHRASES):
        return "at_disappearance"
    return None


def _normalize_fbi_image(image: object) -> dict[str, str | None] | None:
    """Map one FBI image object's keys to the generic canonical photo shape. Returns
    None for a malformed (non-dict) entry -- fails closed on that one entry rather than
    guessing, without discarding the rest of the list (see `_normalize_fbi_images`)."""
    if not isinstance(image, dict):
        return None
    return {
        canonical_key: blank_to_none(image.get(fbi_key))
        for fbi_key, canonical_key in _FBI_IMAGE_KEY_MAP.items()
    }


def _normalize_fbi_images(images: object) -> list[dict[str, str | None]] | None:
    """Map FBI's `images` list to the canonical `photos` shape, preserving order
    exactly. A malformed individual entry is skipped (each image is an independent,
    self-contained object -- unlike `aliases`, one bad entry doesn't call the rest of
    the list into question). Returns None, never `[]`, when nothing usable remains, so
    "no images reported" and "every entry was unusable" read identically: no photos
    known."""
    if not isinstance(images, list) or not images:
        return None
    normalized = [img for img in (_normalize_fbi_image(item) for item in images) if img is not None]
    return normalized or None


def normalize_fbi_record(item: dict[str, Any]) -> NormalizedRecord:
    """Map one raw FBI Wanted API item to canonical Person/Case field values."""
    weight_raw = item.get("weight")
    weight_min_kg, weight_max_kg = _weight_kg_range(
        item.get("weight_min"), item.get("weight_max"), weight_raw
    )

    person_fields: dict[str, Any] = {
        "display_name": blank_to_none(item.get("title")),
        "sex": blank_to_none(item.get("sex")),
        "date_of_birth": parse_single_date_from_list(item.get(_DOB_LIST_FIELD), _DOB_FORMAT),
        # `_raw`, not the FBI-normalized `hair`/`eyes` bucket -- see module docstring.
        "hair_color": blank_to_none(item.get("hair_raw")),
        "eye_color": blank_to_none(item.get("eyes_raw")),
        "aliases": clean_string_list(item.get("aliases")),
        "distinguishing_characteristics": blank_to_none(item.get("scars_and_marks")),
        "weight_min_kg": weight_min_kg,
        "weight_max_kg": weight_max_kg,
        "weight_raw": blank_to_none(weight_raw),
        "weight_temporal_context": _weight_temporal_context(weight_raw),
        "photos": _normalize_fbi_images(item.get("images")),
        # height_min_cm/height_max_cm/height_raw/height_temporal_context: deliberately
        # absent -- see module docstring.
    }
    case_fields: dict[str, Any] = {
        "circumstances": blank_to_none(item.get("description")),
        # Constant, derived from which Source produced this record -- not parsed from
        # any FBI-supplied field. See docs/fbi-normalization.md.
        "investigating_agency": FBI_INVESTIGATING_AGENCY,
    }
    return NormalizedRecord(person_fields=person_fields, case_fields=case_fields)
