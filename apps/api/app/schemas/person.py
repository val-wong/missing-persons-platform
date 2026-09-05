from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator


class HeightRead(BaseModel):
    min_cm: float | None = None
    max_cm: float | None = None
    raw: str | None = None
    temporal_context: str | None = None


class WeightRead(BaseModel):
    min_kg: float | None = None
    max_kg: float | None = None
    raw: str | None = None
    temporal_context: str | None = None


class PhotoRead(BaseModel):
    # Defaults (not just a nullable type) so a stored photo object that omits a key
    # entirely -- not just sets it to null -- still validates cleanly; FBI normalization
    # always emits all four keys, but this is a public API contract, not only a mirror
    # of that one adapter's behavior.
    url: str | None = None
    full_url: str | None = None
    thumbnail_url: str | None = None
    caption: str | None = None


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
    height: HeightRead
    weight: WeightRead
    hair_color: str | None
    eye_color: str | None
    distinguishing_characteristics: str | None
    photos: list[PhotoRead]
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _compose_nested_measurements(cls, obj: Any) -> Any:
        """`Person` stores height/weight as flat, typed columns (height_min_cm,
        height_max_cm, height_raw, height_temporal_context, and the weight
        equivalents) -- see docs/fbi-normalization.md for why. This composes the
        public API's nested height/weight objects from those flat columns without
        changing DB storage or requiring a join. `photos` already has the right shape
        in the DB (a JSONB list of {url, full_url, thumbnail_url, caption} objects);
        it's only ever defaulted here from `None` to `[]` so clients never need to
        null-check the list itself, only its items' fields.

        A plain dict (e.g. a test constructing a PersonRead directly) is passed
        through unchanged, already in the nested shape.
        """
        if isinstance(obj, dict):
            return obj
        return {
            "id": obj.id,
            "given_name": obj.given_name,
            "middle_name": obj.middle_name,
            "family_name": obj.family_name,
            "suffix": obj.suffix,
            "display_name": obj.display_name,
            "aliases": obj.aliases,
            "date_of_birth": obj.date_of_birth,
            "age": obj.age,
            "sex": obj.sex,
            "height": {
                "min_cm": obj.height_min_cm,
                "max_cm": obj.height_max_cm,
                "raw": obj.height_raw,
                "temporal_context": obj.height_temporal_context,
            },
            "weight": {
                "min_kg": obj.weight_min_kg,
                "max_kg": obj.weight_max_kg,
                "raw": obj.weight_raw,
                "temporal_context": obj.weight_temporal_context,
            },
            "hair_color": obj.hair_color,
            "eye_color": obj.eye_color,
            "distinguishing_characteristics": obj.distinguishing_characteristics,
            "photos": obj.photos or [],
            "created_at": obj.created_at,
            "updated_at": obj.updated_at,
        }
