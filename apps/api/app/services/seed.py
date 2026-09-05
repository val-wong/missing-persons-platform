"""Seed reference data (known sources) that is not user or ingestion generated."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.source import Source

SOURCE_SEED_DATA: list[dict[str, str]] = [
    {
        "code": "fbi",
        "name": "Federal Bureau of Investigation",
        "base_url": "https://www.fbi.gov",
        "source_type": "government_agency",
    },
    {
        "code": "namus",
        "name": "National Missing and Unidentified Persons System",
        "base_url": "https://www.namus.gov",
        "source_type": "government_agency",
    },
]


def seed_sources(db: Session) -> list[Source]:
    """Insert the known sources if they do not already exist. Idempotent."""
    created: list[Source] = []
    for entry in SOURCE_SEED_DATA:
        existing = db.scalar(select(Source).where(Source.code == entry["code"]))
        if existing is not None:
            continue
        source = Source(**entry)
        db.add(source)
        created.append(source)
    db.commit()
    return created


if __name__ == "__main__":
    from app.db.session import SessionLocal

    with SessionLocal() as session:
        new_sources = seed_sources(session)
        print(f"Seeded {len(new_sources)} new source(s).")
