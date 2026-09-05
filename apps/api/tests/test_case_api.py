"""API-level tests for the searchable case list/detail/provenance endpoints. All data is
seeded directly via the ORM (no ingestion pipeline involved) -- these tests exercise the
API layer, not normalization. Every name/value used is synthetic.
"""

from datetime import date, timedelta

from sqlalchemy import event

from app.models.case import Case
from app.models.case_source import CaseSource
from app.models.person import Person
from app.models.source import Source
from app.models.source_record import SourceRecord

API = "/api/v1/cases"


def _make_source(db_session, code: str, name: str | None = None) -> Source:
    existing = db_session.query(Source).filter_by(code=code).one_or_none()
    if existing is not None:
        return existing
    source = Source(
        code=code,
        name=name or code.upper(),
        base_url=f"https://example.org/{code}",
        source_type="government_agency",
    )
    db_session.add(source)
    db_session.flush()
    return source


def _make_case(
    db_session,
    *,
    source: Source,
    external_id: str,
    display_name: str = "SAMPLE PERSON",
    sex: str | None = None,
    hair_color: str | None = None,
    eye_color: str | None = None,
    photos: list[dict] | None = None,
    missing_date: date | None = None,
    missing_city: str | None = None,
    missing_state: str | None = None,
    missing_country: str | None = None,
    investigating_agency: str | None = None,
    contributed_fields: dict | None = None,
) -> Case:
    record = SourceRecord(
        source_id=source.id,
        external_id=external_id,
        source_url=f"https://example.org/{source.code}/{external_id}",
        payload_hash=f"hash-{external_id}",
    )
    db_session.add(record)
    db_session.flush()

    person = Person(
        display_name=display_name,
        sex=sex,
        hair_color=hair_color,
        eye_color=eye_color,
        photos=photos,
    )
    db_session.add(person)
    db_session.flush()

    case = Case(
        person_id=person.id,
        missing_date=missing_date,
        missing_city=missing_city,
        missing_state=missing_state,
        missing_country=missing_country,
        investigating_agency=investigating_agency,
    )
    db_session.add(case)
    db_session.flush()

    db_session.add(
        CaseSource(
            case_id=case.id,
            source_record_id=record.id,
            link_method="test",
            contributed_fields=contributed_fields or {"display_name": display_name},
        )
    )
    db_session.flush()
    return case


# --- search / filters ---------------------------------------------------------------


