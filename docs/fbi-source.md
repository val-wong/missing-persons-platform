# FBI Wanted API — raw ingestion (Phase 1)

## Scope

This document covers **raw ingestion**: fetching FBI Wanted API items and storing them,
unmodified, via the `Source` / `SourceRecord` / `SourceSnapshot` models (see
[architecture.md](architecture.md)). This is a prerequisite for, and separate from,
canonical normalization (classify → normalize → validate → persist `Person`/`Case`),
which is documented in [fbi-normalization.md](fbi-normalization.md) and runs
immediately after raw ingestion for any item raw-ingested as new or changed. Phase 1
still does **not**:

- link or deduplicate records across sources (only same-source idempotency, via
  `(source_id, external_id)`, is implemented),
- mark records inactive/removed.

## Official endpoint

`GET https://api.fbi.gov/wanted/v1/list`

This is the FBI's public JSON API for its Wanted program (which includes, among other
categories, missing-persons-related listings under `subjects` such as "Kidnappings and
Missing Persons"). The client (`ingestion/sources/fbi/client.py`) only calls this JSON
endpoint — it never scrapes `fbi.gov` HTML pages.

Observed response shape (subject to change by the FBI, hence the deliberately loose
structural validation described below):

```json
{
  "total": 1233,
  "page": 1,
  "items": [ { "...": "54+ fields, mostly nullable" } ]
}
```

Query parameters used: `page` (1-indexed) and `pageSize` (default 20 if omitted, and
what the client requests explicitly). Requesting a page past the end returns
`items: []` with `total` unchanged — that empty-page (or short-page) response is the
only pagination-end signal the API gives; there is no separate "last page" flag.

## External identifier: `uid`

Each FBI item carries a `uid` field, e.g. `"2caa95f3b2b34cbda7d70dac99d95b9a"` — an
opaque, stable, per-record identifier assigned by the FBI's own system (it also appears
embedded in the item's `pathId`, e.g.
`https://api.fbi.gov/@wanted-person/2caa95f3b2b34cbda7d70dac99d95b9a`). This is used as
`SourceRecord.external_id`.

`uid` was chosen over alternatives because:

- **`url` / `path`** (the public `fbi.gov` page slug, e.g.
  `/wanted/kidnap/sample-person`) can change if a subject's name or listing is
  edited, so it is not stable — but it *is* preserved separately as
  `SourceRecord.source_url` since it's the human-facing link to the source.
- **`title`** is a display name, not an identifier, and can be edited.
- **`uid`** appeared stable and unique across observed pages and is clearly the FBI
  system's own primary key for the record, based on its reuse inside `pathId`.

If an item is missing a usable `uid` (or a usable `url`, which is required by the
`SourceRecord.source_url` NOT NULL column), that single item is skipped and counted as
a failure — it does not abort the rest of the ingestion run.

## Snapshot / hash behavior

Every raw item is serialized deterministically before hashing:
`json.dumps(item, sort_keys=True, ensure_ascii=True, separators=(",", ":"))`, then
SHA-256'd. This hash is compared against the `SourceRecord.payload_hash` already on file
for that `(source_id, external_id)`:

| State | Behavior |
|---|---|
| Not seen before | Create `SourceRecord` (`first_seen_at` = `last_seen_at` = now, `active=true`) and one `SourceSnapshot` with the full raw JSON payload. |
| Seen before, hash unchanged | Update `SourceRecord.last_seen_at` only. No new snapshot. Existing snapshots are never touched. |
| Seen before, hash changed | Update `SourceRecord.payload_hash`, `last_seen_at`, `source_url`, `source_modified_at`. Insert a **new** `SourceSnapshot`; prior snapshots are left exactly as they were written. |

This makes ingestion runs idempotent and safe to re-run repeatedly (e.g. as a
cron/scheduled job later) without inflating storage or losing history.

The FBI item's own `modified` timestamp (an ISO-8601 string) is stored as
`SourceRecord.source_modified_at` when present and parseable; this is informational only
and is not used to decide whether to create a snapshot — the payload hash is the source
of truth for "did anything actually change."

## Known limitations (Phase 1)

- **No removal detection.** This ingestion never sets `SourceRecord.active = false` or
  `removed_at`, even for records that stop appearing in the FBI API. Because pagination
  can be interrupted by transient failures, and a limited/test run only ever sees a
  fraction of the dataset, treating "not seen in this run" as "removed" would produce
  false removals. Removal detection needs a separate, deliberately designed pass (e.g.
  comparing against a known-complete full crawl) and is out of scope here.
- **No missing-person classification.** The FBI Wanted API covers more than missing
  persons (e.g. "Ten Most Wanted", human trafficking, etc.). This ingestion stores
  *every* item returned by the endpoint as a raw `SourceRecord`, regardless of category.
  **Raw ingestion of an FBI Wanted record does not imply that record represents a
  missing-person case.** Deciding which raw records are in scope for the
  missing-persons canonical schema is a normalization/classification decision that has
  not been made yet, and requires first inspecting real `subjects` / category values at
  scale.
- **Structural, not semantic, response validation.** The client validates that a
  response has `total` (int), `page` (int), and `items` (list of objects) — it does not
  validate individual item fields, since imposing a strict per-field schema here would
  itself be a normalization decision, and the FBI API is not contractually documented to
  guarantee field stability.
- **No default full-database fetch anywhere.** Every entry point (the CLI, and
  `run_fbi_ingestion` itself) defaults to fetching a single page. Fetching everything
  requires an explicit `--all-pages` flag or `max_pages=None`.
- **`source_modified_at` parsing is best-effort.** An unparseable `modified` value is
  logged and stored as `NULL` rather than failing the item.

## Running it

```bash
# Safe default: fetch exactly one page (20 items) and ingest it.
docker compose run --rm api python -m ingestion.sources.fbi.cli

# Fetch a specific small number of pages.
docker compose run --rm api python -m ingestion.sources.fbi.cli --max-pages 3

# Fetch everything (not recommended without a reason -- this is >1000 records).
docker compose run --rm api python -m ingestion.sources.fbi.cli --all-pages
```

The `fbi` `Source` row must already exist (created by
`python -m app.services.seed`, part of the base scaffold) before running ingestion.

## Logging

Each run logs, at INFO level: pages fetched, items received per page, and a final
summary of new / changed / unchanged `SourceRecord` counts, snapshots created, and
failures. Individual item failures are logged at WARNING with the `uid` (an opaque FBI
identifier, not a name) and the error — never the full item payload or fields like
`title`, `details`, or `description`.
