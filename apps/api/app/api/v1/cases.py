"""Case search/list, detail, and provenance endpoints.

Query building follows one rule throughout: filters/sorting that touch Person fields
join to `Person` once (1:1 with Case, so this never multiplies rows); the `source`
filter and all provenance data go through `CaseSource -> SourceRecord -> Source`
generically (by `Source.code`), never by hardcoding "fbi" -- this is what lets the API
stay correct once a second source exists. See docs/architecture.md for why raw
SourceSnapshot payloads are never returned here: only already-normalized
`contributed_fields` provenance is exposed.
"""

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, contains_eager

from app.api.deps import get_db
from app.models.case import Case
from app.models.case_source import CaseSource
from app.models.person import Person
from app.models.source import Source
from app.models.source_record import SourceRecord
from app.schemas.case import (
    CaseDetailRead,
    CaseListResponse,
    CaseRead,
    CaseSourceRead,
    CaseSummaryRead,
)
from app.schemas.person import PersonRead

router = APIRouter(prefix="/cases", tags=["cases"])

DEFAULT_LIMIT = 25
MAX_LIMIT = 100

SortField = Literal["name", "missing_date", "created_at", "updated_at"]
SortOrder = Literal["asc", "desc"]

# Explicit allowlist -- never build ORDER BY from raw client input.
_SORT_COLUMNS = {
    "name": Person.display_name,
    "missing_date": Case.missing_date,
    "created_at": Case.created_at,
    "updated_at": Case.updated_at,
}


def _apply_filters(
    stmt: Select,
    *,
    q: str | None,
    first_name: str | None,
    last_name: str | None,
    sex: str | None,
    missing_state: str | None,
    missing_city: str | None,
    missing_country: str | None,
    missing_date_from: date | None,
    missing_date_to: date | None,
    hair_color: str | None,
    eye_color: str | None,
    source: str | None,
) -> Select:
    if q:
        stmt = stmt.where(Person.display_name.ilike(f"%{q}%"))
    if first_name:
        stmt = stmt.where(Person.given_name.ilike(f"%{first_name}%"))
    if last_name:
        stmt = stmt.where(Person.family_name.ilike(f"%{last_name}%"))
    if sex:
        stmt = stmt.where(func.lower(Person.sex) == sex.lower())
    if missing_state:
        stmt = stmt.where(Case.missing_state.ilike(f"%{missing_state}%"))
    if missing_city:
        stmt = stmt.where(Case.missing_city.ilike(f"%{missing_city}%"))
    if missing_country:
        stmt = stmt.where(Case.missing_country.ilike(f"%{missing_country}%"))
    if missing_date_from:
        stmt = stmt.where(Case.missing_date >= missing_date_from)
    if missing_date_to:
        stmt = stmt.where(Case.missing_date <= missing_date_to)
    if hair_color:
        stmt = stmt.where(Person.hair_color.ilike(f"%{hair_color}%"))
    if eye_color:
        stmt = stmt.where(Person.eye_color.ilike(f"%{eye_color}%"))
    if source:
        source_exists = (
            select(CaseSource.id)
            .join(SourceRecord, CaseSource.source_record_id == SourceRecord.id)
            .join(Source, SourceRecord.source_id == Source.id)
            .where(CaseSource.case_id == Case.id, func.lower(Source.code) == source.lower())
        )
        stmt = stmt.where(source_exists.exists())
    return stmt


def _primary_photo_url(photos: list[dict] | None) -> str | None:
    """Deterministic: the first photo entry in stored order, its `url` -- never chosen
    by any content/image analysis. `None` if no photos are available."""
    if not photos:
        return None
    return photos[0].get("url")


def _bulk_source_info(db: Session, case_ids: list[UUID]) -> dict[UUID, list[tuple[str, str]]]:
    """One query for the whole page of cases, not one per row. Maps case_id -> a list of
    (source_code, source_name) pairs, one per contributing SourceRecord."""
    if not case_ids:
        return {}
    rows = db.execute(
        select(CaseSource.case_id, Source.code, Source.name)
        .join(SourceRecord, CaseSource.source_record_id == SourceRecord.id)
        .join(Source, SourceRecord.source_id == Source.id)
        .where(CaseSource.case_id.in_(case_ids))
    ).all()
    result: dict[UUID, list[tuple[str, str]]] = {}
    for case_id, code, name in rows:
        result.setdefault(case_id, []).append((code, name))
    return result


