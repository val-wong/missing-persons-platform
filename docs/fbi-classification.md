# FBI record classification — discovery findings (evidence gathering only)

## Scope

This document is the output of a **read-only analysis pass** over FBI `SourceSnapshot`
data already stored via [fbi-source.md](fbi-source.md) raw ingestion. It exists to
answer one question: *is there a safe, deterministic way to tell which FBI Wanted API
records are missing-person-related?* It reports what was observed — it does **not**
implement a classifier anywhere in the ingestion or normalization pipeline. No `Person`
or `Case` records were created to produce this document, and no `SourceRecord` /
`SourceSnapshot` data was modified.

The report is reproducible and re-runnable at any time (read-only, no network calls):

```bash
docker compose run --rm api python -m ingestion.sources.fbi.report_cli
```

This document has two dated rounds of discovery findings (below), plus a third section
documenting the **Phase 1 classifier that was ultimately implemented** from that
evidence. The second (400-record) discovery round **supersedes** several conclusions
from the first — most notably, a pattern that held cleanly at 100 records
(`poster_classification == "missing"` implies `subjects` contains `"Kidnappings and
Missing Persons"`) broke at 400 records. That reversal is itself the main finding of
that round: **more data revealed more structure, not convergence.**

---

## Phase 1 classifier (implemented)

This section documents `ingestion/sources/fbi/classifier.py`, the first implemented
deterministic classifier, built from the discovery evidence in the two rounds below. Per
the task that introduced it, the four parts below are kept explicitly separate: what the
data showed, what this platform decided to do about it, exactly what the code does, and
what is still not resolved.

**Where each part lives / how to reproduce it:**

```bash
# Read-only aggregate classifier report over currently stored FBI records:
docker compose run --rm api python -m ingestion.sources.fbi.classifier_report_cli
```

The classifier is a pure function, `classify_fbi_record(payload: dict) -> ClassificationResult`,
with no database access and no free-text field reads. Tests:
`apps/api/tests/test_fbi_classifier.py` (unit, pure-function) and
`apps/api/tests/test_fbi_classifier_report.py` (DB-backed aggregation, read-only).

### OBSERVED FBI DATA

This is empirical fact from the FBI API, established by the read-only discovery work in
Round 1 and Round 2 below (full detail there; summarized here as the classifier's
evidentiary basis):

- `poster_classification` is a short scalar label. Across 400 sampled records, exactly
  9 distinct values were ever observed: `missing`, `kidnapping`, `default`,
  `information`, `fraudster`, `ecap`, `law-enforcement-assistance`, `ten`, `terrorist`.
- `subjects` is a list of string category labels, always present as a list when present
  at all in the sample (never null, never a non-list type, never empty), and can hold
  more than one value (up to 3 observed). 28 distinct labels were observed across 400
  records.
- `poster_classification == "missing"` and `subjects` containing `"ViCAP Missing
  Persons"` are **disjoint, non-overlapping-by-construction observed sets** except for
  a genuine 8-record overlap discovered only at n=400 (8 of 37 "missing"-classified
  records carry `subjects == ["ViCAP Missing Persons"]` and nothing else).
- `subjects` containing `"Kidnappings and Missing Persons"` is, empirically, **always**
  accompanied by `poster_classification` in `{missing, kidnapping}` — no exception in
  400 records.
- `"ViCAP Unidentified Persons"`, `"ECAP"` / `"Endangered Child Alert Program"`, and
  `"Human Trafficking"` are each observed as subject labels structurally disjoint from
  the missing-persons-positive signals above.
