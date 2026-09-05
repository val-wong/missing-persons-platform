# FBI historical reprocessing (backfill)

## Why this exists

FBI raw ingestion (`Source`/`SourceRecord`/`SourceSnapshot`) was implemented before the
canonical normalization pipeline (`Person`/`Case`/`CaseSource`) existed. Records
raw-ingested during that window were never classified, normalized, or persisted into
the canonical layer — the pipeline simply didn't exist yet when they were fetched. The
same gap can reopen any time a classifier or normalizer bug is fixed: records that were
`OUT_OF_SCOPE` or failed validation under the old logic need to be replayed under the
corrected logic, without re-fetching them from the source.

Reprocessing (`ingestion.sources.fbi.reprocess`) closes that gap: it replays every
already-stored FBI `SourceRecord`'s latest `SourceSnapshot` through the exact same
`classify → normalize → validate → persist` stages live ingestion uses, entirely from
the local database.

## Reprocessing vs. live ingestion

| | Live ingestion (`ingestion.sources.fbi.cli`) | Reprocessing (`ingestion.sources.fbi.reprocess_cli`) |
|---|---|---|
| Data source | FBI Wanted API (network) | Already-stored `SourceSnapshot` rows only |
| Writes to raw layer | Yes — creates/updates `SourceRecord`, appends `SourceSnapshot` | Never — raw layer is read-only here |
| Which records are visited | Only items returned by the fetched pages | Every stored `SourceRecord` for the source |
| Canonical stages used | `classify_fbi_record` → `normalize_fbi_record` → `validate_normalized_record` → `persist_normalized_record` | The exact same four functions — not reimplemented |
| Idempotency | Keyed by `(source_id, external_id)` for raw; `source_record_id` for canonical | Same canonical idempotency contract (raw layer is untouched) |

Both entry points converge on the same canonical persistence function
(`ingestion.sources.base.persist_normalized_record`), so a record processed once by
either path behaves identically if seen again by the other.

## How the latest snapshot is chosen

For each `SourceRecord`, reprocessing selects the one `SourceSnapshot` ordered by
`fetched_at DESC`, tie-broken by `id DESC`. The tie-break matters because two snapshots
can share a `fetched_at` value (e.g. backfilled/imported data); without a deterministic
tie-break, which snapshot "wins" could differ between runs. Ordering by `id DESC` as the
tie-break means insertion order decides, consistently, on every run.

A `SourceRecord` with no snapshot at all is counted (`snapshots_missing`) and skipped —
this is not an error, just an unprocessable record (nothing to classify).

## Commands

```bash
# Preview only -- zero canonical writes. Safe to run any time, as often as needed.
docker compose run --rm api python -m ingestion.sources.fbi.reprocess_cli

# Actually persist canonical Person/Case/CaseSource rows for IN_SCOPE records.
docker compose run --rm api python -m ingestion.sources.fbi.reprocess_cli --execute
```

Like `ingestion.sources.fbi.cli`, a bare invocation is always the safe option: dry run
is the default, and `--execute` must be passed explicitly to write anything.

## Output counters

```
dry_run=<bool> records_inspected=<n> snapshots_missing=<n> in_scope=<n> out_of_scope=<n>
validation_failed=<n> [would_]created=<n> [would_]updated=<n> [would_]unchanged=<n> failures=<n>
```

- `records_inspected` — every `SourceRecord` for the source, regardless of scope.
- `snapshots_missing` — inspected records with no `SourceSnapshot` at all.
- `in_scope` / `out_of_scope` — the Phase 1 classifier's verdict on the latest snapshot.
- `validation_failed` — `in_scope` records whose normalized output failed
  `validate_normalized_record` (e.g. no usable `display_name`).
- `created` / `updated` / `unchanged` — the `persist_normalized_record` outcome for each
  successfully validated record. In dry-run output these are prefixed `would_` because
  no write is retained (see below), but the values themselves come from actually calling
  `persist_normalized_record`, not from a separate prediction of its logic.
- `failures` — records that raised an unexpected exception; logged with their
  `source_record_id`/`external_id` and skipped. One bad record never aborts the run.

## Dry-run guarantee

Dry-run does not simply skip the call to `persist_normalized_record` — it calls it for
real, inside a `SAVEPOINT` (`db.begin_nested()`), and then forces a `ROLLBACK TO
SAVEPOINT` before moving to the next record. This means the `created`/`updated`/
`unchanged` decision is never duplicated in a second, drift-prone implementation, while
still guaranteeing — at the transaction level, not by convention — that `Person`,
`Case`, and `CaseSource` are left byte-for-byte unchanged. `test_fbi_reprocess.py`
asserts this directly by counting rows after a dry run.

## Idempotency guarantees

- Re-running reprocessing (in `--execute` mode) after nothing has changed reports
  `created=0 updated=0` and `unchanged=<in_scope count>` — no duplicate `Person`/`Case`/
  `CaseSource` rows are ever created.
- A record already canonicalized by live ingestion is a no-op if reprocessed (and vice
  versa) — both paths key persistence off the same `source_record_id`.
- A `SourceRecord`'s canonical fields can only ever be created/updated by that same
  `SourceRecord` — reprocessing never links a second `SourceRecord` to an existing
  `Case`, never merges two different `SourceRecord`s, and performs no cross-source or
  similarity-based matching. This is enforced structurally by
  `persist_normalized_record` (see docs/architecture.md), not by convention here.

## Limitations

- FBI-only. No cross-source linkage, no LLM involvement, no automatic person
  deduplication — none of that exists anywhere in this platform yet.
- Never fetches the FBI API and never modifies `SourceRecord`/`SourceSnapshot` rows —
  raw provenance is immutable input here, exactly as for live ingestion.
- Only ever considers each record's *latest* snapshot. It does not replay intermediate
  historical snapshots even if several exist.
