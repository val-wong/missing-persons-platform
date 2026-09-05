"""End-to-end (DB-backed, mocked HTTP) tests for the classify -> normalize -> validate
-> persist canonical stages wired into ingestion.sources.fbi.service.run_fbi_ingestion.
Raw-layer behavior is already covered by test_fbi_service.py and is not re-tested here.
"""

import pytest

from app.models.case import Case
from app.models.case_source import CaseSource
from app.models.person import Person
from app.models.source import Source
from ingestion.sources.fbi.client import FBIListResponse
from ingestion.sources.fbi.service import FBI_LINK_METHOD, run_fbi_ingestion


class FakeFBIClient:
    """Minimal stand-in for FBIApiClient: yields pre-built pages."""

    def __init__(self, pages: list[FBIListResponse]):
        self._pages = pages

    def iter_pages(self, start_page: int = 1, page_size: int = 20, max_pages: int | None = None):
        yielded = 0
        for page in self._pages:
            if max_pages is not None and yielded >= max_pages:
                return
            yield page
            yielded += 1


def _in_scope_item(uid: str = "m1", title: str = "JANE DOE", description: str = "Last seen near the river.") -> dict:
    return {
        "uid": uid,
        "url": f"https://www.fbi.gov/wanted/kidnap/{uid}",
        "modified": "2026-01-01T00:00:00+00:00",
        "title": title,
        "sex": "Female",
        "description": description,
        "dates_of_birth_used": ["January 1, 2000"],
        "poster_classification": "missing",
        "subjects": ["ViCAP Missing Persons"],
    }


def _out_of_scope_item(uid: str = "w1") -> dict:
    return {
        "uid": uid,
        "url": f"https://www.fbi.gov/wanted/fugitives/{uid}",
        "modified": "2026-01-01T00:00:00+00:00",
        "title": "JOHN SMITH",
        "poster_classification": "ten",
        "subjects": ["Ten Most Wanted Fugitives"],
    }


@pytest.fixture()
def fbi_source(db_session) -> Source:
    source = Source(
        code="fbi",
        name="Federal Bureau of Investigation",
        base_url="https://api.fbi.gov",
        source_type="government_agency",
    )
    db_session.add(source)
    db_session.flush()
    return source


def test_in_scope_record_creates_canonical_person_case_and_link(db_session, fbi_source):
    page = FBIListResponse(total=1, page=1, items=[_in_scope_item()])
    stats = run_fbi_ingestion(db_session, FakeFBIClient([page]), max_pages=1)

    assert stats.canonical_created == 1
    person = db_session.query(Person).one()
    case = db_session.query(Case).one()
    link = db_session.query(CaseSource).one()
    assert person.display_name == "JANE DOE"
    assert person.sex == "Female"
    assert case.circumstances == "Last seen near the river."
    assert case.investigating_agency == "Federal Bureau of Investigation"
    assert case.case_status is None  # never guessed for FBI -- see docs/fbi-normalization.md
    assert link.link_method == FBI_LINK_METHOD


def test_out_of_scope_record_creates_no_canonical_rows(db_session, fbi_source):
    page = FBIListResponse(total=1, page=1, items=[_out_of_scope_item()])
    stats = run_fbi_ingestion(db_session, FakeFBIClient([page]), max_pages=1)

    assert stats.canonical_out_of_scope == 1
    assert db_session.query(Person).count() == 0
    assert db_session.query(Case).count() == 0
    assert db_session.query(CaseSource).count() == 0


def test_rerunning_with_unchanged_payload_does_not_duplicate_canonical_rows(db_session, fbi_source):
    page = FBIListResponse(total=1, page=1, items=[_in_scope_item()])
    run_fbi_ingestion(db_session, FakeFBIClient([page]), max_pages=1)
    stats = run_fbi_ingestion(db_session, FakeFBIClient([page]), max_pages=1)

    assert stats.canonical_created == 0
    assert stats.canonical_updated == 0
    assert db_session.query(Person).count() == 1
    assert db_session.query(Case).count() == 1
    assert db_session.query(CaseSource).count() == 1


def test_changed_payload_updates_existing_canonical_case_not_a_new_one(db_session, fbi_source):
    page1 = FBIListResponse(total=1, page=1, items=[_in_scope_item(description="Original circumstances.")])
    run_fbi_ingestion(db_session, FakeFBIClient([page1]), max_pages=1)

    page2 = FBIListResponse(total=1, page=1, items=[_in_scope_item(description="Updated circumstances.")])
    stats = run_fbi_ingestion(db_session, FakeFBIClient([page2]), max_pages=1)

    assert stats.canonical_updated == 1
    assert db_session.query(Person).count() == 1
    assert db_session.query(Case).count() == 1
    case = db_session.query(Case).one()
    assert case.circumstances == "Updated circumstances."


