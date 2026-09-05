import uuid
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.case import Case
from app.models.person import Person
from app.models.source import Source
from app.models.source_record import SourceRecord


def test_create_person_and_case(db_session):
    person = Person(display_name="Jane Doe", given_name="Jane", family_name="Doe")
    db_session.add(person)
    db_session.flush()

    case = Case(
        person_id=person.id,
        case_status="open",
        missing_date=date(2024, 1, 1),
        missing_state="CA",
    )
    db_session.add(case)
    db_session.commit()

    assert isinstance(person.id, uuid.UUID)
    assert isinstance(case.id, uuid.UUID)
    assert case.person_id == person.id


def test_source_creation(db_session):
    source = Source(
        code="fbi",
        name="Federal Bureau of Investigation",
        base_url="https://www.fbi.gov",
        source_type="government_agency",
    )
    db_session.add(source)
    db_session.commit()

    assert source.id is not None
    assert source.active is True


def test_source_code_must_be_unique(db_session):
    db_session.add(
        Source(code="fbi", name="FBI", base_url="https://www.fbi.gov", source_type="government_agency")
    )
    db_session.commit()

    db_session.add(
        Source(code="fbi", name="FBI Duplicate", base_url="https://www.fbi.gov", source_type="government_agency")
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_source_record_unique_per_source_and_external_id(db_session):
    source = Source(code="namus", name="NamUs", base_url="https://www.namus.gov", source_type="government_agency")
    db_session.add(source)
    db_session.flush()

    db_session.add(
        SourceRecord(
            source_id=source.id,
            external_id="abc-123",
            source_url="https://www.namus.gov/cases/abc-123",
            payload_hash="hash1",
        )
    )
    db_session.commit()

    db_session.add(
        SourceRecord(
            source_id=source.id,
            external_id="abc-123",
            source_url="https://www.namus.gov/cases/abc-123",
            payload_hash="hash2",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
