"""Phase 1 deterministic FBI record classifier.

Classifies a single raw FBI Wanted API payload (as stored in `SourceSnapshot.payload`)
into a platform scope decision. This module is pure and read-only:

  - `classify_fbi_record` is a pure function of its input dict. Same input -> same
    output, always. It performs no I/O, no database access, and no network calls.
  - It never creates or modifies Person, Case, SourceRecord, or SourceSnapshot rows.
  - It never reads free-text/identity-bearing fields: title, details, description,
    remarks, images, locations, coordinates, dates_of_birth_used, place_of_birth, etc.
    are never inspected. Only `poster_classification` and `subjects` are read.
  - It never reads `person_classification` -- per product-scope decision, that field
    must not independently influence the outcome (see docs/fbi-classification.md).

Findings this classifier encodes come from the read-only discovery work in
`ingestion/sources/fbi/classification_report.py` and are written up in
docs/fbi-classification.md. The vocabularies below (`_KNOWN_POSTER_CLASSIFICATIONS`,
`_KNOWN_SUBJECT_LABELS`) are a closed list of values *empirically observed* in that
discovery work, not a documented FBI schema -- the FBI does not publish one. Anything
outside that closed list is deliberately routed to UNCLASSIFIED rather than guessed at
(see rule 5 in the task this module implements / docs/fbi-classification.md).

Normalization policy (documented; exercised by tests):
  - `poster_classification`: trimmed of surrounding whitespace, compared
    case-insensitively. Observed values look like machine-generated slugs
    (e.g. "missing", "kidnapping") where case is not meaningful.
  - `subjects` entries: trimmed of surrounding whitespace, compared with exact
    case-sensitive string equality. These are FBI-authored category labels
    (e.g. "ViCAP Missing Persons"); a differently-cased variant is treated as an
    unrecognized value (-> contributes to UNCLASSIFIED) rather than silently folded
    into a known label, since case is one of the few signals available that a label
    might not be the one we think it is.
  - `subjects` is only ever read when it is an actual JSON list. A non-list `subjects`
    value (e.g. a bare string) is never substring-matched -- it contributes no signal,
    exactly as required by "membership must be tested against individual normalized
    list values, not substring-matched against serialized JSON."
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------------
# Reason codes
# ---------------------------------------------------------------------------------

FBI_POSTER_CLASSIFICATION_MISSING = "FBI_POSTER_CLASSIFICATION_MISSING"
FBI_SUBJECT_VICAP_MISSING_PERSONS = "FBI_SUBJECT_VICAP_MISSING_PERSONS"

FBI_KIDNAPPING_OUT_OF_SCOPE = "FBI_KIDNAPPING_OUT_OF_SCOPE"
FBI_VICAP_UNIDENTIFIED_OUT_OF_SCOPE = "FBI_VICAP_UNIDENTIFIED_OUT_OF_SCOPE"
FBI_SUBJECT_KIDNAPPINGS_AND_MISSING_PERSONS_INSUFFICIENT = (
    "FBI_SUBJECT_KIDNAPPINGS_AND_MISSING_PERSONS_INSUFFICIENT"
)
FBI_SUBJECT_ECAP_OUT_OF_SCOPE = "FBI_SUBJECT_ECAP_OUT_OF_SCOPE"
FBI_SUBJECT_ENDANGERED_CHILD_ALERT_PROGRAM_OUT_OF_SCOPE = (
    "FBI_SUBJECT_ENDANGERED_CHILD_ALERT_PROGRAM_OUT_OF_SCOPE"
)
FBI_SUBJECT_HUMAN_TRAFFICKING_OUT_OF_SCOPE = "FBI_SUBJECT_HUMAN_TRAFFICKING_OUT_OF_SCOPE"

# Shared codes for known-but-unremarkable values that don't need their own named code.
FBI_POSTER_CLASSIFICATION_KNOWN_NON_MISSING = "FBI_POSTER_CLASSIFICATION_KNOWN_NON_MISSING"
FBI_SUBJECT_KNOWN_NON_MISSING_PERSON = "FBI_SUBJECT_KNOWN_NON_MISSING_PERSON"

# A value was present but does not match anything in the known vocabulary.
FBI_UNKNOWN_CLASSIFICATION = "FBI_UNKNOWN_CLASSIFICATION"
# No usable poster_classification or subjects value was present at all.
FBI_NO_CLASSIFICATION_SIGNAL = "FBI_NO_CLASSIFICATION_SIGNAL"


class ClassificationOutcome(str, Enum):
    IN_SCOPE = "IN_SCOPE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    UNCLASSIFIED = "UNCLASSIFIED"


class RecordType(str, Enum):
    MISSING_PERSON = "MISSING_PERSON"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ClassificationResult:
    outcome: ClassificationOutcome
    record_type: RecordType
    reason_codes: tuple[str, ...]


# ---------------------------------------------------------------------------------
# Known vocabularies (closed lists; see module docstring)
# ---------------------------------------------------------------------------------

_SIGNAL_POSITIVE = "positive"
_SIGNAL_KNOWN_NEGATIVE = "known_negative"
_SIGNAL_UNKNOWN = "unknown"


@dataclass(frozen=True)
class _Signal:
    code: str
    kind: str  # one of _SIGNAL_POSITIVE / _SIGNAL_KNOWN_NEGATIVE / _SIGNAL_UNKNOWN


# poster_classification values empirically observed (see docs/fbi-classification.md,
# 400-record sample) that are known to NOT independently indicate a missing person.
_KNOWN_POSTER_CLASSIFICATIONS_NON_QUALIFYING: dict[str, str] = {
    "default": FBI_POSTER_CLASSIFICATION_KNOWN_NON_MISSING,
    "information": FBI_POSTER_CLASSIFICATION_KNOWN_NON_MISSING,
    "fraudster": FBI_POSTER_CLASSIFICATION_KNOWN_NON_MISSING,
    "ecap": FBI_POSTER_CLASSIFICATION_KNOWN_NON_MISSING,
    "law-enforcement-assistance": FBI_POSTER_CLASSIFICATION_KNOWN_NON_MISSING,
    "ten": FBI_POSTER_CLASSIFICATION_KNOWN_NON_MISSING,
    "terrorist": FBI_POSTER_CLASSIFICATION_KNOWN_NON_MISSING,
    "kidnapping": FBI_KIDNAPPING_OUT_OF_SCOPE,
}

# subjects labels empirically observed that are known to NOT independently indicate a
# missing person (per rules 3 and 4). Labels called out by name in the task get their
# own reason code; the rest share a generic "known but not qualifying" code.
_KNOWN_SUBJECT_LABELS_NON_QUALIFYING: dict[str, str] = {
    "Kidnappings and Missing Persons": FBI_SUBJECT_KIDNAPPINGS_AND_MISSING_PERSONS_INSUFFICIENT,
    "ViCAP Unidentified Persons": FBI_VICAP_UNIDENTIFIED_OUT_OF_SCOPE,
    "ECAP": FBI_SUBJECT_ECAP_OUT_OF_SCOPE,
    "Endangered Child Alert Program": FBI_SUBJECT_ENDANGERED_CHILD_ALERT_PROGRAM_OUT_OF_SCOPE,
    "Human Trafficking": FBI_SUBJECT_HUMAN_TRAFFICKING_OUT_OF_SCOPE,
    # Remaining labels observed in the 400-record discovery sample; none of these are
    # called out individually by the task, so they share the generic code.
    "Seeking Information": FBI_SUBJECT_KNOWN_NON_MISSING_PERSON,
    "Cyber's Most Wanted": FBI_SUBJECT_KNOWN_NON_MISSING_PERSON,
    "Criminal Enterprise Investigations": FBI_SUBJECT_KNOWN_NON_MISSING_PERSON,
    "Additional Violent Crimes": FBI_SUBJECT_KNOWN_NON_MISSING_PERSON,
    "Indian Country": FBI_SUBJECT_KNOWN_NON_MISSING_PERSON,
    "ViCAP Homicides and Sexual Assaults": FBI_SUBJECT_KNOWN_NON_MISSING_PERSON,
    "Counterintelligence": FBI_SUBJECT_KNOWN_NON_MISSING_PERSON,
    "China Threat": FBI_SUBJECT_KNOWN_NON_MISSING_PERSON,
    "Most Wanted Fraudster": FBI_SUBJECT_KNOWN_NON_MISSING_PERSON,
    "Violent Crime - Murders": FBI_SUBJECT_KNOWN_NON_MISSING_PERSON,
    "Domestic Terrorism": FBI_SUBJECT_KNOWN_NON_MISSING_PERSON,
    "Law Enforcement Assistance": FBI_SUBJECT_KNOWN_NON_MISSING_PERSON,
    "White-Collar Crime": FBI_SUBJECT_KNOWN_NON_MISSING_PERSON,
    "Seeking Information - Terrorism": FBI_SUBJECT_KNOWN_NON_MISSING_PERSON,
    "Navajo": FBI_SUBJECT_KNOWN_NON_MISSING_PERSON,
    "Ten Most Wanted Fugitives": FBI_SUBJECT_KNOWN_NON_MISSING_PERSON,
    "Pine Ridge": FBI_SUBJECT_KNOWN_NON_MISSING_PERSON,
    "Crimes Against Children": FBI_SUBJECT_KNOWN_NON_MISSING_PERSON,
    "Iran": FBI_SUBJECT_KNOWN_NON_MISSING_PERSON,
    "Case of the Week": FBI_SUBJECT_KNOWN_NON_MISSING_PERSON,
    "John Doe": FBI_SUBJECT_KNOWN_NON_MISSING_PERSON,
    "Most Wanted Terrorists": FBI_SUBJECT_KNOWN_NON_MISSING_PERSON,
}

_VICAP_MISSING_PERSONS_LABEL = "ViCAP Missing Persons"


# ---------------------------------------------------------------------------------
# Field-level signal extraction
# ---------------------------------------------------------------------------------


def _classify_poster_classification(value: Any) -> _Signal | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if normalized == "missing":
        return _Signal(FBI_POSTER_CLASSIFICATION_MISSING, _SIGNAL_POSITIVE)
    code = _KNOWN_POSTER_CLASSIFICATIONS_NON_QUALIFYING.get(normalized)
    if code is not None:
        return _Signal(code, _SIGNAL_KNOWN_NEGATIVE)
    return _Signal(FBI_UNKNOWN_CLASSIFICATION, _SIGNAL_UNKNOWN)


def _classify_subjects(value: Any) -> list[_Signal]:
    # Rule 2 / module docstring: only ever inspect `subjects` as a real list of
    # individual values. A non-list value (e.g. a bare string) is never
    # substring-matched -- it simply yields no signal.
    if not isinstance(value, list):
        return []

    signals: list[_Signal] = []
    for entry in value:
        if not isinstance(entry, str):
            continue
        normalized = entry.strip()
        if not normalized:
            continue
        if normalized == _VICAP_MISSING_PERSONS_LABEL:
            signals.append(_Signal(FBI_SUBJECT_VICAP_MISSING_PERSONS, _SIGNAL_POSITIVE))
            continue
        code = _KNOWN_SUBJECT_LABELS_NON_QUALIFYING.get(normalized)
        if code is not None:
            signals.append(_Signal(code, _SIGNAL_KNOWN_NEGATIVE))
            continue
        signals.append(_Signal(FBI_UNKNOWN_CLASSIFICATION, _SIGNAL_UNKNOWN))
    return signals


# ---------------------------------------------------------------------------------
# Top-level classifier
# ---------------------------------------------------------------------------------


def classify_fbi_record(payload: dict[str, Any]) -> ClassificationResult:
    """Classify one raw FBI item payload. Pure function; no I/O, no DB writes.

    Only `poster_classification` and `subjects` are read. See module docstring for
    the full list of fields this deliberately never inspects.
    """
    poster_signal = _classify_poster_classification(payload.get("poster_classification"))
    subject_signals = _classify_subjects(payload.get("subjects"))

    all_signals = ([poster_signal] if poster_signal is not None else []) + subject_signals

    positive = [s for s in all_signals if s.kind == _SIGNAL_POSITIVE]
    unknown = [s for s in all_signals if s.kind == _SIGNAL_UNKNOWN]
    known_negative = [s for s in all_signals if s.kind == _SIGNAL_KNOWN_NEGATIVE]

    if not all_signals:
        return ClassificationResult(
            outcome=ClassificationOutcome.UNCLASSIFIED,
            record_type=RecordType.UNKNOWN,
            reason_codes=(FBI_NO_CLASSIFICATION_SIGNAL,),
        )

    reason_codes = tuple(sorted({s.code for s in all_signals}))

    if positive:
        return ClassificationResult(
            outcome=ClassificationOutcome.IN_SCOPE,
            record_type=RecordType.MISSING_PERSON,
            reason_codes=reason_codes,
        )

    # Rule 5: an unrecognized value must win over a known-negative one when there is
    # no positive signal -- we are not confident enough to call it OUT_OF_SCOPE.
    if unknown:
        return ClassificationResult(
            outcome=ClassificationOutcome.UNCLASSIFIED,
            record_type=RecordType.UNKNOWN,
            reason_codes=reason_codes,
        )

    assert known_negative  # all_signals is non-empty and neither positive nor unknown
    return ClassificationResult(
        outcome=ClassificationOutcome.OUT_OF_SCOPE,
        record_type=RecordType.OTHER,
        reason_codes=reason_codes,
    )
