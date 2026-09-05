# missing-persons-platform

A public-data aggregation platform for missing-person records.

This platform aggregates and normalizes publicly available missing-person data from
authoritative sources (e.g. FBI, NamUs). It does **not** perform speculative
identification, facial recognition, investigative matching, or infer facts that sources
do not themselves provide. See [docs/architecture.md](docs/architecture.md) for the
principle this is built around.

This repository currently contains the backend scaffold plus **FBI ingestion and
normalization (Phase 1)** — schema, migrations, a read-only API surface, and an FBI
Wanted API client/pipeline that stores raw source data and, for records the Phase 1
classifier marks as missing-person cases, deterministically normalizes them into
canonical `Person`/`Case` records. See [docs/fbi-source.md](docs/fbi-source.md) (raw
ingestion) and [docs/fbi-normalization.md](docs/fbi-normalization.md) (normalization).

## Repository layout

```
apps/api/app/
  api/        FastAPI routers and request-scoped dependencies
  core/       Configuration (env-driven settings)
  db/         SQLAlchemy engine/session setup
  models/     SQLAlchemy ORM models
  schemas/    Pydantic v2 request/response schemas
  services/   Application/business logic (e.g. seeding)
apps/api/tests/
apps/api/alembic/     Alembic migration environment
ingestion/
  sources/base.py      Common source-adapter contract (NormalizedRecord, persistence rule)
  sources/fbi/          FBI Wanted API client, classifier, normalizer, ingestion service/CLI
  sources/namus/         NamUs ingestion (not yet implemented)
  normalize/            Source-agnostic normalization helpers (dates, text) shared by adapters
  linkage/               Cross-source case linkage (not yet implemented; Phase 1 only
                          deduplicates within a single source, via SourceRecord)
docs/          Architecture and design documentation
data/raw/      Raw fetched payloads (gitignored)
data/imports/  Import working files (gitignored)
```

## Tech stack

Python 3.12+, FastAPI, PostgreSQL, SQLAlchemy 2.x, Alembic, Pydantic v2, pytest, Docker
Compose. Deliberately excludes Redis, Celery, Kubernetes, Elasticsearch, and any LLM
framework — this scaffold stays intentionally simple.

## Local setup

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env` if you want non-default credentials. `.env` is gitignored — never commit it.

### 2. Start the stack

```bash
docker compose up -d
```

This starts PostgreSQL (`db`) and the FastAPI app (`api`) on `http://localhost:8000`.

### 3. Run database migrations

```bash
docker compose run --rm api alembic upgrade head
```

### 4. Seed reference data

Seeds the two known sources (FBI, NamUs):

```bash
docker compose run --rm api python -m app.services.seed
```

### 5. Explore the API

- `GET /health` — liveness check
- `GET /api/v1/sources` — list registered sources
- `GET /api/v1/cases` — list cases
- `GET /api/v1/cases/{case_id}` — case detail, including the linked person

Interactive docs: `http://localhost:8000/docs`

## Running tests

Tests run against a real PostgreSQL database (matching production dialect usage —
JSONB, native UUID columns). They create/use a `<POSTGRES_DB>_test` database on the same
server and tear tables down between tests.

```bash
docker compose run --rm api pytest
```

## FBI ingestion + normalization (Phase 1)

```bash
# Fetches exactly one page (20 items) by default -- never the full dataset.
# Raw-ingests every item, then classifies/normalizes/persists canonical Person/Case
# records for whichever of those items the Phase 1 classifier marks IN_SCOPE.
docker compose run --rm api python -m ingestion.sources.fbi.cli
```

Running it twice in a row is safe: unchanged items are skipped entirely, and changed
items update the same `Person`/`Case` row (via `CaseSource`) rather than creating a
duplicate. See [docs/fbi-source.md](docs/fbi-source.md) for raw-ingestion behavior,
flags, and limitations, and [docs/fbi-normalization.md](docs/fbi-normalization.md) for
exactly which fields are mapped, why, and which are deliberately left `NULL`.

Read-only classification discovery report (no writes, no network calls) over already
stored FBI data, used to evaluate candidate missing-person classification rules before
any filtering is implemented:

```bash
docker compose run --rm api python -m ingestion.sources.fbi.report_cli
```

See [docs/fbi-classification.md](docs/fbi-classification.md) for findings.

Phase 1 deterministic classifier report (aggregate counts only, no writes, no network
calls), classifying stored FBI records as `IN_SCOPE` / `OUT_OF_SCOPE` / `UNCLASSIFIED`:

```bash
docker compose run --rm api python -m ingestion.sources.fbi.classifier_report_cli
```

See [docs/fbi-classification.md](docs/fbi-classification.md) (Phase 1 classifier
section) for the implemented rules and product-scope decisions behind them.

Read-only FBI → canonical normalization discovery report (structural stats only, no
writes, no network calls), over currently `IN_SCOPE` FBI records -- the tool used to
evaluate candidate `Person`/`Case` field mappings, including the ones now implemented:

```bash
docker compose run --rm api python -m ingestion.sources.fbi.normalization_report_cli
```

See [docs/fbi-normalization.md](docs/fbi-normalization.md) for the implemented mappings,
the fields deliberately left unmapped, and why.

Historical reprocessing / backfill: replays already-stored `SourceSnapshot`s (latest
per `SourceRecord`) through classify/normalize/validate/persist, for records that
predate the canonical pipeline or were missed by an earlier classifier/normalizer bug.
Never fetches the FBI API. Defaults to a dry run (zero canonical writes):

```bash
docker compose run --rm api python -m ingestion.sources.fbi.reprocess_cli
docker compose run --rm api python -m ingestion.sources.fbi.reprocess_cli --execute
```

See [docs/fbi-reprocessing.md](docs/fbi-reprocessing.md) for the full flow, output
counters, and idempotency guarantees.

## Database migrations

This project uses Alembic. After changing a model in `apps/api/app/models/`, generate a
new revision:

```bash
docker compose run --rm api alembic revision --autogenerate -m "describe the change"
docker compose run --rm api alembic upgrade head
```

Always review autogenerated migrations before applying them.
