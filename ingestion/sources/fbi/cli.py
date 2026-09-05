"""CLI for running raw FBI Wanted API ingestion.

Usage (run inside the api container, which has DB access and dependencies installed):

    docker compose run --rm api python -m ingestion.sources.fbi.cli
    docker compose run --rm api python -m ingestion.sources.fbi.cli --max-pages 2
    docker compose run --rm api python -m ingestion.sources.fbi.cli --all-pages

Defaults to a single page (--max-pages 1) so a bare invocation is always a safe,
deliberately limited smoke test -- never a full-database fetch.
"""

from __future__ import annotations

import argparse
import logging

from app.db.session import SessionLocal
from ingestion.sources.fbi.client import FBIApiClient, FBIApiError
from ingestion.sources.fbi.service import DEFAULT_MAX_PAGES, run_fbi_ingestion

logger = logging.getLogger("ingestion.fbi.cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run raw FBI Wanted API ingestion (Source/SourceRecord/SourceSnapshot only; "
            "no Person/Case records, no normalization). Defaults to a single page."
        )
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help=f"Maximum number of pages to fetch (default: {DEFAULT_MAX_PAGES}).",
    )
    parser.add_argument(
        "--all-pages",
        action="store_true",
        help="Ignore --max-pages and fetch every available page. Not recommended for casual runs.",
    )
    parser.add_argument(
        "--page-size", type=int, default=20, help="Items requested per page (default: 20)."
    )
    parser.add_argument(
        "--start-page", type=int, default=1, help="Page number to start fetching from (default: 1)."
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    max_pages = None if args.all_pages else args.max_pages

    db = SessionLocal()
    try:
        with FBIApiClient() as client:
            stats = run_fbi_ingestion(
                db,
                client,
                max_pages=max_pages,
                page_size=args.page_size,
                start_page=args.start_page,
            )
    except (FBIApiError, RuntimeError) as exc:
        logger.error("FBI ingestion aborted: %s", exc)
        return 1
    finally:
        db.close()

    print(stats.as_summary())
    return 0 if stats.failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
