"""Read-only FBI -> canonical normalization discovery report.

ANALYSIS ONLY. This module never creates or modifies Person, Case, CaseSource,
SourceRecord, or SourceSnapshot rows -- it issues SELECT queries only, and its output
is aggregate structural statistics (field names, JSON types, presence/null/empty
counts, percentages). It exists to answer: "which structured FBI fields can we safely
and deterministically map into the canonical schema?" -- not to perform that mapping.

Only IN_SCOPE / MISSING_PERSON records (per the Phase 1 classifier,
`ingestion.sources.fbi.classifier.classify_fbi_record`) are inspected, since those are
the only FBI records this platform currently intends to normalize at all.

Safety rules this module follows throughout:
  - Never prints or returns individual field *values* that identify or describe a
    specific person (name, DOB, physical description, free-text narrative, etc.).
    Only aggregate counts, type names, and structural pattern-match counts (e.g. "N of
    33 date-of-birth strings match a known date format") are produced -- never the
    values themselves.
  - No free-text NLP or heuristic content-scanning of title/description/details/
    remarks is performed. Fields identified as "free text" are reported structurally
    (present/null/type) only, exactly like every other field -- their *content* is
    never inspected for patterns, names, dates, or locations.
  - No inference: this module reports what the data structurally supports, not a
    best-guess value.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.models.source import Source
from ingestion.sources.fbi.classification_report import get_latest_snapshots
from ingestion.sources.fbi.classifier import ClassificationOutcome, classify_fbi_record

# A structured "Month D, YYYY" date string, e.g. matching the shape observed for
# dates_of_birth_used entries. Used only to COUNT matches/non-matches -- the actual
# date strings are never returned or printed by this module.
_MONTH_DAY_YEAR_PATTERN = re.compile(r"^[A-Za-z]+ \d{1,2}, \d{4}$")

_EMPTY_VALUES = ("", [], {})


# ---------------------------------------------------------------------------------
# Data access (read-only)
# ---------------------------------------------------------------------------------


def get_in_scope_payloads(db: Session, source: Source) -> list[dict[str, Any]]:
    """Latest-snapshot payloads for active FBI records the Phase 1 classifier marks
    IN_SCOPE. Read-only: issues SELECT statements only.
    """
    snapshots = get_latest_snapshots(db, source)
    return [
        snapshot.payload
        for snapshot in snapshots
        if classify_fbi_record(snapshot.payload).outcome is ClassificationOutcome.IN_SCOPE
    ]


# ---------------------------------------------------------------------------------
# 1. Aggregate per-field structural report (all fields, uniform treatment)
# ---------------------------------------------------------------------------------


@dataclass
class FieldStructuralStats:
    observed_types: tuple[str, ...]
    count_present: int  # key exists in the payload
    count_null: int  # key exists and value is None
    count_empty: int  # key exists, non-null, but "" / [] / {}
    count_populated: int  # key exists, non-null, non-empty
    total: int

    @property
    def percentage_populated(self) -> float:
        if self.total == 0:
            return 0.0
        return round(100.0 * self.count_populated / self.total, 1)


def field_structural_report(payloads: list[dict[str, Any]]) -> dict[str, FieldStructuralStats]:
    """Structural stats for every field observed across `payloads`. Values themselves
    are never read into the result -- only `type(value).__name__` and presence/null/
    emptiness booleans are.
    """
    total = len(payloads)
    field_names: set[str] = set()
    for payload in payloads:
        field_names.update(payload.keys())

    report: dict[str, FieldStructuralStats] = {}
    for name in sorted(field_names):
        types: set[str] = set()
        present = 0
        null = 0
        empty = 0
        populated = 0
        for payload in payloads:
            if name not in payload:
                continue
            present += 1
            value = payload[name]
            types.add(type(value).__name__)
            if value is None:
                null += 1
            elif isinstance(value, (str, list, dict)) and value in _EMPTY_VALUES:
                empty += 1
            else:
                populated += 1
        report[name] = FieldStructuralStats(
            observed_types=tuple(sorted(types)),
            count_present=present,
            count_null=null,
            count_empty=empty,
            count_populated=populated,
            total=total,
        )
    return report


# ---------------------------------------------------------------------------------
# 2-3. Targeted investigations backing the rule-4 confidence classifications
# ---------------------------------------------------------------------------------


# Candidate key names that WOULD indicate structured given/middle/family-name
# components, if the FBI API provided them. None of these are expected to be found;
# this list exists so the check is explicit and re-verifiable rather than assumed.
_STRUCTURED_NAME_FIELD_CANDIDATES = (
    "given_name",
    "first_name",
    "middle_name",
    "last_name",
    "family_name",
    "surname",
    "name",
)


@dataclass
class NameFieldInvestigation:
    title_present_count: int
    aliases_present_count: int  # non-null, non-empty
    structured_name_fields_found: tuple[str, ...]  # should be empty
    total: int

    @property
    def structured_name_components_available(self) -> bool:
        return len(self.structured_name_fields_found) > 0


def investigate_name_fields(payloads: list[dict[str, Any]]) -> NameFieldInvestigation:
    total = len(payloads)
    title_present = sum(1 for p in payloads if isinstance(p.get("title"), str) and p["title"].strip())
    aliases_present = sum(1 for p in payloads if isinstance(p.get("aliases"), list) and len(p["aliases"]) > 0)
    found = tuple(
        name for name in _STRUCTURED_NAME_FIELD_CANDIDATES if any(name in p for p in payloads)
    )
    return NameFieldInvestigation(
        title_present_count=title_present,
        aliases_present_count=aliases_present,
        structured_name_fields_found=found,
        total=total,
    )


@dataclass
class DobInvestigation:
    field_name: str
    observed_types: tuple[str, ...]
    null_or_absent_count: int
    list_length_counts: dict[int, int]  # {length: number of records}
    format_matches_known_pattern: int
    format_does_not_match_known_pattern: int
    total: int

    @property
    def exactly_one_value_count(self) -> int:
        return self.list_length_counts.get(1, 0)

    @property
    def multiple_values_count(self) -> int:
        return sum(count for length, count in self.list_length_counts.items() if length > 1)

    @property
    def safe_to_accept_when_exactly_one(self) -> bool:
        """True iff every observed multi-value case is absent (0) -- i.e. whenever the
        field is populated at all in this sample, it has exactly one entry. This does
        NOT mean multi-value lists can never occur; see docs for the fail-closed policy
        this recommends regardless (never choose among multiple).
        """
        return self.multiple_values_count == 0


def investigate_dob_field(
    payloads: list[dict[str, Any]], field_name: str = "dates_of_birth_used"
) -> DobInvestigation:
    total = len(payloads)
    types: set[str] = set()
    null_or_absent = 0
    length_counts: Counter[int] = Counter()
    matches = 0
    non_matches = 0

    for payload in payloads:
        value = payload.get(field_name)
        types.add(type(value).__name__)
        if value is None:
            null_or_absent += 1
            continue
        if not isinstance(value, list):
            # Structurally unexpected shape; do not guess at its meaning.
            continue
        if len(value) == 0:
            null_or_absent += 1
            continue
        length_counts[len(value)] += 1
        if len(value) == 1 and isinstance(value[0], str):
            if _MONTH_DAY_YEAR_PATTERN.match(value[0].strip()):
                matches += 1
            else:
                non_matches += 1

    return DobInvestigation(
        field_name=field_name,
        observed_types=tuple(sorted(types)),
        null_or_absent_count=null_or_absent,
        list_length_counts=dict(length_counts),
        format_matches_known_pattern=matches,
        format_does_not_match_known_pattern=non_matches,
        total=total,
    )


# Fields that could plausibly relate to a physical location, for structural review.
# None are assumed to mean "where the person went missing" -- see docs for why.
_LOCATION_ADJACENT_FIELDS = (
    "place_of_birth",
    "locations",
    "field_offices",
    "possible_states",
    "possible_countries",
    "coordinates",
)


@dataclass
class LocationFieldInvestigation:
    per_field_non_empty_counts: dict[str, int]
    per_field_types: dict[str, tuple[str, ...]]
    total: int


def investigate_location_fields(payloads: list[dict[str, Any]]) -> LocationFieldInvestigation:
    total = len(payloads)
    non_empty: dict[str, int] = {}
    types: dict[str, tuple[str, ...]] = {}
    for name in _LOCATION_ADJACENT_FIELDS:
        count = 0
        observed_types: set[str] = set()
        for payload in payloads:
            value = payload.get(name)
            observed_types.add(type(value).__name__)
            if value is None:
                continue
            if isinstance(value, (str, list, dict)) and value in _EMPTY_VALUES:
                continue
            count += 1
        non_empty[name] = count
        types[name] = tuple(sorted(observed_types))
    return LocationFieldInvestigation(per_field_non_empty_counts=non_empty, per_field_types=types, total=total)


@dataclass
class AgencyFieldInvestigation:
    ncic_populated_count: int
    field_offices_populated_count: int
    dedicated_case_number_field_found: bool
    total: int


def investigate_agency_fields(payloads: list[dict[str, Any]]) -> AgencyFieldInvestigation:
    total = len(payloads)
    ncic_populated = sum(1 for p in payloads if p.get("ncic") not in (None, "", []))
    field_offices_populated = sum(
        1 for p in payloads if isinstance(p.get("field_offices"), list) and len(p["field_offices"]) > 0
    )
    # No field observed anywhere in the FBI item schema is named/shaped like a case
    # docket number other than `ncic`, which is checked above.
    return AgencyFieldInvestigation(
        ncic_populated_count=ncic_populated,
        field_offices_populated_count=field_offices_populated,
        dedicated_case_number_field_found=False,
        total=total,
    )


@dataclass
class MultiPersonStructuralSignal:
    dob_multi_value_count: int
    image_count_distribution: dict[int, int]  # {number of images: number of records}
    total: int


def investigate_multi_person_signal(payloads: list[dict[str, Any]]) -> MultiPersonStructuralSignal:
    """Purely structural evidence for whether a record might represent more than one
    person. Does NOT scan title/description content -- only counts values in fields
    that are structurally list-shaped and could, in principle, hold one entry per
    person (dates_of_birth_used, images). See docs/fbi-normalization.md for why this
    is treated as weak evidence, not a determination.
    """
    total = len(payloads)
    dob_multi = 0
    for payload in payloads:
        value = payload.get("dates_of_birth_used")
        if isinstance(value, list) and len(value) > 1:
            dob_multi += 1

    image_counts: Counter[int] = Counter()
    for payload in payloads:
        images = payload.get("images")
        n = len(images) if isinstance(images, list) else 0
        image_counts[n] += 1

    return MultiPersonStructuralSignal(
        dob_multi_value_count=dob_multi,
        image_count_distribution=dict(sorted(image_counts.items())),
        total=total,
    )


# ---------------------------------------------------------------------------------
# Top-level report
# ---------------------------------------------------------------------------------


@dataclass
class NormalizationDiscoveryReport:
    total_in_scope_records: int
    field_stats: dict[str, FieldStructuralStats]
    name_investigation: NameFieldInvestigation
    dob_investigation: DobInvestigation
    location_investigation: LocationFieldInvestigation
    agency_investigation: AgencyFieldInvestigation
    multi_person_signal: MultiPersonStructuralSignal


def build_normalization_report(db: Session, source: Source) -> NormalizationDiscoveryReport:
    payloads = get_in_scope_payloads(db, source)
    return NormalizationDiscoveryReport(
        total_in_scope_records=len(payloads),
        field_stats=field_structural_report(payloads),
        name_investigation=investigate_name_fields(payloads),
        dob_investigation=investigate_dob_field(payloads),
        location_investigation=investigate_location_fields(payloads),
        agency_investigation=investigate_agency_fields(payloads),
        multi_person_signal=investigate_multi_person_signal(payloads),
    )


def render_normalization_report(report: NormalizationDiscoveryReport) -> str:
    lines: list[str] = []
    lines.append("FBI normalization discovery report (read-only, structural only)")
    lines.append("=" * 60)
    lines.append(f"Total IN_SCOPE / MISSING_PERSON records inspected: {report.total_in_scope_records}")
    lines.append("")

    lines.append("Per-field structural stats (name / types / present / null / empty / populated / %populated):")
    for name, stats in report.field_stats.items():
        lines.append(
            f"  {name}: types={list(stats.observed_types)} present={stats.count_present} "
            f"null={stats.count_null} empty={stats.count_empty} populated={stats.count_populated} "
            f"({stats.percentage_populated}%)"
        )
    lines.append("")

    ni = report.name_investigation
    lines.append("Name field investigation:")
    lines.append(f"  title present: {ni.title_present_count}/{ni.total}")
    lines.append(f"  aliases present (non-empty): {ni.aliases_present_count}/{ni.total}")
    lines.append(f"  structured given/middle/family-name fields found: {list(ni.structured_name_fields_found)}")
    lines.append(f"  -> structured name components available: {ni.structured_name_components_available}")
    lines.append("")

    dob = report.dob_investigation
    lines.append(f"Date-of-birth field investigation ({dob.field_name}):")
    lines.append(f"  observed types: {list(dob.observed_types)}")
    lines.append(f"  null or absent: {dob.null_or_absent_count}/{dob.total}")
    lines.append(f"  list-length distribution (populated only): {dob.list_length_counts}")
    lines.append(f"  exactly-one-value count: {dob.exactly_one_value_count}")
    lines.append(f"  multiple-value count: {dob.multiple_values_count}")
    lines.append(
        f"  format matches known 'Month D, YYYY' pattern: {dob.format_matches_known_pattern}; "
        f"does not match: {dob.format_does_not_match_known_pattern}"
    )
    lines.append(f"  -> safe to accept when exactly one value present: {dob.safe_to_accept_when_exactly_one}")
    lines.append("")

    loc = report.location_investigation
    lines.append("Location-adjacent field investigation (structure only; no semantic mapping implied):")
    for name in _LOCATION_ADJACENT_FIELDS:
        lines.append(
            f"  {name}: non-empty {loc.per_field_non_empty_counts[name]}/{loc.total}, "
            f"types={list(loc.per_field_types[name])}"
        )
    lines.append("")

    agency = report.agency_investigation
    lines.append("Agency / case-number field investigation:")
    lines.append(f"  ncic populated: {agency.ncic_populated_count}/{agency.total}")
    lines.append(f"  field_offices populated: {agency.field_offices_populated_count}/{agency.total}")
    lines.append(f"  dedicated case-number field found: {agency.dedicated_case_number_field_found}")
    lines.append("")

    mp = report.multi_person_signal
    lines.append("Multi-person structural signal (counts only; no title/description content inspected):")
    lines.append(f"  records with >1 dates_of_birth_used entries: {mp.dob_multi_value_count}/{mp.total}")
    lines.append(f"  image-count distribution: {mp.image_count_distribution}")

    return "\n".join(lines)
