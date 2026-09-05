"""CLI for historical FBI reprocessing (backfill): replays already-stored
SourceSnapshots through classify -> normalize -> validate -> persist, without
contacting the FBI API.

Usage (run inside the api container, which has DB access and dependencies installed):

    # Preview only -- zero canonical writes. Safe to run any time, as often as needed.
    docker compose run --rm api python -m ingestion.sources.fbi.reprocess_cli

    # Actually persist canonical Person/Case/CaseSource rows for IN_SCOPE records.
    docker compose run --rm api python -m ingestion.sources.fbi.reprocess_cli --execute

Defaults to a dry run so a bare invocation is always safe -- never a real write --
mirroring the "safe by default" convention `ingestion.sources.fbi.cli` already uses for
live ingestion. See docs/fbi-reprocessing.md for the full flow, guarantees, and expected
output counters.
"""

from __future__ import annotations

import argparse
import logging

from app.db.session import SessionLocal
from ingestion.sources.fbi.reprocess import reprocess_fbi_source_records
from ingestion.sources.fbi.service import get_fbi_source

logger = logging.getLogger("ingestion.fbi.reprocess_cli")


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description=(
            "Reprocess already-stored FBI SourceRecords (latest SourceSnapshot per "
            "record) through classify/normalize/validate/persist. Never calls the FBI "
            "API and never modifies SourceRecord/SourceSnapshot rows. Defaults to a dry "
            "run (zero canonical writes); pass --execute to actually persist."
        )
    )


def _add_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Persist canonical writes. Without this flag, runs a dry run only.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _add_args(build_parser())
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    dry_run = not args.execute

    db = SessionLocal()
    try:
        source = get_fbi_source(db)
        stats = reprocess_fbi_source_records(db, source, dry_run=dry_run)
        if dry_run:
            # Defense-in-depth: this CLI's session holds nothing but this run, so an
            # explicit rollback here is a safe no-op on top of the per-record SAVEPOINT
            # rollback `reprocess_fbi_source_records` already performed.
            db.rollback()
        else:
            db.commit()
    except RuntimeError as exc:
        logger.error("FBI reprocessing aborted: %s", exc)
        db.rollback()
        return 1
    finally:
        db.close()

    print(stats.as_summary())
    return 0 if stats.failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
