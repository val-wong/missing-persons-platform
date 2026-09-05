"""Read-only classification discovery report for stored FBI SourceSnapshots.

This module is ANALYSIS ONLY: it issues SELECT queries against SourceRecord /
SourceSnapshot and never writes to the database. Its purpose is to help decide, from
observed data, what a safe deterministic rule for identifying missing-person-related
FBI records might look like -- it does not implement that rule anywhere else.

It intentionally never prints or stores the *values* of identity-bearing fields (title,
details, description, remarks, images, physical details, locations, dates tied to an
individual). Where those fields matter structurally (are they present? what type are
they?), only field names, presence counts, and Python types are reported -- never
values.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql import func

from app.models.source import Source
from app.models.source_record import SourceRecord
from app.models.source_snapshot import SourceSnapshot

MISSING_PERSONS_SUBJECT = "Kidnappings and Missing Persons"

# Classification-relevant scalar fields we report value counts for directly -- these are
# short controlled-vocabulary labels (e.g. "na", "Main", "missing"), not personal data.
SCALAR_CLASSIFICATION_FIELDS = ("poster_classification", "person_classification", "status")

MISSING_SENTINEL = "<missing>"


# --------------------------------------------------------------------------------------
# Data access (read-only)
# --------------------------------------------------------------------------------------


def get_latest_snapshots(db: Session, source: Source) -> list[SourceSnapshot]:
    """Return the single latest SourceSnapshot for each *active* SourceRecord of `source`.

    "Latest" = greatest fetched_at, with snapshot id as a tiebreaker for determinism.
    Read-only: issues SELECT statements only.
    """
    row_number = (
        func.row_number()
        .over(
            partition_by=SourceSnapshot.source_record_id,
            order_by=(SourceSnapshot.fetched_at.desc(), SourceSnapshot.id.desc()),
        )
        .label("rn")
    )
    ranked = (
        select(SourceSnapshot, row_number)
        .join(SourceRecord, SourceRecord.id == SourceSnapshot.source_record_id)
        .where(SourceRecord.source_id == source.id, SourceRecord.active.is_(True))
        .subquery()
    )
    snapshot_alias = aliased(SourceSnapshot, ranked)
    stmt = select(snapshot_alias).where(ranked.c.rn == 1)
    return list(db.scalars(stmt))


# --------------------------------------------------------------------------------------
# Structural analysis (pure functions over already-fetched payloads)
# --------------------------------------------------------------------------------------


@dataclass
class SubjectsShapeObservations:
    """Structural shape of the `subjects` field across a set of payloads."""

    total: int = 0
    missing_key_count: int = 0
    null_count: int = 0
    non_list_type_count: int = 0
    empty_list_count: int = 0
    single_value_count: int = 0
    multi_value_count: int = 0
    max_len: int = 0
    distinct_value_count: int = 0

    @property
    def always_list_when_present(self) -> bool:
        """True if every non-null, present `subjects` value observed was a list."""
        return self.non_list_type_count == 0

    @property
    def can_be_multi_valued(self) -> bool:
        return self.multi_value_count > 0


def analyze_subjects_shape(payloads: list[dict[str, Any]]) -> SubjectsShapeObservations:
    obs = SubjectsShapeObservations(total=len(payloads))
    distinct_values: set[str] = set()

    for payload in payloads:
        if "subjects" not in payload:
            obs.missing_key_count += 1
            continue
        value = payload["subjects"]
        if value is None:
            obs.null_count += 1
            continue
        if not isinstance(value, list):
            obs.non_list_type_count += 1
            continue
        if len(value) == 0:
            obs.empty_list_count += 1
            continue
        obs.max_len = max(obs.max_len, len(value))
        if len(value) > 1:
            obs.multi_value_count += 1
        else:
            obs.single_value_count += 1
        for entry in value:
            if isinstance(entry, str):
                distinct_values.add(entry)

    obs.distinct_value_count = len(distinct_values)
    return obs


def analyze_subjects_values(payloads: list[dict[str, Any]]) -> Counter[str]:
    """Count how many records each distinct subject label appears on (deduped per record)."""
    counts: Counter[str] = Counter()
    for payload in payloads:
        value = payload.get("subjects")
        if isinstance(value, list):
            for subject in {v for v in value if isinstance(v, str)}:
                counts[subject] += 1
    return counts


def count_missing_persons_subject(payloads: list[dict[str, Any]]) -> int:
    return sum(
        1
        for payload in payloads
        if isinstance(payload.get("subjects"), list)
        and MISSING_PERSONS_SUBJECT in payload["subjects"]
    )


@dataclass
class FieldValueReport:
    """Value-count report for a scalar classification field."""

    value_counts: Counter[str] = field(default_factory=Counter)
    missing_count: int = 0  # key absent, null, or blank string
    present_count: int = 0


def analyze_scalar_field(payloads: list[dict[str, Any]], field_name: str) -> FieldValueReport:
    report = FieldValueReport()
    for payload in payloads:
        value = payload.get(field_name)
        if value is None or (isinstance(value, str) and not value.strip()):
            report.missing_count += 1
            continue
        report.present_count += 1
        report.value_counts[str(value)] += 1
    return report


def analyze_combinations(
    payloads: list[dict[str, Any]], fields: tuple[str, ...] = SCALAR_CLASSIFICATION_FIELDS
) -> Counter[tuple[str, ...]]:
    """Count how often each combination of the given scalar fields' values co-occurs."""
    combos: Counter[tuple[str, ...]] = Counter()
    for payload in payloads:
        key = tuple(
            str(payload[f])
            if payload.get(f) not in (None, "")
            else MISSING_SENTINEL
            for f in fields
        )
        combos[key] += 1
    return combos


