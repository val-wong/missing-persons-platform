"""CLI for the read-only FBI -> canonical normalization discovery report.

Inspects the latest stored snapshot of every FBI record the Phase 1 classifier marks
IN_SCOPE / MISSING_PERSON and reports aggregate structural statistics only -- field
names, JSON types, presence/null/empty counts, and pattern-match counts. It never
prints individual field values that identify or describe a person, issues no writes,
and makes no network calls.

Usage:

    docker compose run --rm api python -m ingestion.sources.fbi.normalization_report_cli
"""

from __future__ import annotations

import argparse
import logging

from app.db.session import SessionLocal
from ingestion.sources.fbi.normalization_report import build_normalization_report, render_normalization_report
from ingestion.sources.fbi.service import get_fbi_source

logger = logging.getLogger("ingestion.fbi.normalization_report")


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description=(
            "Read-only structural discovery report over IN_SCOPE FBI records, used to "
            "evaluate candidate Person/Case field mappings before any normalization is "
            "implemented. Issues SELECT queries only; makes no writes and no network calls."
        )
    )


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    db = SessionLocal()
    try:
        source = get_fbi_source(db)
        report = build_normalization_report(db, source)
    except RuntimeError as exc:
        logger.error("Could not build report: %s", exc)
        return 1
    finally:
        db.close()

    print(render_normalization_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
