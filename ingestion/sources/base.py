"""Common source-adapter contract: fetch -> parse -> normalize -> validate -> persist.

Every ingestion source is expected to follow this shape (see docs/architecture.md).
This module defines the two pieces that are genuinely source-agnostic and reusable by
any adapter, so that adding a new source is mostly "write `normalize()` for that
source's fields" rather than reinventing how normalized output gets persisted:

  - `NormalizedRecord` -- the common shape normalization produces, regardless of source.
  - `persist_normalized_record` -- the shared, provenance-preserving persistence rule.

Fetch/parse/classify stages stay source-specific (e.g. `ingestion/sources/fbi/`) because
they depend entirely on that source's transport and data shape; there is nothing generic
to share there yet with only one source implemented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.case_source import CaseSource
from app.models.person import Person
from app.models.source_record import SourceRecord

# Person columns that must never be silently defaulted -- normalization producing no
# value for one of these means the record cannot be persisted at all (see `validate`).
REQUIRED_PERSON_FIELDS: tuple[str, ...] = ("display_name",)


def _json_safe(value: Any) -> Any:
    """Coerce Python types Person/Case columns use but JSON doesn't support natively
    (date/datetime) into a JSON-storable form, for `contributed_fields` (a JSONB
    column). Applied only to that provenance copy -- the values set on the actual
    Person/Case ORM attributes keep their native Python types."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


@dataclass
class NormalizedRecord:
    """The full set of canonical field values normalization produced for one raw item.

    `person_fields` / `case_fields` map directly onto `Person`/`Case` column names.
    A field a source did not report should simply be absent (or `None`) here -- never
    guessed or defaulted. This dataclass carries no source-specific logic; only the
    values a specific adapter's `normalize()` function decided to populate.
    """

    person_fields: dict[str, Any] = field(default_factory=dict)
    case_fields: dict[str, Any] = field(default_factory=dict)

    def contributed_fields(self) -> dict[str, Any]:
        """JSON-safe flat view of everything this record contributed, for CaseSource
        provenance (a JSONB column)."""
        return {
            name: _json_safe(value)
            for name, value in {**self.person_fields, **self.case_fields}.items()
        }


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: tuple[str, ...] = ()


def validate_normalized_record(record: NormalizedRecord) -> ValidationResult:
    """Reject normalized output that can't be safely persisted. Deliberately minimal:
    only checks the one column that is genuinely NOT NULL (`Person.display_name`).
    Every other canonical field is nullable by design (see docs/architecture.md) and
    is not something normalization can get "wrong" in a way validation should police --
    that's normalize()'s own fail-closed responsibility (e.g. a malformed date parses
    to None, it doesn't fail validation).
    """
    errors = [
        f"{name} is required but normalization produced no value"
        for name in REQUIRED_PERSON_FIELDS
        if not record.person_fields.get(name)
    ]
    return ValidationResult(valid=not errors, errors=tuple(errors))


class PersistOutcome(str, Enum):
    CREATED = "created"  # first time this SourceRecord was normalized: new Person+Case
    UPDATED = "updated"  # same SourceRecord, contributed values changed
    UNCHANGED = "unchanged"  # same SourceRecord, contributed values identical


def persist_normalized_record(
    db: Session,
    source_record: SourceRecord,
    record: NormalizedRecord,
    link_method: str,
) -> PersistOutcome:
    """Idempotently persist one normalized record's canonical fields.

    Reconciliation rule (Phase 1): a `Case`'s canonical fields may only ever be
    written by the *same* `SourceRecord` that originally produced it -- enforced here
    structurally by keying the lookup on `source_record_id`, not by name/similarity
    matching. This function never links a second `SourceRecord` to an existing `Case`;
    cross-source linkage (and the conflict-resolution policy it would require) is
    explicitly deferred (see docs/architecture.md and requirement 7 of the Phase 1
    brief). That means two sources disagreeing on a field cannot be silently merged
    here -- there is simply no code path in Phase 1 that lets one source's write touch
    a Case another source produced.

    `contributed_fields` on the resulting `CaseSource` row always reflects exactly what
    this call's `record` contained, independent of prior state -- so what a source
    literally reported stays inspectable even after an update.
    """
    existing_link = db.scalar(
        select(CaseSource).where(CaseSource.source_record_id == source_record.id)
    )
    contributed = record.contributed_fields()

    if existing_link is None:
        person = Person(**record.person_fields)
        db.add(person)
        db.flush()  # assign person.id for the case FK
        case = Case(person_id=person.id, **record.case_fields)
        db.add(case)
        db.flush()  # assign case.id for the case_source FK
        db.add(
            CaseSource(
                case_id=case.id,
                source_record_id=source_record.id,
                link_method=link_method,
                contributed_fields=contributed,
            )
        )
        return PersistOutcome.CREATED

    if existing_link.contributed_fields == contributed:
        return PersistOutcome.UNCHANGED

    case = db.get(Case, existing_link.case_id)
    person = db.get(Person, case.person_id)
    for name, value in record.person_fields.items():
        setattr(person, name, value)
    for name, value in record.case_fields.items():
        setattr(case, name, value)
    existing_link.contributed_fields = contributed
    return PersistOutcome.UPDATED
