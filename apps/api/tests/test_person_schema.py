"""Unit tests for PersonRead's flat-columns -> nested-API-shape composition. No DB
needed: these construct a Person ORM instance directly (never persisted) since only
the Pydantic-level transformation in app/schemas/person.py is under test.
"""

import uuid
from datetime import datetime, timezone

from app.models.person import Person
from app.schemas.person import PersonRead


def _person(**overrides) -> Person:
    """Person.id normally comes from the ORM's `default=uuid.uuid4` on flush -- since
    these tests construct a Person without a session, it's supplied explicitly here."""
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid.uuid4(),
        display_name="SAMPLE PERSON",
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return Person(**defaults)


def test_height_and_weight_compose_into_nested_objects_with_explicit_nulls():
    person = _person()  # nothing set -- every height/weight field NULL
    read = PersonRead.model_validate(person)

    assert read.height.model_dump() == {
        "min_cm": None,
        "max_cm": None,
        "raw": None,
        "temporal_context": None,
    }
    assert read.weight.model_dump() == {
        "min_kg": None,
        "max_kg": None,
        "raw": None,
        "temporal_context": None,
    }


def test_populated_weight_composes_correctly():
    person = _person(
        weight_min_kg=59.0,
        weight_max_kg=63.5,
        weight_raw="130 to 140 pounds",
        weight_temporal_context=None,
    )
    read = PersonRead.model_validate(person)

    assert read.weight.min_kg == 59.0
    assert read.weight.max_kg == 63.5
    assert read.weight.raw == "130 to 140 pounds"
    assert read.weight.temporal_context is None


def test_photos_defaults_to_empty_list_not_null():
    person = _person(photos=None)
    read = PersonRead.model_validate(person)
    assert read.photos == []


def test_photos_pass_through_with_all_keys():
    person = _person(
        photos=[
            {
                "url": "https://example.gov/large.jpg",
                "full_url": "https://example.gov/original.jpg",
                "thumbnail_url": "https://example.gov/thumb.jpg",
                "caption": "A caption.",
            }
        ]
    )
    read = PersonRead.model_validate(person)

    assert len(read.photos) == 1
    photo = read.photos[0]
    assert photo.url == "https://example.gov/large.jpg"
    assert photo.full_url == "https://example.gov/original.jpg"
    assert photo.thumbnail_url == "https://example.gov/thumb.jpg"
    assert photo.caption == "A caption."


def test_photos_ordering_preserved():
    person = _person(
        photos=[
            {"url": "https://example.gov/1.jpg"},
            {"url": "https://example.gov/2.jpg"},
            {"url": "https://example.gov/3.jpg"},
        ]
    )
    read = PersonRead.model_validate(person)
    assert [p.url for p in read.photos] == [
        "https://example.gov/1.jpg",
        "https://example.gov/2.jpg",
        "https://example.gov/3.jpg",
    ]
