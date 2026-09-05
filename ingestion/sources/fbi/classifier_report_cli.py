"""CLI for the read-only Phase 1 FBI classifier report.

Runs the deterministic classifier (`classifier.classify_fbi_record`) against every
currently stored active FBI record and prints aggregate counts only -- never
per-record identifying data. Issues SELECT queries only; no writes, no network calls.

Usage:

    docker compose run --rm api python -m ingestion.sources.fbi.classifier_report_cli
"""

from __future__ import annotations

import argparse
import logging

from app.db.session import SessionLocal
from ingestion.sources.fbi.classifier_report import build_classifier_report, render_classifier_report
from ingestion.sources.fbi.service import get_fbi_source

logger = logging.getLogger("ingestion.fbi.classifier_report")


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description=(
            "Read-only aggregate report of Phase 1 FBI classifier outcomes over "
            "currently stored FBI records. Issues SELECT queries only; makes no "
            "writes and no network calls."
        )
    )


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    db = SessionLocal()
    try:
        source = get_fbi_source(db)
        report = build_classifier_report(db, source)
    except RuntimeError as exc:
        logger.error("Could not build report: %s", exc)
        return 1
    finally:
        db.close()

    print(render_classifier_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