def _case_sources(db: Session, case_id: UUID) -> list[CaseSourceRead]:
    rows = db.execute(
        select(CaseSource, SourceRecord, Source)
        .join(SourceRecord, CaseSource.source_record_id == SourceRecord.id)
        .join(Source, SourceRecord.source_id == Source.id)
        .where(CaseSource.case_id == case_id)
        .order_by(CaseSource.id.asc())
    ).all()
    return [
        CaseSourceRead(
            code=src.code,
            name=src.name,
            external_id=source_record.external_id,
            source_url=source_record.source_url,
            link_method=case_source.link_method,
            first_seen_at=source_record.first_seen_at,
            last_seen_at=source_record.last_seen_at,
            source_modified_at=source_record.source_modified_at,
            contributed_fields=case_source.contributed_fields,
        )
        for case_source, source_record, src in rows
    ]


@router.get("", response_model=CaseListResponse)
def list_cases(
    db: Session = Depends(get_db),
    q: str | None = Query(default=None, description="Free-text search against the person's display name"),
    first_name: str | None = Query(default=None),
    last_name: str | None = Query(default=None),
    sex: str | None = Query(default=None),
    missing_state: str | None = Query(default=None),
    missing_city: str | None = Query(default=None),
    missing_country: str | None = Query(default=None),
    missing_date_from: date | None = Query(default=None),
    missing_date_to: date | None = Query(default=None),
    hair_color: str | None = Query(default=None),
    eye_color: str | None = Query(default=None),
    source: str | None = Query(default=None, description="Source code, e.g. 'fbi'"),
    sort_by: SortField = Query(default="created_at"),
    sort_order: SortOrder = Query(default="desc"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> CaseListResponse:
    base = select(Case).join(Person, Case.person_id == Person.id)
    base = _apply_filters(
        base,
        q=q,
        first_name=first_name,
        last_name=last_name,
        sex=sex,
        missing_state=missing_state,
        missing_city=missing_city,
        missing_country=missing_country,
        missing_date_from=missing_date_from,
        missing_date_to=missing_date_to,
        hair_color=hair_color,
        eye_color=eye_color,
        source=source,
    )

    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0

    sort_column = _SORT_COLUMNS[sort_by]
    order_fn = sort_column.desc() if sort_order == "desc" else sort_column.asc()

    page_stmt = (
        base.options(contains_eager(Case.person))
        # Secondary tie-break on a unique column so pagination is stable even when the
        # primary sort key has duplicate/NULL values across rows.
        .order_by(order_fn, Case.id.asc())
        .limit(limit)
        .offset(offset)
    )
    cases = list(db.scalars(page_stmt).unique())

    source_info = _bulk_source_info(db, [c.id for c in cases])

    items = [
        CaseSummaryRead(
            case_id=c.id,
            person_id=c.person_id,
            display_name=c.person.display_name,
            sex=c.person.sex,
            missing_date=c.missing_date,
            missing_city=c.missing_city,
            missing_state=c.missing_state,
            missing_country=c.missing_country,
            primary_photo_url=_primary_photo_url(c.person.photos),
            investigating_agency=c.investigating_agency,
            source_codes=[code for code, _ in source_info.get(c.id, [])],
            source_names=[name for _, name in source_info.get(c.id, [])],
            updated_at=c.updated_at,
        )
        for c in cases
    ]
    return CaseListResponse(total=total, limit=limit, offset=offset, items=items)


@router.get("/{case_id}", response_model=CaseDetailRead)
def get_case(case_id: UUID, db: Session = Depends(get_db)) -> CaseDetailRead:
    stmt = (
        select(Case)
        .join(Person, Case.person_id == Person.id)
        .options(contains_eager(Case.person))
        .where(Case.id == case_id)
    )
    case = db.scalars(stmt).unique().one_or_none()
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    base = CaseRead.model_validate(case)
    return CaseDetailRead(
        **base.model_dump(),
        person=PersonRead.model_validate(case.person),
        sources=_case_sources(db, case_id),
    )


@router.get("/{case_id}/sources", response_model=list[CaseSourceRead])
def get_case_sources(case_id: UUID, db: Session = Depends(get_db)) -> list[CaseSourceRead]:
    exists = db.scalar(select(Case.id).where(Case.id == case_id))
    if exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    return _case_sources(db, case_id)
