import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import app.models  # noqa: F401  (registers all models on Base.metadata)
from app.api.deps import get_db
from app.core.config import get_settings
from app.db.base import Base
from app.main import app as fastapi_app


def _test_database_name() -> str:
    return f"{get_settings().postgres_db}_test"


def _test_database_url() -> str:
    settings = get_settings()
    return (
        f"postgresql+psycopg://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{_test_database_name()}"
    )


def _ensure_test_database_exists() -> None:
    settings = get_settings()
    admin_url = (
        f"postgresql+psycopg://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/postgres"
    )
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    db_name = _test_database_name()
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": db_name}
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        admin_engine.dispose()


@pytest.fixture(scope="session")
def test_engine():
    _ensure_test_database_exists()
    engine = create_engine(_test_database_url(), future=True)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def db_session(test_engine):
    with Session(test_engine) as session:
        yield session
        session.rollback()

    with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture()
def client(db_session):
    """A TestClient wired to this test's db_session, via FastAPI's dependency override
    -- API-level tests see exactly the data seeded through db_session, in the same
    session/transaction, without a second database connection."""

    def _override_get_db():
        yield db_session

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(fastapi_app) as test_client:
            yield test_client
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
