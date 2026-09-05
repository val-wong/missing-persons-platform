# FBI → canonical normalization

## Implementation status

The five mappings in "SAFE FIELD MAPPINGS" below, plus the four physical-detail
mappings in "PHYSICAL DETAIL FIELD MAPPINGS (implemented)" further down, are
implemented in `ingestion/sources/fbi/normalize.py` (`normalize_fbi_record`) and wired
into `ingestion/sources/fbi/service.py`: raw-ingested items that the Phase 1 classifier
marks `IN_SCOPE` are normalized, validated (only `Person.display_name` being unset is
rejected — see docs/architecture.md), and persisted via
`ingestion.sources.base.persist_normalized_record`. Every other canonical field this
document marks `NOT_AVAILABLE` or `AMBIGUOUS` is left `NULL` for FBI records, exactly as
recommended below — this implementation does not relitigate those findings.

The rest of this document is the original discovery-only analysis that justified the
first five mappings; it is retained as-is below for traceability. "Physical description
/ photo fields" (further down) is a later, separate discovery pass that added
`height_min`/`height_max`/`weight`/`hair`/`hair_raw`/`eyes`/`eyes_raw`/`race`/
`race_raw`/`scars_and_marks`/`images`/`aliases` to the picture; a subsequent
field-evidence audit resolved four of those fields to HIGH confidence (see "PHYSICAL
DETAIL FIELD MAPPINGS (implemented)"), now implemented, while height, weight, images,
and race remain deliberately unmapped for the reasons given there.

---

## Scope

This document is the output of a **read-only structural analysis pass** over the
latest stored `SourceSnapshot` of every FBI record the Phase 1 classifier
(`ingestion/sources/fbi/classifier.py`) marks `IN_SCOPE` / `MISSING_PERSON` (see
[fbi-classification.md](fbi-classification.md)). It exists to answer: *which
structured FBI fields can we safely, deterministically map into the canonical
`Person` and `Case` models?* It does **not** implement normalization — no `Person`,
`Case`, or `CaseSource` row was created to produce this document, and no
`SourceRecord` / `SourceSnapshot` data was read, modified, or overwritten beyond
normal `SELECT`s.

Reproduce this report at any time (read-only, no writes, no network calls):

```bash
docker compose run --rm api python -m ingestion.sources.fbi.normalization_report_cli
```

**Sample:** 103 `IN_SCOPE` FBI records (of 400 currently stored), as of the classifier
report run in [fbi-classification.md](fbi-classification.md).

No individual field value that identifies or describes a person (name, DOB, physical
description, free-text narrative, location content) appears anywhere in this document
or in the report tool's output — only field names, JSON types, presence/null/empty
counts, percentages, and structural pattern-match counts.

---

## OBSERVED SOURCE STRUCTURE

All 103 `IN_SCOPE` records exhibit the same 54-field schema seen throughout prior FBI
discovery work (see [fbi-classification.md](fbi-classification.md)). Every field is
present as a *key* on all 103 records; population (non-null, non-empty) varies widely.
Selected fields relevant to canonical mapping (full per-field stats are in the live
report output, not reproduced verbatim here since some entries are single-digit counts
that would otherwise implicitly disclose which few records are populated):

| Field | Types observed | Notes |
|---|---|---|
| `title` | `str` | Present & populated on 103/103. The **only** name-bearing field. |
| `aliases` | `list`, `NoneType` | Populated (non-empty list) on 12/103. |
| `given_name` / `first_name` / `middle_name` / `last_name` / `family_name` / `surname` / `name` | — | **Not found on any record.** No structured name-component field exists. |
| `dates_of_birth_used` | `list`, `NoneType` | Populated on 33/103 (~32%). See DOB investigation below. |
| `place_of_birth` | `str`, `NoneType` | Populated on 12/103. Means birthplace, not disappearance location. |
| `locations` | `NoneType` | Populated on **0/103**. Key exists, never has a value. |
| `field_offices` | `list`, `NoneType` | Populated on 29/103 (~28%); FBI field-office slugs (e.g. an office name), not incident location. |
| `possible_states` | `list`, `NoneType` | Populated on 21/103 (~20%); the field name itself signals uncertainty. |
| `possible_countries` | `NoneType` | Populated on **0/103**. |
| `coordinates` | `list` (always present as a list) | Non-empty on 2/103 (~2%); undocumented semantics. |
| `publication` | `str` | Present & populated on 103/103. Poster publication timestamp (naive, no timezone in observed samples), not an event date. |
| `modified` | `str` | Present & populated on 103/103. Poster last-modified timestamp (with UTC offset), not an event date. |
| `status` | `str` | Always `"na"` on all 103 `IN_SCOPE` records — zero variance within this population. |
| `poster_classification` | `str` | `missing` (37), `default` (66) within this population — matches the classifier's OR logic exactly. |
| `person_classification` | `str` | `Main` (58), `Victim` (45). Describes the person's *role on the poster*, not case status. |
| `ncic` | always `null` | Populated on **0/103**. No case/docket-number-shaped field exists anywhere in the schema. |
| `age_min` / `age_max` | `int`, `NoneType` | Populated on 65/103 each. |
| `age_range` | `str`, `NoneType` | Populated on 66/103; despite the name, contains no hyphen in any observed value (format inconsistent with a literal "min-max" range string) — its actual structure requires further review before any use, independent of the semantic ambiguity below. |
| `sex` | `str`, `NoneType` | Populated on 101/103 (1 `null`, 1 blank string, 101 populated). |

---

## PRODUCT SCOPE DECISIONS

These are restated from [fbi-classification.md](fbi-classification.md) for context,
not re-decided here: this document only concerns *how* to map fields for records
already deemed `IN_SCOPE`. One new scope-adjacent decision this document makes:

- **Verbatim free text may be stored in a free-text canonical field without being
  "inference."** Copying FBI's `description` field byte-for-byte into
  `Case.circumstances` is data movement, not fact extraction — no structured fact
  (date, location, agency) is parsed out of it. This is distinct from, and does not
  contradict, the rule against using free text to *derive* structured fields like
  `missing_date` or `missing_city`.

---

## Name investigation (rule 5)

- `title` is present and populated on **103/103** records.
- No dedicated first/middle/last/family-name field exists anywhere in the observed
  schema (checked explicitly: `given_name`, `first_name`, `middle_name`, `last_name`,
  `family_name`, `surname`, `name` — none found).
- `aliases` (a list, populated on 12/103) is name-*adjacent* but holds alternate names,
  not components of the primary name, and there is no canonical field for it.

**Conclusion: `title` is the only practical display-name field, and there is no way to
safely split it into `given_name` / `middle_name` / `family_name` / `suffix` without
guessing.** Per rule 5, we do not attempt that split. Recommendation: map `title` →
`Person.display_name` directly; leave `given_name`, `middle_name`, `family_name`,
`suffix` `NULL`.

## Date-of-birth investigation (rule 6)

Field: `dates_of_birth_used`.

- Type: always either `list` or `NoneType` — never a bare string or other shape.
- Null/absent: 70/103 (~68%).
- **List-length distribution when populated: `{1: 33}` — every single populated
  occurrence has exactly one entry.** Zero records have more than one.
- Format check (structural pattern match only, values never printed): of the 33
  single-entry cases, **30 match a `"Month D, YYYY"` pattern; 3 do not.** The field is
  free-text-shaped even when structurally single-valued — roughly 9% of populated
  values would fail a naive fixed-format parse.

**Conclusion:** accepting a DOB is safe **only** when (a) the field is a list with
exactly one entry, and (b) that entry parses against a known date format — with a
fail-closed policy (parse failure → leave `NULL`, never guess). Because 100% of
observed populated cases already have exactly one entry, condition (a) is not
currently a practical obstacle — but the code must still handle a hypothetical
multi-entry list by refusing to choose among the values, per rule 6, rather than
assuming today's 100%-single-value pattern will always hold.

## Missing-date investigation (rule 7)

No field named or shaped like a missing/disappearance date exists anywhere in the
54-field schema. The only date-shaped fields are:

- `publication` (103/103 populated) — when the FBI *published the poster*.
- `modified` (103/103 populated) — when the FBI *last edited the poster* on their
  system (already captured, appropriately, as `SourceRecord.source_modified_at`).
- `dates_of_birth_used` — birth date, not disappearance date (see above).

None of these describe the missing-person event. Per rule 7, none may be substituted
for `missing_date`.

**Conclusion: `missing_date` — NOT_AVAILABLE. Recommend `NULL` for every record until
(if ever) a field with a clearly established "date this person was reported/went
missing" meaning is identified.**

## Location investigation (rule 8)

None of the location-adjacent fields observed carry an established "where this person
went missing" meaning:

- `place_of_birth` (12/103 populated) — explicitly a birthplace, not a disappearance
  location. Mapping it to `missing_city`/`missing_state` would be a direct semantic
  error the task explicitly warns against.
- `locations` — key always present, **never populated (0/103)**. Structurally
  unusable regardless of intended meaning.
- `field_offices` (29/103 populated) — identifies which FBI office(s) are handling the
  case. Correlates loosely with geography but is an administrative/organizational
  field, not a location-of-incident field; translating an office identifier into a
  state would also require an external lookup table this platform does not have and
  the source does not provide.
- `possible_states` (21/103 populated) — the name itself ("possible") signals FBI's
  own uncertainty; it's a list of *candidate* states, not a confirmed single location.
- `possible_countries` — never populated (0/103).
- `coordinates` — populated on only 2/103 (~2%), with no documented meaning attached
  (could represent an office, a last-known location, or something else entirely —
  unconfirmed).

**Conclusion: `missing_city`, `missing_county`, `missing_state`, `missing_country` —
NOT_AVAILABLE. Recommend `NULL` for all four, for every record, in Phase 1.**

## Agency / case-number investigation

- `ncic` (the one field name that could plausibly hold an external case reference) is
  **never populated (0/103)** — the key exists but the FBI does not appear to actually
  fill it in for any record in this sample.
- No other field resembling a case/docket number exists in the schema.
- `field_offices`, when populated (29/103), names which FBI office(s) are associated
  with the record — this is *investigating-agency-adjacent* structured data, though
  translating an office slug into an agency name still requires a lookup table not
  provided by the source.
- Separately, and requiring no per-record field parsing at all: **every record in this
  dataset was, by definition, ingested from the FBI** (`Source.code == "fbi"`). That
  fact alone deterministically supports a constant value for `investigating_agency`,
  independent of any specific FBI field's content.

**Conclusion: `agency_case_number` — NOT_AVAILABLE (recommend `NULL`).
`investigating_agency` — SAFE_WITH_DETERMINISTIC_TRANSFORMATION, using the constant
`"Federal Bureau of Investigation"` derived from the known source, not from parsing a
variable field.**

## Multi-person structural signal investigation (rule 9)

Two purely structural signals were checked, without inspecting `title`/`description`
content:

- `dates_of_birth_used` with more than one entry: **0/103** records. If a record
  legitimately described multiple people, each with their own birth date, this is the
  one field structurally shaped to reveal it — and it never does, in this sample.
- Image-count distribution (a weak proxy at best, since one person commonly has
  multiple photos — e.g. an original photo plus an age-progressed rendering):
  1 image (49 records), 2 (30), 3 (15), 4 (4), 5 (1), 6 (3), 7 (1). A record having
  several images is not distinguishable, from image count alone, between "one person,
  several photos" and "several people, one photo each."

**Conclusion:** no field in the structured schema reliably distinguishes single-person
from multi-person records. The one field that plausibly could (`dates_of_birth_used`)
shows no multi-value cases in the current `IN_SCOPE` sample, which is *some* evidence
against multi-person records being common — but it is not proof none exist, since a
multi-person poster with a single quoted birth date, or none at all, would be
indistinguishable from a single-person record using only these fields. This platform
does not currently have a reliable structural way to detect or reject
multiple-people-per-record cases; per rule 9, we report this as an open structural
gap rather than attempt to resolve it via title/description content inspection, which
was explicitly out of scope for this analysis.

---

## SAFE FIELD MAPPINGS

| FBI field | → Canonical field | Transformation | Confidence |
|---|---|---|---|
| `title` | `Person.display_name` | none (verbatim copy) | **SAFE_DIRECT** |
| `sex` | `Person.sex` | none (verbatim copy; canonical field is an unconstrained string) | **SAFE_DIRECT** |
| `description` | `Case.circumstances` | none (verbatim copy of free text into free text; no fact extraction) | **SAFE_DIRECT** |
| `dates_of_birth_used[0]` | `Person.date_of_birth` | parse `"Month D, YYYY"` → date; **fail-closed to `NULL`** if list has ≠1 entry or the entry doesn't match the known format | **SAFE_WITH_DETERMINISTIC_TRANSFORMATION** |
| *(known source, not a field)* | `Case.investigating_agency` | constant `"Federal Bureau of Investigation"` | **SAFE_WITH_DETERMINISTIC_TRANSFORMATION** |
| `uid` | `SourceRecord.external_id` | none | already implemented (raw ingestion) |
| `url` | `SourceRecord.source_url` | none | already implemented (raw ingestion) |
| `modified` | `SourceRecord.source_modified_at` | ISO-8601 parse | already implemented (raw ingestion) |

`publication` is not currently captured anywhere in the canonical or `SourceRecord`
schema. It is structurally reliable (103/103 populated, consistent ISO-ish format) but
has no target field today — noted for potential future schema work, not a Phase 1
mapping.

## AMBIGUOUS FIELDS

| FBI field(s) | Candidate canonical field | Why ambiguous |
|---|---|---|
| `age_min` / `age_max` / `age_range` | `Case.age_at_missing` | Cannot establish whether these represent age *at time of disappearance* or *current estimated age* (FBI posters are known to use age-progressed imagery, implying at least some age fields track present-day estimates, not the age when the person went missing). Structural presence (65-66/103) does not resolve this semantic question. `age_range`'s format also doesn't match its own name (no hyphen observed in any sample), so even its literal content shape needs review independent of the semantic issue. |
| `status` | `Case.case_status` | Field exists and has multiple values across the full FBI dataset (`na`, `captured`, `deceased`, `resolved`, `surrendered` — see fbi-classification.md), but is **constant (`"na"`) across 100% of the current `IN_SCOPE` population**, providing zero discriminating signal for this specific record set. Its intended semantics (FBI case handling status) are also not confirmed to align with what our `case_status` workflow field is meant to represent. |
| `field_offices` | `Case.investigating_agency` (refinement) | Could in principle sharpen the agency value to a specific field office (e.g. "FBI Honolulu"), but requires an office-slug-to-name lookup table this platform does not have and the source does not supply; only populated on 29/103 records. |
| `possible_states` | `Case.missing_state` | Explicitly a list of *candidate* states per its own name — inherently non-deterministic to reduce to one value. |

## UNAVAILABLE CANONICAL FIELDS

| Canonical field | Verdict | Why |
|---|---|---|
| `Person.given_name`, `Person.middle_name`, `Person.family_name`, `Person.suffix` | **NOT_AVAILABLE** | No structured name-component field exists; only `title` (whole display name) is available. |
| `Case.missing_date` | **NOT_AVAILABLE** | No field represents this event; only administrative poster timestamps (`publication`, `modified`) and unrelated birth dates exist. |
| `Case.missing_city`, `Case.missing_county`, `Case.missing_state`, `Case.missing_country` | **NOT_AVAILABLE** | No field reliably represents "where this person went missing"; candidates found (`place_of_birth`, `field_offices`, `possible_states`, `coordinates`) each have a different, non-substitutable meaning or near-zero/uncertain coverage. |
| `Case.agency_case_number` | **NOT_AVAILABLE** | `ncic` is the only plausibly-matching field name and is never populated (0/103). |
| `Case.age_at_missing` | **NOT_AVAILABLE** (ambiguous, treated conservatively as unavailable for Phase 1) | See Ambiguous Fields — temporal meaning of age fields is unresolved. |
| `Case.case_status` | **NOT_AVAILABLE** for Phase 1 | `status` is constant across the entire `IN_SCOPE` population; provides no per-record signal today. |

## DETERMINISTIC TRANSFORMATIONS

Only two are proposed, both fully specified and fail-closed (never guess; leave `NULL`
on any doubt):

1. **DOB parse:** `dates_of_birth_used` → `Person.date_of_birth`. Applies only when
   the field is a list with exactly one string entry that matches a `"Month D, YYYY"`
   pattern (e.g. via `datetime.strptime(value, "%B %d, %Y")`, with the exact format
   string to be finalized against a fuller sample when this is actually implemented).
   Any other shape (missing, empty, multiple entries, non-matching format) → `NULL`.
   Per rule 6, this transformation must never choose among multiple values — a
   multi-entry list yields `NULL`, not a first/last/arbitrary pick.
2. **Constant agency value:** `Case.investigating_agency` = `"Federal Bureau of
   Investigation"` for every record ingested from the `fbi` `Source`. Derived from
   which `Source` produced the record, not from parsing any FBI-supplied field value —
   this is why it is a "transformation" rather than a direct field copy despite being
   a single constant.

No other transformation is proposed. In particular, no attempt is made to: split
`title` into name components; parse a location out of `possible_states` /
`field_offices` / `coordinates`; derive `missing_date` from `publication` or
`modified`; or infer `age_at_missing` from `age_min`/`age_max`.

## FIELDS WE WILL NOT INFER

Per rules 3, 5, 7, 8, and 11, the following are explicitly **not** used to derive any
canonical field value in Phase 1, regardless of how suggestive their content might be:

- `title`, `description`, `details`, `remarks`, `caution`, `additional_information`,
  `warning_message` — free text. `description` is permitted as a **verbatim copy**
  into `Case.circumstances` (no parsing), but none of these fields are scanned,
  parsed, or NLP-processed to extract a date, location, agency, or name.
- `publication`, `modified` — never substituted for `missing_date`, regardless of how
  tempting a fallback they might seem.
- `place_of_birth`, `field_offices`, `possible_states`, `possible_countries`,
  `coordinates` — never substituted for a missing-location field.
- `age_min`, `age_max`, `age_range` — never mapped to `age_at_missing` given the
  unresolved current-age-vs-age-at-disappearance ambiguity.
- `status` — never mapped to `case_status` given it is constant across the current
  `IN_SCOPE` population and its semantics relative to our workflow are unconfirmed.
- No LLM or free-text NLP model is used anywhere in this analysis or in any proposed
  transformation.

---

## Physical description / photo fields (evidenced, not yet mapped)

A separate, later discovery pass (same read-only methodology, run against 104 currently
stored `IN_SCOPE` records) checked whether the FBI schema carries usable structured
fields for `Person.height_cm` / `weight_kg` / `hair_color` / `eye_color` /
`distinguishing_characteristics` / `photo_urls` — none of which the original discovery
rounds above investigated (they were scoped to name/DOB/location/agency only).

**Finding: these fields exist and are well-populated** — unlike `missing_date` or
`missing_city`, which were confirmed absent. Structural population, `IN_SCOPE` sample
(n=104):

| FBI field(s) | Types | Populated |
|---|---|---|
| `eyes`, `eyes_raw` | `str`, `NoneType` | 98/104 (94%) |
| `hair`, `hair_raw` | `str`, `NoneType` | 96–99/104 (92–95%) |
| `height_min`, `height_max` | `int`, `NoneType` | 95/104 (91%) |
| `weight` (str), `weight_min`, `weight_max` (int) | mixed | 95/104 (91%) |
| `race`, `race_raw` | `str`, `NoneType` | 96/104 (92%) |
| `scars_and_marks` | `str`, `NoneType` | 44/104 (42%) |
| `images` | `list` | 104/104 (100%) |
| `complexion`, `build` | `str`, `NoneType` | 1/104, 4/104 — too sparse to be useful |
| `aliases` | `list`, `NoneType` | 12/104 (12%), matches the original 12/103 finding above |

**Not yet resolved — mapping these requires answering these first, not implemented
here:**

- **`hair` vs. `hair_raw`, `eyes` vs. `eyes_raw`, `race` vs. `race_raw`**: two variants
  exist for each and this pass did not determine which is FBI's own literal/verbatim
  value vs. a normalized/controlled-vocabulary value FBI derives from it. Requirement 1
  of this platform's canonical schema calls for storing physical description "exactly
  as reported by the source" — picking the wrong variant would violate that without
  being obviously wrong to a casual reader.
- **Units for `height_min`/`height_max`/`weight_min`/`weight_max`**: structurally
  `int`, but the unit (inches vs. cm, lb vs. kg) was not confirmed against FBI
  documentation or by inspecting values in this pass. `Person.height_cm`/`weight_kg`
  are named assuming metric storage; converting the wrong assumed unit would silently
  corrupt every value rather than fail loudly.
- **`images` list shape**: confirmed to be a populated list on every sampled record,
  but which key inside each list entry holds the actual photo URL (vs. a thumbnail,
  caption, or other metadata) was not inspected in this pass.

Per the same fail-closed policy used throughout this document: none of `height_cm`,
`weight_kg`, `hair_color`, `eye_color`, `photo_urls` are mapped until those questions
are answered. `aliases` is the one exception worth calling out as lower-risk — it's a
direct list-of-strings copy with no unit or raw/normalized ambiguity — but is still left
unmapped in this pass since resolving it in isolation, separately from its
higher-ambiguity siblings, was judged not worth a second partial implementation pass.
`distinguishing_characteristics` ← `scars_and_marks` is comparatively low-risk (free
text → free text, same "verbatim copy is not inference" reasoning already applied to
`description` → `Case.circumstances`) and is the best next candidate once this batch of
mappings is picked up.

---

## PHYSICAL DETAIL FIELD MAPPINGS (implemented)

A follow-up field-evidence audit (read-only, same 104 `IN_SCOPE` records) resolved four
of the open questions above to `HIGH` confidence. These four are now implemented in
`normalize_fbi_record`; the rest of this section records the evidence and reasoning so
a future editor doesn't have to re-derive it.

| FBI field | → Canonical field | Transformation | Confidence |
|---|---|---|---|
| `hair_raw` | `Person.hair_color` | verbatim copy, blank/absent → `NULL` | **HIGH** |
| `eyes_raw` | `Person.eye_color` | verbatim copy, blank/absent → `NULL` | **HIGH** |
| `aliases` | `Person.aliases` | deterministic `list[str]` copy, empty/absent/any-non-string-or-blank-element → `NULL` | **HIGH** |
| `scars_and_marks` | `Person.distinguishing_characteristics` | verbatim copy, blank/absent → `NULL` | **HIGH** |

### Why `_raw`, never the FBI-normalized `hair`/`eyes` bucket

`hair` and `eyes` are FBI's own small, fixed, lowercase controlled vocabularies (4 and 6
distinct values respectively, across the full `IN_SCOPE` sample) — evidently a bucketed
classification FBI derives for its own search/filter facets, not the literal reported
description. `hair_raw`/`eyes_raw` carry the fuller, human-authored text (46 and 10
distinct values respectively), including detail the bucketed field discards (length,
styling, dye, compound descriptions, accessory notes).

