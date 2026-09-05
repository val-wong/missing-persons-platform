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


class CaseDetailRead(CaseRead):
    person: PersonRead