@dataclass
class FieldPresence:
    """Structural-only presence/type report for one field name. Never stores values."""

    key_present_count: int = 0
    non_null_count: int = 0
    observed_types: tuple[str, ...] = ()


def field_presence_and_types(payloads: list[dict[str, Any]]) -> dict[str, FieldPresence]:
    """For every field name observed anywhere in `payloads`, report presence/null/type
    counts only. Actual field values are never read into the result.
    """
    field_names: set[str] = set()
    for payload in payloads:
        field_names.update(payload.keys())

    result: dict[str, FieldPresence] = {}
    for name in sorted(field_names):
        present = 0
        non_null = 0
        observed_types: set[str] = set()
        for payload in payloads:
            if name not in payload:
                continue
            present += 1
            value = payload[name]
            if value is not None:
                non_null += 1
                observed_types.add(type(value).__name__)
        result[name] = FieldPresence(
            key_present_count=present,
            non_null_count=non_null,
            observed_types=tuple(sorted(observed_types)),
        )
    return result


# --------------------------------------------------------------------------------------
# Top-level report
# --------------------------------------------------------------------------------------


@dataclass
class MissingPersonsSubsetReport:
    total_records: int
    poster_classification: FieldValueReport
    person_classification: FieldValueReport
    status: FieldValueReport
    field_presence: dict[str, FieldPresence]


@dataclass
class ClassificationReport:
    total_records: int
    subjects_shape: SubjectsShapeObservations
    subjects_value_counts: Counter[str]
    missing_persons_subject_count: int
    scalar_field_reports: dict[str, FieldValueReport]
    combination_counts: Counter[tuple[str, ...]]
    missing_persons_subset: MissingPersonsSubsetReport