def test_search_by_name_query(client, db_session):
    source = _make_source(db_session, "fbi")
    _make_case(db_session, source=source, external_id="1", display_name="ALEX SAMPLE")
    _make_case(db_session, source=source, external_id="2", display_name="JORDAN OTHER")

    resp = client.get(API, params={"q": "sample"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["display_name"] == "ALEX SAMPLE"


def test_filter_by_missing_state(client, db_session):
    source = _make_source(db_session, "fbi")
    _make_case(db_session, source=source, external_id="1", missing_state="Nevada")
    _make_case(db_session, source=source, external_id="2", missing_state="Ohio")

    resp = client.get(API, params={"missing_state": "nevada"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_filter_by_sex(client, db_session):
    source = _make_source(db_session, "fbi")
    _make_case(db_session, source=source, external_id="1", sex="Female")
    _make_case(db_session, source=source, external_id="2", sex="Male")

    resp = client.get(API, params={"sex": "female"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_filter_by_hair_color(client, db_session):
    source = _make_source(db_session, "fbi")
    _make_case(db_session, source=source, external_id="1", hair_color="Brown, Curly")
    _make_case(db_session, source=source, external_id="2", hair_color="Black")

    resp = client.get(API, params={"hair_color": "brown"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_filter_by_eye_color(client, db_session):
    source = _make_source(db_session, "fbi")
    _make_case(db_session, source=source, external_id="1", eye_color="Green/Hazel")
    _make_case(db_session, source=source, external_id="2", eye_color="Blue")

    resp = client.get(API, params={"eye_color": "hazel"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_filter_by_source(client, db_session):
    fbi = _make_source(db_session, "fbi")
    other = _make_source(db_session, "other")
    _make_case(db_session, source=fbi, external_id="1")
    _make_case(db_session, source=other, external_id="2")

    resp = client.get(API, params={"source": "fbi"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["source_names"] == ["FBI"]


def test_filter_by_missing_date_range(client, db_session):
    source = _make_source(db_session, "fbi")
    _make_case(db_session, source=source, external_id="1", missing_date=date(2020, 1, 1))
    _make_case(db_session, source=source, external_id="2", missing_date=date(2023, 6, 15))

    resp = client.get(API, params={"missing_date_from": "2022-01-01", "missing_date_to": "2024-01-01"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_combined_filters(client, db_session):
    source = _make_source(db_session, "fbi")
    _make_case(
        db_session, source=source, external_id="1", sex="Female", missing_state="Texas", hair_color="Brown"
    )
    _make_case(
        db_session, source=source, external_id="2", sex="Female", missing_state="Texas", hair_color="Black"
    )
    _make_case(
        db_session, source=source, external_id="3", sex="Male", missing_state="Texas", hair_color="Brown"
    )

    resp = client.get(API, params={"sex": "female", "missing_state": "texas", "hair_color": "brown"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_no_matches_returns_empty_list(client, db_session):
    source = _make_source(db_session, "fbi")
    _make_case(db_session, source=source, external_id="1", sex="Female")

    resp = client.get(API, params={"sex": "unknown-value"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []


# --- pagination -----------------------------------------------------------------------


def test_default_pagination(client, db_session):
    source = _make_source(db_session, "fbi")
    for i in range(3):
        _make_case(db_session, source=source, external_id=str(i))

    resp = client.get(API)
    assert resp.status_code == 200
    body = resp.json()
    assert body["limit"] == 25
    assert body["offset"] == 0
    assert len(body["items"]) == 3


def test_explicit_limit_offset(client, db_session):
    source = _make_source(db_session, "fbi")
    for i in range(5):
        _make_case(db_session, source=source, external_id=str(i))

    resp = client.get(API, params={"limit": 2, "offset": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert body["limit"] == 2
    assert body["offset"] == 1
    assert len(body["items"]) == 2
    assert body["total"] == 5


def test_max_limit_enforced(client, db_session):
    source = _make_source(db_session, "fbi")
    _make_case(db_session, source=source, external_id="1")

    resp = client.get(API, params={"limit": 101})
    assert resp.status_code == 422

    resp_neg_offset = client.get(API, params={"offset": -1})
    assert resp_neg_offset.status_code == 422


def test_total_count_independent_of_page_size(client, db_session):
    source = _make_source(db_session, "fbi")
    for i in range(7):
        _make_case(db_session, source=source, external_id=str(i))

    resp = client.get(API, params={"limit": 2})
    body = resp.json()
    assert body["total"] == 7
    assert len(body["items"]) == 2


def test_stable_ordering_across_pages(client, db_session):
    """All cases share (effectively) the same created_at within one test transaction --
    without the Case.id tie-break, offset-based pagination could skip/duplicate rows."""
    source = _make_source(db_session, "fbi")
    for i in range(6):
        _make_case(db_session, source=source, external_id=str(i))

    seen_ids = set()
    for offset in (0, 2, 4):
        resp = client.get(API, params={"limit": 2, "offset": offset, "sort": "created_at", "order": "desc"})
        for item in resp.json()["items"]:
            seen_ids.add(item["case_id"])

    assert len(seen_ids) == 6


# --- sorting ----------------------------------------------------------------------


def test_sort_by_missing_date_ascending(client, db_session):
    source = _make_source(db_session, "fbi")
    _make_case(db_session, source=source, external_id="1", display_name="LATER", missing_date=date(2023, 1, 1))
    _make_case(db_session, source=source, external_id="2", display_name="EARLIER", missing_date=date(2020, 1, 1))

    resp = client.get(API, params={"sort": "missing_date", "order": "asc"})
    names = [item["display_name"] for item in resp.json()["items"]]
    assert names == ["EARLIER", "LATER"]


def test_sort_descending(client, db_session):
    source = _make_source(db_session, "fbi")
    _make_case(db_session, source=source, external_id="1", display_name="LATER", missing_date=date(2023, 1, 1))
    _make_case(db_session, source=source, external_id="2", display_name="EARLIER", missing_date=date(2020, 1, 1))

    resp = client.get(API, params={"sort": "missing_date", "order": "desc"})
    names = [item["display_name"] for item in resp.json()["items"]]
    assert names == ["LATER", "EARLIER"]


def test_invalid_sort_field_rejected(client, db_session):
    source = _make_source(db_session, "fbi")
    _make_case(db_session, source=source, external_id="1")

    resp = client.get(API, params={"sort": "not_a_real_field"})
    assert resp.status_code == 422

    resp_order = client.get(API, params={"order": "sideways"})
    assert resp_order.status_code == 422


# --- list response shape -------------------------------------------------------------


def test_list_response_is_compact_summary_shape(client, db_session):
    source = _make_source(db_session, "fbi")
    _make_case(
        db_session,
        source=source,
        external_id="1",
        display_name="SAMPLE PERSON",
        contributed_fields={"display_name": "SAMPLE PERSON", "circumstances": "secret narrative"},
    )

    resp = client.get(API)
    item = resp.json()["items"][0]
    expected_keys = {
        "case_id", "person_id", "display_name", "sex", "missing_date", "missing_city",
        "missing_state", "missing_country", "primary_photo_url", "investigating_agency",
        "source_names", "updated_at",
    }
    assert set(item.keys()) == expected_keys
    assert "contributed_fields" not in item
    assert "payload" not in item
    assert "circumstances" not in item
    assert "aliases" not in item


def test_primary_photo_selection_uses_first_photo(client, db_session):
    # Rows created in the same test transaction share an identical `created_at` (Postgres
    # `now()` is transaction-time), so pagination's id tie-break order is not creation
    # order -- assert by case identity, not list position, to avoid a flaky test.
    source = _make_source(db_session, "fbi")
    case_with_photos = _make_case(
        db_session,
        source=source,
        external_id="1",
        photos=[
            {"url": "https://example.org/first.jpg", "full_url": None, "thumbnail_url": None, "caption": None},
            {"url": "https://example.org/second.jpg", "full_url": None, "thumbnail_url": None, "caption": None},
        ],
    )
    case_without_photos = _make_case(db_session, source=source, external_id="2", photos=None)

    resp = client.get(API)
    items = {item["case_id"]: item for item in resp.json()["items"]}
    assert items[str(case_with_photos.id)]["primary_photo_url"] == "https://example.org/first.jpg"
    assert items[str(case_without_photos.id)]["primary_photo_url"] is None


def test_source_names_present_in_list(client, db_session):
    source = _make_source(db_session, "fbi", name="Federal Bureau of Investigation")
    _make_case(db_session, source=source, external_id="1")

    resp = client.get(API)
    assert resp.json()["items"][0]["source_names"] == ["Federal Bureau of Investigation"]


# --- detail response ----------------------------------------------------------------


def test_detail_returns_person_and_case_fields(client, db_session):
    source = _make_source(db_session, "fbi")
    case = _make_case(
        db_session,
        source=source,
        external_id="1",
        display_name="SAMPLE PERSON",
        sex="Female",
        missing_city="Sampleton",
        investigating_agency="Federal Bureau of Investigation",
    )

    resp = client.get(f"{API}/{case.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["person"]["display_name"] == "SAMPLE PERSON"
    assert body["person"]["sex"] == "Female"
    assert body["missing_city"] == "Sampleton"
    assert body["investigating_agency"] == "Federal Bureau of Investigation"


def test_detail_height_and_weight_are_nested_objects(client, db_session):
    source = _make_source(db_session, "fbi")
    case = _make_case(db_session, source=source, external_id="1")

    resp = client.get(f"{API}/{case.id}")
    person = resp.json()["person"]
    assert set(person["height"].keys()) == {"min_cm", "max_cm", "raw", "temporal_context"}
    assert set(person["weight"].keys()) == {"min_kg", "max_kg", "raw", "temporal_context"}
    assert person["height"]["min_cm"] is None  # not populated -- explicit null, not fabricated


def test_detail_photos_list(client, db_session):
    source = _make_source(db_session, "fbi")
    case = _make_case(
        db_session,
        source=source,
        external_id="1",
        photos=[{"url": "https://example.org/a.jpg", "full_url": None, "thumbnail_url": None, "caption": "A."}],
    )

    resp = client.get(f"{API}/{case.id}")
    photos = resp.json()["person"]["photos"]
    assert photos == [{"url": "https://example.org/a.jpg", "full_url": None, "thumbnail_url": None, "caption": "A."}]


def test_detail_includes_provenance_sources(client, db_session):
    source = _make_source(db_session, "fbi", name="Federal Bureau of Investigation")
    case = _make_case(
        db_session,
        source=source,
        external_id="ext-123",
        contributed_fields={"display_name": "SAMPLE PERSON"},
    )

    resp = client.get(f"{API}/{case.id}")
    sources = resp.json()["sources"]
    assert len(sources) == 1
    assert sources[0]["source_code"] == "fbi"
    assert sources[0]["source_name"] == "Federal Bureau of Investigation"
    assert sources[0]["external_id"] == "ext-123"
    assert sources[0]["contributed_fields"] == {"display_name": "SAMPLE PERSON"}
    assert "first_seen_at" in sources[0]
    assert "last_seen_at" in sources[0]


def test_detail_handles_missing_null_fields(client, db_session):
    source = _make_source(db_session, "fbi")
    case = _make_case(db_session, source=source, external_id="1", photos=None)

    resp = client.get(f"{API}/{case.id}")
    person = resp.json()["person"]
    assert person["photos"] == []
    assert person["aliases"] is None
    assert person["hair_color"] is None
    assert person["distinguishing_characteristics"] is None


def test_case_sources_endpoint(client, db_session):
    source = _make_source(db_session, "fbi")
    case = _make_case(db_session, source=source, external_id="1")

    resp = client.get(f"{API}/{case.id}/sources")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["source_code"] == "fbi"


def test_case_detail_not_found(client, db_session):
    resp = client.get(f"{API}/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


def test_case_sources_not_found(client, db_session):
    resp = client.get(f"{API}/00000000-0000-0000-0000-000000000000/sources")
    assert resp.status_code == 404


# --- query efficiency ----------------------------------------------------------------


def test_list_cases_query_count_does_not_scale_with_row_count(client, db_session, test_engine):
    source = _make_source(db_session, "fbi")
    for i in range(10):
        _make_case(db_session, source=source, external_id=str(i))

    counts = {"n": 0}

    def _count(conn, cursor, statement, parameters, context, executemany):
        counts["n"] += 1

    event.listen(test_engine, "before_cursor_execute", _count)
    try:
        resp = client.get(API, params={"limit": 25})
    finally:
        event.remove(test_engine, "before_cursor_execute", _count)

    assert resp.status_code == 200
    assert resp.json()["total"] == 10
    # Bounded regardless of row count: a count query, the page query, and one bulk
    # source-names query -- never one query per case row.
    assert counts["n"] <= 6
