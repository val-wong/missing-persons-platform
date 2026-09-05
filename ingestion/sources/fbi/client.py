"""Thin HTTP client for the official FBI Wanted API.

Endpoint: https://api.fbi.gov/wanted/v1/list

This client only ever talks to the public JSON API -- it never scrapes fbi.gov HTML
pages. It performs no interpretation of the data beyond validating that a response is
well-formed JSON shaped like a paginated list; item contents are passed through as
opaque dicts for the ingestion service to store raw.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import Any, Self

import httpx
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger("ingestion.fbi.client")

FBI_WANTED_LIST_URL = "https://api.fbi.gov/wanted/v1/list"

# Identifies this prototype to the FBI API operators; not a browser UA.
USER_AGENT = "missing-persons-platform-fbi-ingestion/0.1 (raw-ingestion-prototype)"

DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)
DEFAULT_PAGE_SIZE = 20

# Operational protections: this client must never hammer a public API. Retries only
# cover transient failures (timeouts, connection errors, HTTP 5xx) with exponential
# backoff -- a 4xx response or a malformed body is not retried, since retrying those
# wastes requests with no chance of a different outcome.
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 1.0
DEFAULT_MIN_REQUEST_INTERVAL_SECONDS = 0.5


class FBIApiError(Exception):
    """Base class for all FBI API client failures."""


class FBIApiConnectionError(FBIApiError):
    """The FBI API could not be reached (network error or timeout)."""


class FBIApiResponseError(FBIApiError):
    """The FBI API responded, but with a non-2xx status or a structurally invalid body."""


class FBIListResponse(BaseModel):
    """Structural shape of the FBI Wanted list endpoint. Item contents are left as raw dicts:
    interpreting individual fields is a normalization concern, not a raw-ingestion concern.
    """

    model_config = ConfigDict(extra="ignore")

    total: int
    page: int
    items: list[dict[str, Any]]


class FBIApiClient:
    """Client for GET https://api.fbi.gov/wanted/v1/list, with pagination support."""

    def __init__(
        self,
        base_url: str = FBI_WANTED_LIST_URL,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        client: httpx.Client | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
        min_request_interval: float = DEFAULT_MIN_REQUEST_INTERVAL_SECONDS,
    ) -> None:
        self._base_url = base_url
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._min_request_interval = min_request_interval
        self._last_request_at: float | None = None

    def _wait_for_rate_limit(self) -> None:
        """Block, if needed, so at least `min_request_interval` elapses between the
        start of consecutive requests this client makes -- regardless of whether the
        previous request succeeded or failed."""
        if self._min_request_interval <= 0:
            return
        now = time.monotonic()
        if self._last_request_at is not None:
            remaining = self._min_request_interval - (now - self._last_request_at)
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at = time.monotonic()

    def _get_with_retries(self, page: int, page_size: int) -> httpx.Response:
        """One page fetch, retrying only transient failures (timeout, connection error,
        HTTP 5xx) with exponential backoff. A 4xx response raises immediately -- it is
        not going to succeed on retry."""
        last_error: FBIApiError | None = None
        attempts = self._max_retries + 1
        for attempt in range(attempts):
            self._wait_for_rate_limit()
            try:
                response = self._client.get(
                    self._base_url, params={"page": page, "pageSize": page_size}
                )
            except httpx.TimeoutException as exc:
                last_error = FBIApiConnectionError(
                    f"Timed out contacting FBI API (page {page}): {exc}"
                )
            except httpx.RequestError as exc:
                last_error = FBIApiConnectionError(
                    f"Could not reach FBI API (page {page}): {exc}"
                )
            else:
                if 200 <= response.status_code < 300:
                    return response
                if response.status_code < 500:
                    raise FBIApiResponseError(
                        f"FBI API returned HTTP {response.status_code} for page {page}"
                    )
                last_error = FBIApiResponseError(
                    f"FBI API returned HTTP {response.status_code} for page {page}"
                )

            if attempt < attempts - 1:
                delay = self._retry_backoff_seconds * (2**attempt)
                logger.warning(
                    "FBI API request failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1,
                    attempts,
                    delay,
                    last_error,
                )
                time.sleep(delay)

        assert last_error is not None  # attempts >= 1, so the loop always sets this
        raise last_error

    def fetch_page(self, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> FBIListResponse:
        """Fetch and validate a single page of FBI Wanted list results."""
        response = self._get_with_retries(page=page, page_size=page_size)

        try:
            data = response.json()
        except ValueError as exc:
            raise FBIApiResponseError(
                f"FBI API returned a non-JSON response for page {page}: {exc}"
            ) from exc

        try:
            return FBIListResponse.model_validate(data)
        except Exception as exc:  # pydantic.ValidationError, plus defensive catch-all
            raise FBIApiResponseError(
                f"FBI API response for page {page} failed structural validation: {exc}"
            ) from exc

    def iter_pages(
        self,
        start_page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages: int | None = None,
    ) -> Iterator[FBIListResponse]:
        """Yield successive pages starting at `start_page`.

        Stops when the API returns fewer items than `page_size` (or zero items) --
        the signal the FBI API gives for "last page" -- or when `max_pages` is reached.
        Raises FBIApiError from the caller's iteration if a page fetch fails; the
        caller decides whether to stop or has already made partial progress.
        """
        page = start_page
        pages_yielded = 0
        while max_pages is None or pages_yielded < max_pages:
            response = self.fetch_page(page=page, page_size=page_size)
            yield response
            pages_yielded += 1
            if len(response.items) < page_size:
                break
            page += 1

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