- `person_classification` (`Main` / `Victim`) does not correlate in any way this
  analysis could establish with whether a record is a missing-person case — it looks
  like it describes the *role* of the person the poster concerns (primary subject vs.
  victim of someone else's case), not missing-person status.
- The FBI does not publish a documented, versioned schema for any of these
  classification fields. Everything above is inferred from observed sample data, not
  from FBI documentation.

### PRODUCT SCOPE DECISIONS

**These are this platform's own policy decisions, not FBI policy or FBI
classification.** The FBI does not define "in scope for a missing-persons
aggregation platform" — this platform does, and the decisions below were made
deliberately narrow (conservative / high-precision, lower-recall) for a first
implementation:

1. **In scope for Phase 1:** a record is treated as a missing person if and only if the
   FBI itself has tagged it `poster_classification == "missing"`, OR tagged it with the
   subject `"ViCAP Missing Persons"`. Both are direct, explicit FBI-supplied signals —
   nothing is inferred beyond reading these two fields.
2. **Explicitly out of scope for Phase 1, even though related to the broader
   missing/unidentified-person domain:**
   - Kidnapping-in-progress cases (`poster_classification == "kidnapping"`, and the
     `"Kidnappings and Missing Persons"` subject on its own) — a kidnapping is not
     automatically treated as a missing-person case in Phase 1. This is a scope
     narrowing decision, not a claim that kidnapping victims aren't in some sense
     missing.
   - `"ViCAP Unidentified Persons"` — unidentified-remains/persons cases are a
     conceptually distinct problem from missing-*living*-persons and are explicitly
     excluded from Phase 1 scope, regardless of the word "Persons" appearing in the
     label.
   - `"ECAP"` / `"Endangered Child Alert Program"` — missing/abducted-child alerts are
     excluded from Phase 1 scope pending a separate, deliberate decision about whether
     and how to include them (this program has its own alerting semantics that may
     warrant separate handling rather than being folded into general missing-person
     classification).
   - Human-trafficking classifications — excluded from Phase 1 scope; trafficking and
     missing-persons are related but distinct categories.
3. **`person_classification` must never independently influence scope.** Decided
   because it appears to encode the person's *role* in the poster (primary subject vs.
   victim), not their missing/present status, and using it risked conflating "this
   record is *about* someone" with "this record is a missing-person case."
4. **No inference from free text.** Title, description, details, remarks, images,
   locations, and any other free-text or media field are never read by the classifier,
   even though they likely contain highly relevant information (e.g. an explicit
   statement that someone is missing). This is a deliberate scope limit, not an
   oversight: free-text inference is exactly the kind of speculative interpretation this
   platform's architecture rules out (see [architecture.md](architecture.md)).
5. **Unrecognized values are never assumed to be out of scope.** When the classifier
   encounters a `poster_classification` or `subjects` value it has not seen in the
   discovery rounds, it reports `UNCLASSIFIED` rather than guessing either way. This
   was chosen so that new FBI taxonomy additions surface for human review instead of
   silently vanishing from (or silently entering) the aggregation pipeline.

### IMPLEMENTED DETERMINISTIC RULES

Implemented in `ingestion/sources/fbi/classifier.py`, function `classify_fbi_record`.

**Inputs read:** `poster_classification` (string), `subjects` (list of strings) only.
**Inputs never read:** everything else, including `person_classification`.

**Normalization policy** (documented and tested):
- `poster_classification`: trimmed of surrounding whitespace, compared
  case-insensitively (`"  MISSING "` matches `"missing"`). Justification: observed
  values look like machine-generated slugs where case carries no meaning.
- `subjects` entries: trimmed of surrounding whitespace, compared with **exact
  case-sensitive** string equality. Justification: these are FBI-authored category
  labels; an unexpected casing is one of the few signals available that a value might
  not be the label we think it is, so it is treated as unrecognized rather than
  silently folded into a known label.
- `subjects` is only read when it is an actual JSON list. Any other shape (string, null,
  missing key, number, object, boolean) contributes no signal — it is never
  substring-matched against a serialized form.

**Decision logic** (in priority order):

1. Compute a signal for `poster_classification` (positive if `"missing"`; a specific or
   generic known-negative code if one of the other 8 known values, most notably
   `poster_classification == "kidnapping"` → `FBI_KIDNAPPING_OUT_OF_SCOPE`; otherwise
   `FBI_UNKNOWN_CLASSIFICATION`).
2. Compute a signal for each entry in `subjects` (positive if exactly
   `"ViCAP Missing Persons"`; a specific known-negative code for
   `"Kidnappings and Missing Persons"`, `"ViCAP Unidentified Persons"`, `"ECAP"`,
   `"Endangered Child Alert Program"`, `"Human Trafficking"`; a generic known-negative
   code for the other 22 labels observed in discovery; `FBI_UNKNOWN_CLASSIFICATION` for
   anything else).
