# Architecture

## Core principle

> Raw source data is immutable. Normalized data is derived. Canonical data must always be
> traceable to one or more raw source records.

Everything in this platform's data model exists to uphold that sentence. It is the reason
the schema is layered the way it is, and it constrains what future ingestion and linkage
code is allowed to do.

## Data layers

### 1. Raw layer — `Source`, `SourceRecord`, `SourceSnapshot`

This layer is a faithful, append-only record of what an external source (FBI, NamUs, ...)
publishes, and nothing else.

- **`Source`** — a registered data provider (code, name, base URL, type, active flag).
- **`SourceRecord`** — identifies one record at a source by `(source_id, external_id)`
  (enforced with a unique constraint) and tracks its lifecycle: `first_seen_at`,
  `last_seen_at`, `source_modified_at`, and `removed_at` if the source stops publishing it.
  A `SourceRecord` is never deleted when a source removes a listing; it is marked
  `active = false` with a `removed_at` timestamp so history is preserved.
- **`SourceSnapshot`** — an immutable, point-in-time copy of the raw payload
  (`JSONB`) fetched for a `SourceRecord`, with a `payload_hash` and `fetched_at`. Snapshots
  are append-only: a new fetch that differs from the prior payload creates a new snapshot
  row rather than overwriting one. This is what "raw source data is immutable" means
  concretely — the raw layer only ever grows.

Nothing in this layer is written by hand or inferred. It is the direct output of ingestion
pulling from a source.

### 2. Canonical layer — `Person`, `Case`

This layer is the platform's normalized, queryable view: one row per distinct person, one
row per distinct case. Canonical rows are **derived** from raw data — every field here
should be traceable to something a source actually reported, never a value invented,
guessed, or algorithmically inferred by the platform (e.g. no speculative identification,
no facial recognition, no probabilistic entity matching beyond what this document allows).

- **`Person`** — canonical identity fields (name parts, date of birth, sex). Uses a UUID
  primary key since person identity is platform-internal, not tied to any one source's ID
  scheme.
- **`Case`** — canonical case facts (status, missing date/location, circumstances,
  investigating agency). Also UUID-keyed, `person_id` foreign key to `Person`.

### 3. Traceability layer — `CaseSource`

- **`CaseSource`** — the join between a canonical `Case` and the `SourceRecord`(s) it was
  derived from, recording `link_method` (how the link was established, e.g. a deterministic
  key match performed during ingestion) and an optional `link_confidence`. This table is
  what makes the core principle enforceable rather than aspirational: given any `Case`, you
  can always walk `CaseSource` back to the exact `SourceRecord` (and, through
  `SourceSnapshot`, the exact raw payload) that produced it. A `Case` with no `CaseSource`
  row is not traceable and should not exist.

## Why this shape

- **Immutability of raw data** means the platform can always answer "what did the source
  actually say, and when?" — independent of any normalization bugs discovered later.
  Reprocessing normalization logic never requires re-fetching from the source; it replays
  against existing snapshots.
- **Derivation, not invention**, at the canonical layer keeps `Person` and `Case` rows
  auditable: every field change should be explainable by pointing at a source snapshot.
- **Traceability via `CaseSource`** is what distinguishes this platform from a
  speculative-matching system. Linking a `Case` to a `SourceRecord` records *how* the link
  was made and lets a human review or reverse it; it is not a black-box inference.

## Source-adapter contract

Every source is expected to follow the same shape: **fetch → parse → classify (if the
source needs one) → normalize → validate → persist**. `ingestion/sources/base.py` is
where the source-agnostic pieces of that contract live:

- **`NormalizedRecord`** — the common output shape `normalize()` produces for any
  source: a `person_fields` dict and a `case_fields` dict, mapping directly onto
  `Person`/`Case` column names. A field the source didn't report is simply absent —
  never guessed or defaulted.
- **`validate_normalized_record`** — rejects output that can't be safely persisted
  (today: a missing `Person.display_name`, the one canonical column that isn't
  nullable). A rejected record is logged and skipped; it never aborts the batch.
- **`persist_normalized_record`** — the shared, idempotent, provenance-preserving
  write. See "Reconciliation rule" below.

Everything else — the HTTP client, response parsing, and (for FBI) the missing-person
classifier and the field-mapping decisions themselves — is source-specific and lives
under `ingestion/sources/<source>/`. Adding a new source is expected to mean writing
that source's `fetch`/`parse`/`normalize`, not modifying `base.py` or another source's
adapter.

## Reconciliation rule: how sources contribute fields without overwriting each other

`CaseSource` carries a `contributed_fields` column (JSONB): the exact normalized field
values *that specific `SourceRecord`* produced, independent of which of those values
ended up as the canonical value on the linked `Case`/`Person`. This is what makes "two
sources disagree on a field" something the schema can represent without silently
merging: each source's literal contribution stays inspectable on its own `CaseSource`
row, forever, even if it never becomes the canonical value.

`persist_normalized_record` enforces the reconciliation rule structurally, not just by
convention: it looks up an existing link by `source_record_id`, so a `Case`'s canonical
fields can only ever be created or updated by the *same* `SourceRecord` that originally
produced them. It never links a second `SourceRecord` to an existing `Case`. That means
cross-source linkage — and the conflict-resolution policy it would require when two
sources genuinely disagree — has no code path yet in this platform; building it later
requires a deliberate, separate step (see "What this scaffold deliberately does not
do"), not a side effect of normalizing a second source.

## What this scaffold deliberately does not do

FBI raw ingestion and canonical normalization are implemented (see docs/fbi-source.md,
docs/fbi-normalization.md); cross-source linkage and deduplication are not. Any future
work in that direction must:

- Write to the raw layer only by appending (`SourceRecord` upsert-by-external-id,
  `SourceSnapshot` insert-only) — already true of the FBI adapter.
- Populate `Person` / `Case` only from data present in `SourceSnapshot` payloads,
  through an explicit, deterministic `normalize()` function — never inferred.
- Always create a `CaseSource` row (with an honest `link_method`) when associating a `Case`
  with a `SourceRecord` — never leave a canonical case untraceable.
- Avoid any form of speculative identification, facial recognition, or probabilistic
  cross-source identity matching that is not explicitly, transparently recorded via
  `link_method` / `link_confidence` and reviewable by a human. Deciding what happens
  when two sources' `contributed_fields` disagree for the same `Case` is exactly this
  kind of decision — it must be a deliberate, reviewable policy, not a default.
