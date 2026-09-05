from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.person import PersonRead


class CaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    person_id: UUID
    case_status: str | None
    missing_date: date | None
    missing_city: str | None
    missing_county: str | None
    missing_state: str | None
    missing_country: str | None
    age_at_missing: int | None
    circumstances: str | None
    investigating_agency: str | None
    agency_case_number: str | None
    created_at: datetime
    updated_at: datetime


class CaseSourceRead(BaseModel):
    """Provenance for one SourceRecord's contribution to a Case -- deliberately not the
    raw SourceSnapshot payload (see docs/architecture.md): only the already-normalized
    `contributed_fields` a source produced, plus enough identifying/timing metadata to
    trace the claim back to its source. Shared by CaseDetailRead.sources and the
    dedicated GET /cases/{id}/sources endpoint."""

    model_config = ConfigDict(from_attributes=True)

    source_code: str
    source_name: str
    external_id: str
    source_url: str
    link_method: str
    first_seen_at: datetime
    last_seen_at: datetime
    source_modified_at: datetime | None
    contributed_fields: dict | None


class CaseSummaryRead(BaseModel):
    """Compact per-case shape for search/list results -- not every internal field, and
    never the raw SourceSnapshot payload. See docs for the full field list."""

    case_id: UUID
    person_id: UUID
    display_name: str
    sex: str | None
    missing_date: date | None
    missing_city: str | None
    missing_state: str | None
    missing_country: str | None
    primary_photo_url: str | None
    investigating_agency: str | None
    source_names: list[str]
    updated_at: datetime


class CaseListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[CaseSummaryRead]


class CaseDetailRead(CaseRead):
    person: PersonRead
    sources: list[CaseSourceRead]