This was confirmed structurally, not assumed from field naming: for every populated
pair in the sample, the lowercased `_raw` value **starts with or contains** the
corresponding bucketed value (`hair`: 96/96; `eyes`: 98/98 — 100% in both cases; the
same check on `race`/`race_raw`, not mapped, was also 96/96). The bucketed field is
never independent of, or in conflict with, its `_raw` counterpart in this sample — it
is a strict simplification of it.

Per this platform's core principle (docs/architecture.md: canonical data must be
traceable to, and faithful to, what the source actually reported), the `_raw` variant
is the correct mapping target: it preserves what FBI's poster literally says, rather
than substituting FBI's own downstream, lossy re-bucketing. `hair`/`eyes` are never used
as a fallback when `_raw` is absent — code and tests both enforce this (there is no
plausible case in the current schema where `_raw` is null but the bucketed value would
be a safe substitute, since the bucket is *derived from* the raw text, not an
independent report).

### `aliases`

Verified: always `list[str]` when populated (12/104, 11.5%), no blank elements, no
internal duplicates in any observed record. `ingestion.normalize.text.clean_string_list`
accepts the list verbatim only when it is a non-empty list where every element is a
non-blank string; any other shape (not a list, empty, or containing a non-string/blank
element) is rejected **as a whole** — this never partially filters or rewrites
individual alias entries, per the "do not invent, normalize, split, deduplicate" rule.

