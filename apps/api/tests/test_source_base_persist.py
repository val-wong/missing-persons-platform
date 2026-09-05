from app.models.case import Case
from app.models.case_source import CaseSource
from app.models.person import Person
from app.models.source import Source
from app.models.source_record import SourceRecord
from ingestion.sources.base import (
    NormalizedRecord,
    PersistOutcome,
    persist_normalized_record,
    validate_normalized_record,
)


def _source(db_session) -> Source:
    source = Source(
        code="fbi", name="FBI", base_url="https://api.fbi.gov", source_type="government_agency"
    )
    db_session.add(source)
    db_session.flush()
    return source


def _source_record(db_session, source: Source, external_id: str = "ext-1") -> SourceRecord:
    record = SourceRecord(
        source_id=source.id,
        external_id=external_id,
        source_url=f"https://example.org/{external_id}",
        payload_hash="hash",
    )
    db_session.add(record)
    db_session.flush()
    return record


def test_validate_rejects_missing_display_name():
    record = NormalizedRecord(person_fields={"display_name": None}, case_fields={})
    result = validate_normalized_record(record)
    assert result.valid is False
    assert "display_name" in result.errors[0]


def test_validate_rejects_blank_display_name():
    record = NormalizedRecord(person_fields={"display_name": ""}, case_fields={})
    assert validate_normalized_record(record).valid is False


def test_validate_accepts_display_name_present():
    record = NormalizedRecord(person_fields={"display_name": "Jane Doe"}, case_fields={})
    assert validate_normalized_record(record).valid is True


def test_persist_creates_person_case_and_case_source(db_session):
    source = _source(db_session)
    source_record = _source_record(db_session, source)
    record = NormalizedRecord(
        person_fields={"display_name": "Jane Doe", "sex": "Female"},
        case_fields={"circumstances": "..."},
    )

    outcome = persist_normalized_record(db_session, source_record, record, link_method="test")
    db_session.commit()

    assert outcome is PersistOutcome.CREATED
    people = db_session.query(Person).all()
    cases = db_session.query(Case).all()
    links = db_session.query(CaseSource).all()
    assert len(people) == 1
    assert len(cases) == 1
    assert len(links) == 1
    assert people[0].display_name == "Jane Doe"
    assert cases[0].circumstances == "..."
    assert cases[0].person_id == people[0].id
    assert links[0].source_record_id == source_record.id
    assert links[0].case_id == cases[0].id
    assert links[0].link_method == "test"
    assert links[0].contributed_fields == {
        "display_name": "Jane Doe",
        "sex": "Female",
        "circumstances": "...",
    }


def test_persist_is_idempotent_for_unchanged_values(db_session):
    source = _source(db_session)
    source_record = _source_record(db_session, source)
    record = NormalizedRecord(person_fields={"display_name": "Jane Doe"}, case_fields={})

    first = persist_normalized_record(db_session, source_record, record, link_method="test")
    db_session.commit()
    second = persist_normalized_record(db_session, source_record, record, link_method="test")
    db_session.commit()

    assert first is PersistOutcome.CREATED
    assert second is PersistOutcome.UNCHANGED
    assert db_session.query(Person).count() == 1
    assert db_session.query(Case).count() == 1
    assert db_session.query(CaseSource).count() == 1


def test_persist_updates_same_source_records_case_on_changed_values(db_session):
    source = _source(db_session)
    source_record = _source_record(db_session, source)
    original = NormalizedRecord(
        person_fields={"display_name": "Jane Doe"}, case_fields={"circumstances": "v1"}
    )
    persist_normalized_record(db_session, source_record, original, link_method="test")
    db_session.commit()

    updated = NormalizedRecord(
        person_fields={"display_name": "Jane Doe"}, case_fields={"circumstances": "v2"}
    )
    outcome = persist_normalized_record(db_session, source_record, updated, link_method="test")
    db_session.commit()

    assert outcome is PersistOutcome.UPDATED
    assert db_session.query(Case).count() == 1  # same Case row updated, not duplicated
    case = db_session.query(Case).one()
    assert case.circumstances == "v2"
    link = db_session.query(CaseSource).one()
    assert link.contributed_fields["circumstances"] == "v2"


def test_persist_never_lets_a_different_source_record_merge_into_an_existing_case(db_session):
    """Two distinct SourceRecords normalizing to conflicting values must never merge
    into one Case. Phase 1 has no cross-source linkage step -- this is enforced
    structurally: persist_normalized_record only ever looks up an existing CaseSource
    by source_record_id, so a second, different SourceRecord always gets its own new
    Case rather than overwriting the first source's contribution.
    """
    source = _source(db_session)
    record_a = _source_record(db_session, source, external_id="a")
    record_b = _source_record(db_session, source, external_id="b")

    persist_normalized_record(
        db_session,
        record_a,
        NormalizedRecord(
            person_fields={"display_name": "Jane Doe"}, case_fields={"circumstances": "from A"}
        ),
        link_method="test",
    )
    db_session.commit()
    persist_normalized_record(
        db_session,
        record_b,
        NormalizedRecord(
            person_fields={"display_name": "Jane Doe"}, case_fields={"circumstances": "from B"}
        ),
        link_method="test",
    )
    db_session.commit()

    cases = db_session.query(Case).all()
    assert len(cases) == 2
    assert {c.circumstances for c in cases} == {"from A", "from B"}
    links = db_session.query(CaseSource).all()
    assert {link.contributed_fields["circumstances"] for link in links} == {"from A", "from B"}
