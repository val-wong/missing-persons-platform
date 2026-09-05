import httpx
import pytest

from ingestion.sources.fbi.client import (
    USER_AGENT,
    FBIApiClient,
    FBIApiConnectionError,
    FBIApiResponseError,
)


def _client_with_handler(handler, **client_kwargs) -> FBIApiClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(
        transport=transport, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    # Tests exercise a single request/response by default -- no retries, no rate-limit
    # delay -- unless a test explicitly opts in (see the retry/rate-limit tests below).
    client_kwargs.setdefault("max_retries", 0)
    client_kwargs.setdefault("min_request_interval", 0.0)
    return FBIApiClient(client=http_client, **client_kwargs)


def _fbi_item(uid: str = "abc123", title: str = "SAMPLE SUBJECT") -> dict:
    return {
        "uid": uid,
        "url": f"https://www.fbi.gov/wanted/kidnap/{uid}",
        "modified": "2026-01-01T00:00:00+00:00",
        "title": title,
        "status": "na",
    }


def test_default_client_sets_explicit_user_agent():
    client = FBIApiClient()
    try:
        assert client._client.headers["user-agent"] == USER_AGENT
        assert "prototype" in USER_AGENT
    finally:
        client.close()


def test_fetch_page_parses_successful_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["user-agent"] == USER_AGENT
        assert request.url.params["page"] == "1"
        return httpx.Response(200, json={"total": 2, "page": 1, "items": [_fbi_item("a"), _fbi_item("b")]})

    client = _client_with_handler(handler)
    response = client.fetch_page(page=1, page_size=20)

    assert response.total == 2
    assert response.page == 1
    assert len(response.items) == 2
    assert response.items[0]["uid"] == "a"


def test_fetch_page_raises_on_non_2xx_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal server error")

    client = _client_with_handler(handler)
    with pytest.raises(FBIApiResponseError):
        client.fetch_page(page=1)


def test_fetch_page_raises_on_invalid_json():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    client = _client_with_handler(handler)
    with pytest.raises(FBIApiResponseError):
        client.fetch_page(page=1)


def test_fetch_page_raises_on_structurally_invalid_body():
    def handler(request: httpx.Request) -> httpx.Response:
        # Missing required "items" key entirely.
        return httpx.Response(200, json={"total": 0, "page": 1})

    client = _client_with_handler(handler)
    with pytest.raises(FBIApiResponseError):
        client.fetch_page(page=1)


def test_iter_pages_stops_on_short_page():
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        if page == 1:
            items = [_fbi_item(f"p1-{i}") for i in range(3)]
        elif page == 2:
            items = [_fbi_item(f"p2-{i}") for i in range(1)]  # short page -> last page
        else:
            raise AssertionError("should not fetch beyond the short page")
        return httpx.Response(200, json={"total": 4, "page": page, "items": items})

    client = _client_with_handler(handler)
    pages = list(client.iter_pages(page_size=3))

    assert len(pages) == 2
    assert len(pages[0].items) == 3
    assert len(pages[1].items) == 1


def test_iter_pages_respects_max_pages():
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        items = [_fbi_item(f"p{page}-{i}") for i in range(3)]
        return httpx.Response(200, json={"total": 100, "page": page, "items": items})

    client = _client_with_handler(handler)
    pages = list(client.iter_pages(page_size=3, max_pages=2))

    assert len(pages) == 2


def test_fetch_page_retries_transient_server_error_then_succeeds(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr("ingestion.sources.fbi.client.time.sleep", lambda s: sleeps.append(s))

    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] < 3:
            return httpx.Response(503, text="temporarily unavailable")
        return httpx.Response(200, json={"total": 1, "page": 1, "items": [_fbi_item()]})

    client = _client_with_handler(handler, max_retries=3, retry_backoff_seconds=1.0)
    response = client.fetch_page(page=1)

    assert response.total == 1
    assert call_count["n"] == 3
    # Two retries before success: backoff doubles (1s, 2s). Rate-limit waits are 0.
    assert sleeps == [1.0, 2.0]


def test_fetch_page_does_not_retry_client_error():
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(404, text="not found")

    client = _client_with_handler(handler, max_retries=3)
    with pytest.raises(FBIApiResponseError):
        client.fetch_page(page=1)

    assert call_count["n"] == 1


def test_fetch_page_raises_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr("ingestion.sources.fbi.client.time.sleep", lambda s: None)
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(503, text="still unavailable")

    client = _client_with_handler(handler, max_retries=2)
    with pytest.raises(FBIApiResponseError):
        client.fetch_page(page=1)

    assert call_count["n"] == 3  # initial attempt + 2 retries


def test_fetch_page_retries_connection_errors(monkeypatch):
    monkeypatch.setattr("ingestion.sources.fbi.client.time.sleep", lambda s: None)
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, json={"total": 1, "page": 1, "items": [_fbi_item()]})

    client = _client_with_handler(handler, max_retries=2)
    response = client.fetch_page(page=1)

    assert response.total == 1
    assert call_count["n"] == 2


def test_fetch_page_exhausts_retries_on_persistent_connection_error(monkeypatch):
    monkeypatch.setattr("ingestion.sources.fbi.client.time.sleep", lambda s: None)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = _client_with_handler(handler, max_retries=1)
    with pytest.raises(FBIApiConnectionError):
        client.fetch_page(page=1)


def test_rate_limit_waits_between_consecutive_requests(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr("ingestion.sources.fbi.client.time.sleep", lambda s: sleeps.append(s))

    # Freeze monotonic time so the elapsed-time calculation is deterministic.
    monkeypatch.setattr("ingestion.sources.fbi.client.time.monotonic", lambda: 100.0)

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        return httpx.Response(200, json={"total": 2, "page": page, "items": [_fbi_item()]})

    client = _client_with_handler(handler, min_request_interval=0.5)
    client.fetch_page(page=1)
    client.fetch_page(page=2)

    assert sleeps == [0.5]