### `scars_and_marks`

Always `str`/`NoneType` (44/104 populated, 42%), free-text prose (2–62 words). Same
"verbatim copy of free text is data movement, not inference" reasoning already
established for `description` → `Case.circumstances`: copied byte-for-byte via
`blank_to_none`, with no fact extraction from the prose.

### Length note

`Person.hair_color`/`Person.eye_color` are `String(64)`. The longest observed
`hair_raw`/`eyes_raw` value in the current dataset is 56 characters (well within the
column width). This is not a mapping-safety guarantee for all future FBI data — an
unusually long future value would fail loudly at insert time (a `String(64)` length
violation), not silently truncate or corrupt, which is consistent with this platform's
fail-closed philosophy, but is worth knowing if it is ever actually hit.

### Still intentionally unmapped: height, weight, images, race

- **`height_min`/`height_max` → `Person.height_cm`**: the unit could not be proven with
  the same rigor as weight (no sibling free-text `height` string exists to cross-check
  against, unlike `weight`). Numeric range evidence (36–96, median 66) is consistent
  with inches and implausible as centimeters for this population, but this is
  circumstantial, not proof — **confidence: MEDIUM at best**. Independently, ~17% of
  populated records report a genuine `height_min ≠ height_max` range, which a single
  `height_cm` float cannot represent without a collapse policy (min/max/average) that
  has not been decided. Both issues must be resolved before implementation.