3. If **any** signal is positive → `IN_SCOPE` / `MISSING_PERSON`, with all applicable
   reason codes retained (positive and informational known-negative alike).
4. Else if **any** signal is unrecognized → `UNCLASSIFIED` / `UNKNOWN`. This takes
   priority over known-negative signals — an unrecognized value must not be
   auto-resolved to "clearly not a missing person."
5. Else if there is at least one known-negative signal → `OUT_OF_SCOPE` / `OTHER`.
6. Else (no `poster_classification`, no usable `subjects` entries at all) →
   `UNCLASSIFIED` / `UNKNOWN`, reason code `FBI_NO_CLASSIFICATION_SIGNAL`.

**Reason codes** (machine-readable, always at least one, all applicable ones retained):
`FBI_POSTER_CLASSIFICATION_MISSING`, `FBI_SUBJECT_VICAP_MISSING_PERSONS` (positive);
`FBI_KIDNAPPING_OUT_OF_SCOPE`, `FBI_VICAP_UNIDENTIFIED_OUT_OF_SCOPE`,
`FBI_SUBJECT_KIDNAPPINGS_AND_MISSING_PERSONS_INSUFFICIENT`,
`FBI_SUBJECT_ECAP_OUT_OF_SCOPE`,
`FBI_SUBJECT_ENDANGERED_CHILD_ALERT_PROGRAM_OUT_OF_SCOPE`,
`FBI_SUBJECT_HUMAN_TRAFFICKING_OUT_OF_SCOPE`,
`FBI_POSTER_CLASSIFICATION_KNOWN_NON_MISSING`, `FBI_SUBJECT_KNOWN_NON_MISSING_PERSON`
(known-negative); `FBI_UNKNOWN_CLASSIFICATION` (unrecognized value present);
`FBI_NO_CLASSIFICATION_SIGNAL` (no usable value present at all).

**Guarantees:** pure function (no I/O, no randomness, no mutable global state); same
input always produces the same output (tested directly); performs no database writes;
does not create, modify, or read `Person`/`Case` rows; does not modify `SourceRecord` /
`SourceSnapshot` rows (the report CLI only issues `SELECT`s).

### Verification run (400-record sample)

Output of `python -m ingestion.sources.fbi.classifier_report_cli` against the currently
stored sample:

```
Total active FBI records classified: 400

Outcome counts:
  IN_SCOPE: 103
  OUT_OF_SCOPE: 297
  UNCLASSIFIED: 0

Record type counts:
  MISSING_PERSON: 103
  OTHER: 297
  UNKNOWN: 0

Reason-code counts:
  FBI_POSTER_CLASSIFICATION_KNOWN_NON_MISSING: 361
  FBI_SUBJECT_KNOWN_NON_MISSING_PERSON: 279
  FBI_SUBJECT_VICAP_MISSING_PERSONS: 74
  FBI_POSTER_CLASSIFICATION_MISSING: 37
  FBI_SUBJECT_KIDNAPPINGS_AND_MISSING_PERSONS_INSUFFICIENT: 31
  FBI_VICAP_UNIDENTIFIED_OUT_OF_SCOPE: 15
  FBI_SUBJECT_ECAP_OUT_OF_SCOPE: 7
  FBI_KIDNAPPING_OUT_OF_SCOPE: 2
  FBI_SUBJECT_ENDANGERED_CHILD_ALERT_PROGRAM_OUT_OF_SCOPE: 2
  FBI_SUBJECT_HUMAN_TRAFFICKING_OUT_OF_SCOPE: 1
```

A follow-up read-only check (aggregate counts only, same code path, no new record
data) looked specifically for combinations worth human attention:

- **0 records** were `IN_SCOPE` while also carrying one of the explicitly-excluded
  codes (`FBI_VICAP_UNIDENTIFIED_OUT_OF_SCOPE`, `FBI_SUBJECT_ECAP_OUT_OF_SCOPE`,
  `FBI_SUBJECT_ENDANGERED_CHILD_ALERT_PROGRAM_OUT_OF_SCOPE`,
  `FBI_KIDNAPPING_OUT_OF_SCOPE`, `FBI_SUBJECT_HUMAN_TRAFFICKING_OUT_OF_SCOPE`) — the
  exclusions and the positive signals never collided in this sample.