def build_classification_report(db: Session, source: Source) -> ClassificationReport:
    """Assemble the full classification discovery report. Read-only; no writes."""
    snapshots = get_latest_snapshots(db, source)
    payloads = [s.payload for s in snapshots]

    subjects_shape = analyze_subjects_shape(payloads)
    subjects_value_counts = analyze_subjects_values(payloads)
    missing_persons_count = count_missing_persons_subject(payloads)

    scalar_field_reports = {
        f: analyze_scalar_field(payloads, f) for f in SCALAR_CLASSIFICATION_FIELDS
    }
    combination_counts = analyze_combinations(payloads)

    subset_payloads = [
        p
        for p in payloads
        if isinstance(p.get("subjects"), list) and MISSING_PERSONS_SUBJECT in p["subjects"]
    ]
    subset_report = MissingPersonsSubsetReport(
        total_records=len(subset_payloads),
        poster_classification=analyze_scalar_field(subset_payloads, "poster_classification"),
        person_classification=analyze_scalar_field(subset_payloads, "person_classification"),
        status=analyze_scalar_field(subset_payloads, "status"),
        field_presence=field_presence_and_types(subset_payloads),
    )

    return ClassificationReport(
        total_records=len(payloads),
        subjects_shape=subjects_shape,
        subjects_value_counts=subjects_value_counts,
        missing_persons_subject_count=missing_persons_count,
        scalar_field_reports=scalar_field_reports,
        combination_counts=combination_counts,
        missing_persons_subset=subset_report,
    )


# --------------------------------------------------------------------------------------
# Rendering (text only; never prints identity-bearing field values)
# --------------------------------------------------------------------------------------


def _render_value_counts(title: str, report: FieldValueReport, indent: str = "  ") -> list[str]:
    lines = [f"{title}: present={report.present_count} missing={report.missing_count}"]
    for value, count in report.value_counts.most_common():
        lines.append(f"{indent}{value!r}: {count}")
    return lines


def render_report(report: ClassificationReport) -> str:
    lines: list[str] = []
    lines.append("FBI classification discovery report (read-only, structural)")
    lines.append("=" * 60)
    lines.append(f"Total active FBI records inspected (latest snapshot each): {report.total_records}")
    lines.append("")

    lines.append("subjects: structural shape")
    s = report.subjects_shape
    lines.append(f"  key missing entirely: {s.missing_key_count}")
    lines.append(f"  null: {s.null_count}")
    lines.append(f"  non-list type: {s.non_list_type_count}")
    lines.append(f"  empty list: {s.empty_list_count}")
    lines.append(f"  single-value list: {s.single_value_count}")
    lines.append(f"  multi-value list: {s.multi_value_count}")
    lines.append(f"  max list length observed: {s.max_len}")
    lines.append(f"  distinct subject labels observed: {s.distinct_value_count}")
    lines.append(f"  always a list when present and non-null: {s.always_list_when_present}")
    lines.append(f"  can be multi-valued: {s.can_be_multi_valued}")
    lines.append("")

    lines.append("subjects: value counts (records containing each label; a record may count toward several)")
    for value, count in report.subjects_value_counts.most_common():
        lines.append(f"  {value!r}: {count}")
    lines.append("")

    lines.append(
        f"Records with subjects containing {MISSING_PERSONS_SUBJECT!r}: "
        f"{report.missing_persons_subject_count} / {report.total_records}"
    )
    lines.append("")

    lines.append("Scalar classification fields (all records)")
    for f in SCALAR_CLASSIFICATION_FIELDS:
        lines.extend(_render_value_counts(f, report.scalar_field_reports[f]))
    lines.append("")

    lines.append(f"Common ({', '.join(SCALAR_CLASSIFICATION_FIELDS)}) combinations")
    for combo, count in report.combination_counts.most_common():
        lines.append(f"  {combo}: {count}")
    lines.append("")

    subset = report.missing_persons_subset
    lines.append(f"Subset: subjects contains {MISSING_PERSONS_SUBJECT!r} (n={subset.total_records})")
    lines.extend(_render_value_counts("  poster_classification", subset.poster_classification, indent="    "))
    lines.extend(_render_value_counts("  person_classification", subset.person_classification, indent="    "))
    lines.extend(_render_value_counts("  status", subset.status, indent="    "))
    lines.append("")

    lines.append("Subset field presence/type structure (names and types only -- no values)")
    for name, presence in subset.field_presence.items():
        types = ", ".join(presence.observed_types) or "n/a"
        lines.append(
            f"  {name}: present={presence.key_present_count}/{subset.total_records} "
            f"non_null={presence.non_null_count} types=[{types}]"
        )

    return "\n".join(lines)
