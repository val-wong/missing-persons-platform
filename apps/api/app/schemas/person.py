from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PersonRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    given_name: str | None
    middle_name: str | None
    family_name: str | None
    suffix: str | None
    display_name: str
    aliases: list[str] | None
    date_of_birth: date | None
    age: int | None
    sex: str | None
    height_cm: float | None
    weight_kg: float | None
    hair_color: str | None
    eye_color: str | None
    distinguishing_characteristics: str | None
    photo_urls: list[str] | None
    created_at: datetime
    updated_at: datetime
