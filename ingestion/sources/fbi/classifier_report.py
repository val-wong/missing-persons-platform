"""Read-only aggregate report: run the Phase 1 FBI classifier over stored data.

Like `classification_report.py`, this module only issues SELECT queries and never
writes to the database. It reports counts only -- outcome counts, record_type counts,
and reason-code counts -- and never prints per-record identifying data.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.source import Source
from ingestion.sources.fbi.classification_report import get_latest_snapshots
from ingestion.sources.fbi.classifier import ClassificationOutcome, RecordType, classify_fbi_record


@dataclass
class ClassifierRunReport:
    total_records: int = 0
    outcome_counts: Counter[str] = field(default_factory=Counter)
    record_type_counts: Counter[str] = field(default_factory=Counter)
    reason_code_counts: Counter[str] = field(default_factory=Counter)


def build_classifier_report(db: Session, source: Source) -> ClassifierRunReport:
    """Classify the latest snapshot of every active FBI record and aggregate results.

    Read-only: issues SELECT queries only, performs no writes. Classification itself
    is a pure function (see `classifier.classify_fbi_record`) -- this function's only
    job is to fetch payloads and tally outcomes.
    """
    snapshots = get_latest_snapshots(db, source)
    report = ClassifierRunReport(total_records=len(snapshots))

    for snapshot in snapshots:
        result = classify_fbi_record(snapshot.payload)
        report.outcome_counts[result.outcome.value] += 1
        report.record_type_counts[result.record_type.value] += 1
        for code in result.reason_codes:
            report.reason_code_counts[code] += 1

    return report


def render_classifier_report(report: ClassifierRunReport) -> str:
    lines: list[str] = []
    lines.append("FBI Phase 1 classifier report (read-only, aggregate counts only)")
    lines.append("=" * 60)
    lines.append(f"Total active FBI records classified: {report.total_records}")
    lines.append("")

    lines.append("Outcome counts:")
    for outcome in ClassificationOutcome:
        lines.append(f"  {outcome.value}: {report.outcome_counts.get(outcome.value, 0)}")
    lines.append("")

    lines.append("Record type counts:")
    for record_type in RecordType:
        lines.append(f"  {record_type.value}: {report.record_type_counts.get(record_type.value, 0)}")
    lines.append("")

    lines.append("Reason-code counts:")
    for code, count in report.reason_code_counts.most_common():
        lines.append(f"  {code}: {count}")

    return "\n".join(lines)