def test_physical_detail_fields_are_persisted_and_recorded_in_contributed_fields(db_session, fbi_source):
    item = _in_scope_item(uid="m-physical")
    item.update(
        hair="black",
        hair_raw="Black (shoulder length)",
        eyes="brown",
        eyes_raw="Brown",
        aliases=["Johnny", "J.D."],
        scars_and_marks="Scar on left forearm.",
    )
    page = FBIListResponse(total=1, page=1, items=[item])
    stats = run_fbi_ingestion(db_session, FakeFBIClient([page]), max_pages=1)

    assert stats.canonical_created == 1
    person = db_session.query(Person).one()
    link = db_session.query(CaseSource).one()

    assert person.hair_color == "Black (shoulder length)"
    assert person.eye_color == "Brown"
    assert person.aliases == ["Johnny", "J.D."]
    assert person.distinguishing_characteristics == "Scar on left forearm."

    # Provenance: contributed_fields must reflect exactly what this SourceRecord
    # contributed, including these newly-mapped fields.
    assert link.contributed_fields["hair_color"] == "Black (shoulder length)"
    assert link.contributed_fields["eye_color"] == "Brown"
    assert link.contributed_fields["aliases"] == ["Johnny", "J.D."]
    assert link.contributed_fields["distinguishing_characteristics"] == "Scar on left forearm."


def test_physical_detail_fields_stay_none_when_source_fields_absent(db_session, fbi_source):
    page = FBIListResponse(total=1, page=1, items=[_in_scope_item()])
    stats = run_fbi_ingestion(db_session, FakeFBIClient([page]), max_pages=1)

    assert stats.canonical_created == 1
    person = db_session.query(Person).one()
    assert person.hair_color is None
    assert person.eye_color is None
    assert person.aliases is None
    assert person.distinguishing_characteristics is None


def test_weight_and_media_fields_are_persisted_and_recorded_in_contributed_fields(db_session, fbi_source):
    item = _in_scope_item(uid="m-weight-media")
    item.update(
        weight="130 to 140 pounds",
        weight_min=130,
        weight_max=140,
        images=[
            {
                "large": "https://example.gov/large.jpg",
                "original": "https://example.gov/original.jpg",
                "thumb": "https://example.gov/thumb.jpg",
                "caption": "A caption.",
            }
        ],
    )
    page = FBIListResponse(total=1, page=1, items=[item])
    stats = run_fbi_ingestion(db_session, FakeFBIClient([page]), max_pages=1)

    assert stats.canonical_created == 1
    person = db_session.query(Person).one()
    link = db_session.query(CaseSource).one()

    assert person.weight_min_kg == 59.0
    assert person.weight_max_kg == 63.5
    assert person.weight_raw == "130 to 140 pounds"
    assert person.photos == [
        {
            "url": "https://example.gov/large.jpg",
            "full_url": "https://example.gov/original.jpg",
            "thumbnail_url": "https://example.gov/thumb.jpg",
            "caption": "A caption.",
        }
    ]

    assert link.contributed_fields["weight_min_kg"] == 59.0
    assert link.contributed_fields["weight_max_kg"] == 63.5
    assert link.contributed_fields["weight_raw"] == "130 to 140 pounds"
    assert link.contributed_fields["weight_temporal_context"] is None
    assert link.contributed_fields["photos"] == person.photos


def test_fbi_height_stays_null_and_absent_from_contributed_fields(db_session, fbi_source):
    """Even though this item reports height_min/height_max, FBI height mapping is
    deliberately disabled (unit confidence only MEDIUM) -- canonical height columns
    must stay NULL and out of contributed_fields entirely."""
    item = _in_scope_item(uid="m-height")
    item.update(height_min=66, height_max=66)
    page = FBIListResponse(total=1, page=1, items=[item])
    stats = run_fbi_ingestion(db_session, FakeFBIClient([page]), max_pages=1)

    assert stats.canonical_created == 1
    person = db_session.query(Person).one()
    link = db_session.query(CaseSource).one()

    assert person.height_min_cm is None
    assert person.height_max_cm is None
    assert person.height_raw is None
    assert person.height_temporal_context is None
    for field_name in ("height_min_cm", "height_max_cm", "height_raw", "height_temporal_context"):
        assert field_name not in link.contributed_fields


def test_malformed_item_with_blank_title_fails_validation_without_aborting_batch(db_session, fbi_source):
    good = _in_scope_item(uid="good-1")
    bad = _in_scope_item(uid="bad-1", title="   ")
    page = FBIListResponse(total=2, page=1, items=[good, bad])
    stats = run_fbi_ingestion(db_session, FakeFBIClient([page]), max_pages=1)

    assert stats.canonical_created == 1
    assert stats.canonical_validation_failed == 1
    assert db_session.query(Person).count() == 1