- **`weight`/`weight_min`/`weight_max` → `Person.weight_kg`**: unit is proven **HIGH**
  confidence — the free-text `weight` field states "pounds" directly and its number
  matches `weight_min`/`weight_max` exactly (e.g. `"130 pounds"` ↔ `130`/`130`). Despite
  the proven unit, implementation is still blocked by (a) ~24% of populated records
  being genuine ranges (up to 108 lb apart), and (b) some `weight` strings carrying an
  explicit "at the time of her disappearance" qualifier not reflected anywhere on
  `weight_min`/`weight_max` — the same current-vs-at-disappearance ambiguity already
  identified for `age_min`/`age_max` above, now shown to also apply to weight for at
  least a subset of records.
- **`images` → `Person.photo_urls`**: every image object has exactly the same four
  keys — `original` (the unscaled uploaded file), `large` (a pre-rendered display-size
  rendition), `thumb` (an explicit small thumbnail), and `caption` (populated on 31% of
  the 201 image objects sampled). `thumb` should never be the mapping target; `large`
  vs. `original` is a legitimate policy choice, not something the evidence alone
  settles. More importantly, collapsing to one URL string per image permanently drops
  `caption` and the alternate-size variants — whether `photo_urls` should hold flat
  URL strings or `{url, caption}`-style objects is an undecided data-shape convention,
  not a migration (the column is already flexible JSONB).
- **`race`/`race_raw`**: same normalized/verbatim relationship as hair/eyes was
  confirmed (100% containment), but `Person` has no `race` column, and adding one is a
  distinct product decision (whether to represent race at all, and how) rather than a
  mapping detail. `race`/`race_raw` remain source-only — preserved forever in
  `SourceSnapshot`, not promoted to the canonical schema in this pass.