- **8 records** carried both positive signals at once (`poster_classification ==
  "missing"` AND `subjects` containing `"ViCAP Missing Persons"`) — this is exactly
  the overlap set discovered in Round 2, now confirmed to land where expected:
  `IN_SCOPE`, with both reason codes retained.
- **9 records** produced 3+ reason codes, all explainable by rule 5's multi-value
  `subjects` finding from Round 2 (a `"Kidnappings and Missing Persons"` record that
  also carries a geographic tag like `"Indian Country"`/`"Navajo"`, or an `"ECAP"`
  record that also carries `"Endangered Child Alert Program"` or another generic
  label) — none were unexplained by prior discovery findings.
- No genuinely *surprising* combination (i.e. one not already anticipated by the
  discovery rounds) was found in this run.

### KNOWN LIMITATIONS

- **Recall is bounded by exactly two explicit FBI-supplied signals, but that still
  reaches beyond the `"missing"` label alone.** Because rule 1 is an OR across both
  `poster_classification == "missing"` (37 records in the 400-record sample) and
  `subjects` containing `"ViCAP Missing Persons"` (74 records, regardless of their own
  `poster_classification`), the classifier's `IN_SCOPE` set is their union, not just
  the `"missing"`-labeled subset. Verified against the stored sample: **103 of 400
  records are `IN_SCOPE`** (37 + 74 − 8 counted-once overlap; see Round 2 finding #1 and
  #3 above for that overlap). What is deliberately *not* captured, regardless of how
  plausible it looks by label semantics: kidnapping-in-progress, unidentified-persons,
  ECAP, and human-trafficking records — excluded by the explicit product-scope
  decisions above, not by a data or detection limitation.
- **Closed vocabulary, open world -- and today's 0 `UNCLASSIFIED` count is circular,
  not reassuring.** The known-value lists in `classifier.py` were built directly from
  the same 400-record sample the classifier report was run against, so it is
  tautological that today's run produced `UNCLASSIFIED: 0` — every value in the sample
  was, by construction, already known. This is not evidence the classifier handles
  novel taxonomy well; it only means no *new* records have been ingested since the
  vocabulary was written. The real test is what happens on the next ingestion batch
  from the ~68% of the dataset not yet sampled: the FBI can add new
  `poster_classification` or `subjects` values at any time without notice, and any of
  them will correctly surface as `UNCLASSIFIED` rather than being silently mis-sorted —
  a non-zero and growing `UNCLASSIFIED` count over time is the expected, healthy
  signal that the vocabulary needs periodic re-review, not evidence of malfunction.
- **No cross-check against ambiguous/adjacent categories.** The classifier cannot tell
  whether a `default`-classified `"ViCAP Missing Persons"` record is a currently-open
  case or something else (see docs Round 2 unresolved question #1) — Phase 1 resolves
  that ambiguity by product-scope decision (subject label alone is sufficient), not by
  additional evidence. If that decision turns out to be wrong for some subset of these
  records, this classifier will produce false positives with no way to distinguish them
  using classification metadata alone.
- **Not validated against ground truth.** No precision/recall measurement exists yet;
  this classifier has not been checked against any independently known-correct set of
  missing-person vs. non-missing-person FBI records.
- **Scope decisions may need revisiting.** The exclusions of kidnapping-in-progress,
  ECAP, and human-trafficking cases are explicit product decisions (see PRODUCT SCOPE
  DECISIONS above), not conclusions drawn from the data — a future product decision
  could reasonably choose to include any of them, at which point this classifier's
  rules (not the underlying FBI data) would need to change.
- **This document, not FBI documentation, is the source of truth for what these rules
  mean.** Nothing above should be read as a claim about how the FBI itself defines or
  uses `poster_classification` / `subjects` — those interpretations belong to the FBI,
  are undocumented, and could differ from what's assumed here.

---

## Round 2 — 400-record sample

### Sample analyzed

**400 active FBI records** (latest snapshot per record), fetched via 20 pages
(`--max-pages 20`, default page size 20, the existing ingestion CLI — no new ingestion
code was written) of `GET https://api.fbi.gov/wanted/v1/list`. The prior round observed
an API-reported `total` of ~1,233 records, so this is roughly **32% of the full
dataset**. Ingestion was fully idempotent: the 100 records from round 1 came back
`unchanged` (0 new snapshots for them), and 300 new records were added with 0 failures.

### A. Observed facts

**`subjects` shape (n=400).** Still always a list when present: 0 nulls, 0 missing
keys, 0 empty lists, 0 non-list values across all 400. 352 records had a single subject
label, 48 had more than one (max observed: still 3). **28 distinct subject labels**
observed (up from 18 at n=100) — the label vocabulary is still growing as sample size
grows, with no sign of leveling off.

**`subjects` value distribution (n=400; a record can count toward more than one label):**

| Subject label | Records | Seen at n=100? |
|---|---|---|
| ViCAP Missing Persons | 74 | yes (4) |
| Seeking Information | 69 | yes |
| Cyber's Most Wanted | 37 | **no** |
| Criminal Enterprise Investigations | 33 | yes |
| Kidnappings and Missing Persons | 31 | yes (15) |
| Additional Violent Crimes | 27 | yes |
| Indian Country | 25 | yes |
| ViCAP Homicides and Sexual Assaults | 21 | yes |
| Counterintelligence | 20 | **no** |
| China Threat | 17 | **no** |
| ViCAP Unidentified Persons | 15 | yes (1) |
| Most Wanted Fraudster | 13 | yes |
| Violent Crime - Murders | 13 | yes |
| Domestic Terrorism | 10 | **no** |
| Law Enforcement Assistance | 7 | yes |
| White-Collar Crime | 7 | yes |
| ECAP | 7 | yes (1) |
| Seeking Information - Terrorism | 6 | **no** |
| Navajo | 5 | yes |
| Ten Most Wanted Fugitives | 4 | yes |
| Pine Ridge | 3 | yes |
| Crimes Against Children | 3 | yes |
| Iran | 3 | **no** |
| Endangered Child Alert Program | 2 | **no** (distinct from "ECAP" — see Unresolved) |
| Case of the Week | 1 | yes |
| John Doe | 1 | **no** |
| Human Trafficking | 1 | **no** |
| Most Wanted Terrorists | 1 | **no** |

**`poster_classification` distribution (n=400):** `default` 246, `information` 82,
`missing` 37, `fraudster` 13, `ecap` 8, `law-enforcement-assistance` 7, `ten` 4,
`kidnapping` 2, `terrorist` 1.

**`person_classification` distribution (n=400):** `Main` 337, `Victim` 63.

**`status` distribution (n=400):** `na` 377, `captured` 20, `deceased` 1, `resolved` 1,
`surrendered` 1.

**Group definitions used below** (A–E as specified for this round):

| Group | Definition | Count (n=400) |
|---|---|---|
| A | `subjects` contains `"Kidnappings and Missing Persons"` | 31 |
| B | `poster_classification == "missing"` | 37 |
| C | `poster_classification == "kidnapping"` | 2 |
| D | `subjects` contains `"ViCAP Missing Persons"` | 74 |
| E | `subjects` contains `"ViCAP Unidentified Persons"` | 15 |

Within group A specifically: `poster_classification` is `missing` (29) or `kidnapping`
(2) — no exceptions, all 31 accounted for. `person_classification` is `Main` (27) /
`Victim` (4). `status` is `na` for all 31.

### B. Overlap findings (the core result of this round)

Computed directly against stored payloads (read-only `jsonb` containment queries; no
values beyond classification-field labels were read):

1. **Are all `poster_classification == "missing"` records still contained in group A?
   NO — this changed from round 1.** At n=100, all 14 "missing"-classified records were
   inside group A. At n=400, **8 of the 37 "missing" records (22%) fall outside group
   A**. All 8 of those instead have `subjects == ["ViCAP Missing Persons"]` (group D)
   exclusively — none carry `"Kidnappings and Missing Persons"`. This directly falsifies
   the round-1 observation that `poster_classification == "missing"` was a safe,
   conservative subset of group A; it no longer is.
2. **Are there group-A records whose `poster_classification` is neither `missing` nor
   `kidnapping`? No — still holds.** All 31 group-A records have `poster_classification`
   in `{missing, kidnapping}`, at both sample sizes. This is the one pattern that got
   *more* confirmed, not less, by the larger sample.
3. **Are ViCAP Missing Persons (D) still completely separate from `subjects` group A?
   Mostly, but not from `poster_classification == "missing"`.** `D ∩ A = 0` (no record
   carries both subject labels, in either round). But `D` and `poster_classification ==
   "missing"` now overlap: 8 of D's 74 records (11%) are `poster_classification ==
   "missing"`; the other 66 (89%) are `poster_classification == "default"`.
4. **Are ViCAP Unidentified Persons (E) still completely separate? Yes.** `E ∩ A = 0`,
   `E ∩ D = 0`, `E ∩ {B, C} = 0` — group E shares no records with any other group
   examined, at either sample size. Its `poster_classification` values are `default`
   (12) and `information` (3) — never `missing` or `kidnapping`.
5. **Are any records members of multiple *relevant* subject categories?** Only within
   group A, and only with clearly geographic/jurisdictional tags, not competing
   classification categories: 24 of the 31 group-A records have `subjects ==
   ["Kidnappings and Missing Persons"]` alone; the other 7 additionally carry
   `"Indian Country"` and/or `"Navajo"` (tribal-jurisdiction tags). No group-A record
   also carries `"ViCAP Missing Persons"` or `"ViCAP Unidentified Persons"`, and no
   cross-membership was found between D and E, or between either ViCAP group and the new
   `ecap`/ECAP cluster described next.

### C. New classification-adjacent cluster found only at this sample size

A `poster_classification == "ecap"` cluster (8 records) appeared, entirely disjoint from
A, D, and E (0 overlap with all three, confirmed by direct query). Structurally:

- Subject labels used across these 8 records are **inconsistent**: `["ECAP"]` (5
  records), `["Endangered Child Alert Program"]` (1), `["ECAP", "Endangered Child Alert
  Program"]` (1), `["ECAP", "John Doe"]` (1) — i.e. "ECAP" and "Endangered Child Alert
  Program" are used both separately and together for the same `poster_classification`,
  suggesting these may be an abbreviation/full-name pair the FBI has not consistently
  normalized in its own tagging.
- `status` for this cluster: `na` (6), `captured` (1), `resolved` (1).
- ECAP is the FBI's Endangered Child Alert Program (missing/abducted children) — by
  label semantics this is plausibly missing-persons-relevant, structurally distinct from
  groups A/D/E, and was essentially invisible at n=100 (only 1 record, label "ECAP",
  present but not obviously a distinct cluster).

Two single-record subject labels appeared that are structurally ambiguous and **not**
resolvable from classification metadata alone:

- `"Human Trafficking"` (1 record): `poster_classification == "default"`,
  `status == "na"`. No structural signal ties this to groups A/B/C/D/E.
- `"John Doe"` (1 record): co-occurs with `"ECAP"` and has `poster_classification ==
  "ecap"` — i.e. in this single observed instance it is an ECAP (missing-child) case,
  not (as might be assumed) an unidentified-adult/"John Doe" case in the ViCAP-Unidentified
  sense. With n=1 this cannot be generalized either way.

No conclusions above were drawn from `title`, `details`, `description`, `remarks`, or
any other free-text/identity-bearing field — only `subjects`, `poster_classification`,
`person_classification`, and `status`, per the task constraint.

---

## Candidate rules

Two single-signal candidates were evaluated in round 1; a third (combined) candidate is
added here because round 2 shows neither single signal is a subset of the other:

**Rule A — `subjects` contains `"Kidnappings and Missing Persons"`.**
31/400 (7.75%). Internally consistent: 100% of matches have `poster_classification` in
`{missing, kidnapping}` at both sample sizes. Does not capture the 8 `"ViCAP Missing
Persons"`-only records with `poster_classification == "missing"`, nor any of the 66
`"default"`-classified ViCAP Missing Persons records, nor the ECAP cluster, nor group E.

**Rule B — `poster_classification == "missing"`.**
37/400 (9.25%). **No longer a strict subset of Rule A** (see overlap finding #1) — 8 of
its 37 matches carry only the `"ViCAP Missing Persons"` subject, not `"Kidnappings and
Missing Persons"`. Still misses the 2 `kidnapping`-classified group-A records, the ECAP
cluster, group E, and the 66 `default`-classified ViCAP Missing Persons records.

**Rule C — `subjects` contains `"Kidnappings and Missing Persons"` OR
`poster_classification == "missing"`.**
This is the union of A and B: 39/400 (31 + 8, since the 8 "missing"-outside-A records
are disjoint from A by construction). It is presented here **as evidence, not as a
recommendation** — it is the maximal-recall combination of the two signals studied in
detail so far, and it still excludes the 66 `default`-classified ViCAP Missing Persons
records, the ECAP cluster (8), and group E (15) — all of which carry subject labels that
read as missing/unidentified-persons-relevant by their own text but lack independent
`poster_classification` confirmation.

None of these three rules is being recommended for implementation (see Recommendation).

---

## Unresolved questions

These cannot be settled by more classification-metadata analysis alone — they require
either a product/policy decision, further non-metadata investigation (out of scope
here), or simply more time to see if the FBI's own tagging becomes more consistent:

1. **What do the 66 `default`-classified `"ViCAP Missing Persons"` records represent?**
   The subject label says "missing persons"; `poster_classification == "default"` is not
   evidence *against* that — it may simply mean "no special classification tag was
   set," i.e. a catch-all/unset value rather than a meaningful signal either way.
   Structured metadata cannot disambiguate "default because not individually flagged"
   from "default because not actually a missing-person case."
2. **Does an active-kidnapping poster (`poster_classification == "kidnapping"`,
   2 records total) belong in a missing-persons dataset?** Still a policy question, not
   a data question — unchanged from round 1, now with one more supporting data point (2
   instead of 1).
3. **Does `"ViCAP Unidentified Persons"` (group E, 15 records, fully disjoint from
   everything else) belong in scope?** Unidentified remains/persons are adjacent to but
   conceptually distinct from *missing* persons. Still an open product-scope decision.
4. **Does the ECAP (Endangered Child Alert Program) cluster belong in scope, and if so,
   under which subject label — `"ECAP"`, `"Endangered Child Alert Program"`, or
   both?** The FBI's own tagging is inconsistent between the abbreviation and full name
   for what appears to be the same program, which is itself a data-quality caveat for
   any rule that names specific subject strings.
5. **Are `"Human Trafficking"` and `"John Doe"` relevant categories, or noise?** n=1 for
   each in this sample; no structural signal answers this either way.
6. **Is the subject-label vocabulary close to fully observed, or still growing?** 18
   distinct labels at n=100 became 28 at n=400 — a ~56% increase for a 4x sample-size
   increase, with 10 entirely new labels appearing (`Cyber's Most Wanted`,
   `Counterintelligence`, `China Threat`, `Domestic Terrorism`, `Seeking Information -
   Terrorism`, `Iran`, `Endangered Child Alert Program`, `John Doe`, `Human
   Trafficking`, `Most Wanted Terrorists`). There is no evidence in this data that the
   remaining ~68% of the dataset (400 of ~1,233) won't introduce further new labels,
   including possibly more missing-persons-adjacent ones.

---

## Why not AI/probabilistic classification at this stage

Unchanged from round 1, and reinforced by round 2's findings — if anything, round 2
strengthens the argument, since a bigger sample surfaced *more* structure and *more*
open policy questions rather than resolving them:

1. **Determinism and traceability.** The architecture's core rule (see
   [architecture.md](architecture.md)) is that canonical data must be traceable to raw
   source records. A rule like "`subjects` contains X" is directly inspectable against
   the raw payload; an LLM/ML classifier's decision is not traceable in the same way and
   would need its own audit trail this project doesn't have.
2. **The open questions are policy questions, not classification-difficulty
   questions.** Whether kidnapping-in-progress, unidentified-persons, ECAP, or
   trafficking records are in scope is a decision about what this platform is *for* — an
   AI classifier still needs that decision made first (as training signal or prompt
   rules); it does not make the decision for us, it just obscures that one was made.
3. **Sample size still is not large enough to evaluate any classifier's precision/recall**
   — and round 2 demonstrates *why* that bar keeps moving: new categories kept
   appearing as the sample grew, so there is no stable label distribution yet to
   evaluate against.
4. **A field-based deterministic rule stays reversible and cheap to change** against
   immutable raw snapshots; nothing here changes that calculus.

---

## Recommendation

**No — the 400-record sample does not give enough evidence to implement a Phase 1 FBI
missing-person classifier, and the sample expansion made this less clear-cut, not more.**
The central round-1 assumption (`poster_classification == "missing"` ⊆ subject group A)
was falsified by round 2. A larger sample did not converge on a stable, unambiguous
rule — it surfaced a new disjoint cluster (ECAP), confirmed a second disjoint cluster
(ViCAP Unidentified Persons) stays fully separate, and left the largest single relevant
group (66 `default`-classified `"ViCAP Missing Persons"` records) with no independent
structural confirmation either way.

Precisely what remains uncertain, restated:

- Whether `poster_classification == "default"` on a `"ViCAP Missing Persons"`-tagged
  record means "still an open missing-person case" or something else — not answerable
  from classification metadata alone.
- Four separate, mutually exclusive scope decisions (kidnapping-in-progress,
  unidentified persons, ECAP, human trafficking) that are product/policy calls, not
  data-analysis outputs.
- Whether the subject-label vocabulary itself is close to fully observed — the evidence
  so far (28 labels at 32% sample coverage, still growing) suggests it may not be.

If a decision is still wanted now despite the above, **Rule C** (`subjects` contains
`"Kidnappings and Missing Persons"` OR `poster_classification == "missing"`) is the
best-supported candidate as an upper-bound/high-recall starting point — but it is
presented here strictly as evidence, per the task's explicit instruction not to
implement anything. Before implementation, the next steps this document recommends are:

1. Get explicit product decisions on the four scope questions above.
2. Investigate the `"ViCAP Missing Persons"` / `default` ambiguity — likely requires
   either more sample or a different structured field this analysis has not yet
   examined (still classification metadata, not free text) to resolve, e.g. checking
   whether `status` or another field distinguishes them in the still-unseen ~68% of the
   dataset.
3. Only then encode the agreed rule(s) as an explicit, tested, deterministic filter (not
   an AI/ML classifier) in the normalization stage — out of scope for this task.

---

## Round 1 — 100-record sample (superseded findings retained for reference)

*The following was the round-1 analysis. It is retained verbatim below for traceability
of how the picture changed; treat conclusions here as superseded by Round 2 where the
two disagree (notably: "every `poster_classification == 'missing'` record fell inside
the `Kidnappings and Missing Persons` subject group" — no longer true at n=400).*

### Sample analyzed

100 active FBI records (latest snapshot per record), fetched via 5 pages
(`--max-pages 5`) against a reported API `total` of ~1,233 records (~8% coverage).

### `subjects` value distribution (n=100)

Seeking Information 27, Indian Country 17, **Kidnappings and Missing Persons 15**,
Criminal Enterprise Investigations 15, Most Wanted Fraudster 13, Law Enforcement
Assistance 7, Violent Crime - Murders 5, Additional Violent Crimes 5, **ViCAP Missing
Persons 4**, ViCAP Homicides and Sexual Assaults 3, Pine Ridge 3, Navajo 2, Ten Most
Wanted Fugitives 2, Case of the Week 1, White-Collar Crime 1, Crimes Against Children 1,
ECAP 1, **ViCAP Unidentified Persons 1**.

### `poster_classification` / `person_classification` / `status` (n=100)

`poster_classification`: default 35, information 27, missing 14, fraudster 13,
law-enforcement-assistance 7, ten 2, kidnapping 1, ecap 1.
`person_classification`: Main 94, Victim 6.
`status`: na 82, captured 15, deceased 1, resolved 1, surrendered 1.

### Round-1 candidate rules (see Round 2 for what changed)

- Rule A: `subjects` contains `"Kidnappings and Missing Persons"` → 15/100.
- Rule B: `poster_classification == "missing"` → 14/100, and at n=100 this *was* a
  strict subset of Rule A (superseded — see Round 2 overlap finding #1).

### Round-1 recommendation

Not enough evidence yet; flagged the `"ViCAP Missing Persons"` / `"ViCAP Unidentified
Persons"` disjoint-cluster finding as the primary open question, and recommended
expanding the sample — which round 2 above did.
