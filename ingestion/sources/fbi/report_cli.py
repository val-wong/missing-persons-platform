"""CLI for the read-only FBI classification discovery report.

This command only issues SELECT queries against already-stored SourceSnapshots -- it
never fetches from the FBI API and never writes to the database. Use
`ingestion.sources.fbi.cli` (raw ingestion) first if you need more data to inspect.

Usage:

    docker compose run --rm api python -m ingestion.sources.fbi.report_cli
"""

from __future__ import annotations

import argparse
import logging

from app.db.session import SessionLocal
from ingestion.sources.fbi.classification_report import build_classification_report, render_report
from ingestion.sources.fbi.service import get_fbi_source

logger = logging.getLogger("ingestion.fbi.report")


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description=(
            "Read-only structural report on how the FBI API classifies stored records "
            "(subjects, poster_classification, person_classification, status). "
            "Issues SELECT queries only; makes no writes and no network calls."
        )
    )


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    db = SessionLocal()
    try:
        source = get_fbi_source(db)
        report = build_classification_report(db, source)
    except RuntimeError as exc:
        logger.error("Could not build report: %s", exc)
        return 1
    finally:
        db.close()

    print(render_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
