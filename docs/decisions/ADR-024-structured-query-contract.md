# ADR-024: The structured query contract (PoC Stage 8)

**Status:** **Accepted**, 2026-10-30. The owner ratified this ADR as written ("ratify ADR-024"), relayed by the coordinator session. Register: owner decision D-S9-1.

**Date:** 2026-10-30

**Related:**
- ADR-011 (scene revisions, the `SceneAnalysis` unit, coverage, the processing-visibility barrier, decision 8).
- ADR-013 §16 and ADR-021 (attribute and similarity read paths), ADR-018/019 (plate search).
- ADR-020 (`poc-single-host`, Development evidence class).
- ADR-025 (analytic events, the `mavi-events-v1` catalogue, the events read surface).
- ADR-023 (Entity semantics, S7), accepted 2026-10-30. The Entity unit of this contract reads its confirmed membership (§3; note below).
- Plan `docs/superpowers/plans/2026-10-28-mavi-poc-end-to-end.md`, slice S9; D7 (Ask MAVI emits only Stage-8 structured queries). Register `docs/reviews/2026-10-28-poc-acceptance.md`, rows C8.1 and C8.2.

## Context

MAVI already answers questions through several read surfaces. Each has its own query keys, its own coverage block and the same visibility rule:

- **Track search** (`GET /api/tracks`): committed filters, analytic predicates (zone, line, motion), plate text (Stage 4) and visual attributes (S5). Results come back as pages with a signed v4 cursor.
- **Stage 3 aggregates** (`/api/cameras/{id}/analytics`): counts per zone, line and bucket for one camera and window.
- **S8 events timeline** (`/api/cameras/{id}/events`): events per rule, with derivation coverage.
- **S4 similarity** (`/api/tracks/{id}/similar`): ranked candidates.

Stage 8 asks for counts, group-bys, time buckets, extremes, rankings and comparisons across these surfaces, through an Advanced Search builder. Stage 9 (S10, Ask MAVI) will have a language model write the same queries (plan D7). That second consumer sets the requirements:

- The model's output must be checkable before anything runs.
- Anything outside the language must be refused in a way the caller can act on.
- The same query must always give the same answer from the same data.
- An answer must never present a gap in the data as an observation.

## Decision

### 1. One closed, versioned contract

A structured query is a JSON document at contract version `mavi-query-v1`:

```json
{
  "contractVersion": "mavi-query-v1",
  "unit": "track",
  "where": {
    "timeWindow": { "fromUtc": "2026-10-30T08:00:00Z", "toUtc": "2026-10-30T14:00:00Z" },
    "cameraIds": ["…"],
    "objectClass": "Person",
    "line": { "lineId": "…", "direction": "aToB" }
  },
  "operation": { "op": "timeBucket", "bucketSeconds": 3600 }
}
```

- **Closed.** Every object refuses unknown members, and every enumeration is a fixed list. The JSON Schema is `contracts/schemas/structured-query-v1.schema.json` (`additionalProperties: false` throughout). At runtime the API uses a strict hand-written .NET parser. The repository's JSON Schema tooling already exists in Python (`tools/verify_repo.py`), so no new library is needed.
- **One corpus checks both.** A frozen golden corpus (`contracts/test-vectors/structured-query-v1-golden.json`) is run against the schema by `verify_repo.py` and against the parser by the .NET tests, so the two cannot drift. A query the schema accepts and the parser refuses, or the reverse, fails CI. The exceptions are the cross-field and reference rules the schema cannot express. The corpus marks each of these explicitly.
- **Changes need a new version.** Any change to semantics, a predicate, an operation or a dimension creates a new contract version. The API refuses an unknown version.

### 2. Predicates are a whitelist per unit

All predicates in a query combine with AND. `timeWindow` is required: explicit UTC instants (`Z` or `+00:00`) and half-open `[from, to)`. Relative phrases ("today") are resolved by the caller (the builder, or S10) and never by the contract.

| Predicate | Track | Event | Entity | Reused implementation |
|---|---|---|---|---|
| `timeWindow` (required) | ✔ overlap, as in Track search | ✔ the events timeline's half-open rule | ✔ | `AnalyticsScopeQuery`, S8 read |
| `cameraIds` (1–64; absent = every camera) | ✔ | ✔ | ✔ | base chain |
| `objectClass`, `objectSubclass` (exposed subclasses only) | ✔ | `objectClass` only | — | base chain, `VehicleSubclassExposurePolicy` |
| `minDurationMs`, `minConfidence` | ✔ | — | — | base chain |
| `zone` {`zoneId`, `relation`, `minDwellMs`, `loitering`} | ✔ one camera | `zoneId` | — | Stage 3 analytic predicates |
| `line` {`lineId`, `direction`} | ✔ one camera | `lineId`, `direction` | — | Stage 3 analytic predicates |
| `motion` {`direction`, `minStationaryMs`} | ✔ one camera | — | — | Stage 3 analytic predicates |
| `attributes` (1–4 {type, value} from the frozen vocabulary) | ✔ | — | — | S5 attribute predicate |
| `plateText` {`text`, `match`} | ✔ | — | — | Stage 4 plate predicate |
| `similarTo` {`trackId`, `k`} | ✔ `find` only, alone | — | — | S4 `TrackSimilarityService` |
| `ruleIds`, `catalogueVersion` (only `mavi-events-v1`; every event row carries its rule version) | — | ✔ | — | S8 events read |

- **Geometry is per camera.** Zones and lines belong to one camera's scene revision, so a geometric Track predicate needs exactly one camera. The camera's active revision is resolved inside the snapshot, as Track search does.
- **Similarity is a ranking, not a set.** `similarTo` therefore allows only `find` and no other derived predicate. This mirrors the existing `appearance_query_combination_unsupported` rule.
- **Appearance text is excluded.** The appearance text query (`appearanceQuery`) is not in v1. It waits on an asynchronous worker vector, so it is not a deterministic read.

### 3. Three explicit units; Entity is defined but has no data

- **Track:** a persisted Track of the latest completed run per video, visible in the snapshot.
- **Event:** an `analytic_events` row of the current catalogue, derived from a fact-bearing unit visible in the snapshot.
- **Entity:** defined now, with the predicates `timeWindow` and `cameraIds` and the dimension `camera`.
  - Until ADR-023 is accepted and S7 writes confirmed associations, every valid Entity query returns the `empty` result with the reason `entity_data_unavailable` and the text "No Entity exists until ReID candidates are confirmed (S7, ADR-023)".
  - It returns no rows, no zero count and no error. When S7 lands, the Entity unit will read confirmed associations only (`Track.EntityId` written by an attributable confirmation), never candidates.

### 4. A closed set of operations

| Operation | Parameters | Result |
|---|---|---|
| `find` | `limit` 1–200 (default 50), `order` `newest`/`oldest` | rows, with drill-through ids |
| `count` | — | one value |
| `countDistinct` | `field` (Track: `camera`, `objectClass`, `video`; Event: `camera`, `track`, `rule`; Entity: `camera`) | one value |
| `groupBy` | `by` (Track: `camera`, `objectClass`, `objectSubclass`; Event: `camera`, `rule`, `objectClass`, `direction`, `zone`, `line`; Entity: `camera`) | groups, ordered by key |
| `timeBucket` | `bucketSeconds` (Stage 3 bounds, at most `MaximumBuckets` buckets) | buckets aligned to `fromUtc` |
| `first` / `last` | — | the earliest or latest row by anchor instant |
| `top` | `by` (as for `groupBy`), `k` 1–50 | groups by count descending, then by key ascending |
| `compare` | `baseline` window | count in the query window and in the baseline window, and their difference |

- **Anchor instant.** For a Track it is its first instant inside the window, `max(start, from)`; for an Event, `max(startUtc, from)`. Time buckets therefore partition the count: the buckets sum to `count`.
- **Ties.** Every ordering has a total tie-break (anchor, then id; count, then key).

### 5. Execution reuses the existing read paths, in one snapshot

There is no second search engine. Each query runs as one read transaction:

1. It takes the shared processing-visibility barrier before reading any scope (ADR-011 decision 8).
2. It allocates one snapshot sequence.
3. It resolves scope, revision, identities and coverage through the same code the existing surfaces use: `AnalyticsScopeQuery`, the Stage 3 predicates, the S5 attribute predicate, the Stage 4 plate predicate and the S8 events read.

The repository returns matching records as narrow projections, and a pure, unit-tested evaluator computes the operation. This is the pattern the Stage 3 aggregates already use: counting rules stay where a fixture can reach them.

- **Bounded scope.** A query whose matching scope exceeds **50 000 records** is refused with `query_scope_too_large`. An aggregate is never computed over a silently truncated set.
- **`find` and paging.** `find` returns at most `limit` rows, and the truncation is disclosed with the full matching total. v1 has no continuation cursor. Paging is handed over by drill-through to Track search (v4 cursor) or the events timeline.
- **`compare`.** Both windows are evaluated in the same transaction and snapshot.
- **Similarity.** A `similarTo` query is answered by the S4 service in its own signed snapshot, which its result reports.

### 6. The result envelope

Every answer carries:

- `contractVersion`;
- `resolvedQuery`: the canonical form, with defaults made explicit, sets sorted (a repeated id is refused, not merged) and instants at millisecond precision;
- `queryFingerprint`: the SHA-256 of the canonical JSON;
- `snapshot`: the visibility sequence and the evaluation instant;
- `identity`: per camera, the scene revision and analytics algorithm version; the attribute, plate or embedding identity fingerprint where used; and the events catalogue version;
- `coverage`: the components and a `complete` flag;
- `result`;
- `truncation`;
- the Development disclosure.

**Coverage reuses the existing blocks unchanged:**

- scene-analytics coverage (ADR-011) for geometric predicates and for Events;
- event-derivation coverage (`eventsPendingRuns`) for Events;
- attribute coverage (S5) for attribute predicates. The per-predicate Unknown counts are disclosed as abstentions: a Track whose attribute is Unknown is not counted as a match and not counted as a non-match;
- plate coverage (Stage 4) for plate predicates.

**Incomplete coverage is never shown as zero.**

- An operation that asserts something about the whole scope (`count`, `countDistinct`, `groupBy`, `timeBucket`, `top`, `compare`, `first`, `last`) returns `{"kind": "withheld", "reason": "coverage_incomplete"}` with the coverage block when coverage is incomplete. This is how the Stage 3 Analytics page withholds figures.
- `find` returns the rows it found, each of them real, with the coverage that says the list is partial. This is how Track search behaves.
- `requireCompleteCoverage: true` turns an incomplete answer into a typed refusal (409, `coverage_incomplete`).

### 7. Refusals are typed

A query outside the contract never executes. The API answers `400` with `{"code": "query_refused", "refusal": {"code", "path", "message"}}`:

- `code` comes from a closed list in the contract, for example `unknown_member`, `unsupported_version`, `unsupported_unit`, `predicate_not_allowed_for_unit`, `operation_not_allowed`, `dimension_not_allowed`, `invalid_value`, `missing_required`, `geometry_requires_single_camera`, `similarity_combination_unsupported` and `unknown_reference`;
- `path` is a JSON pointer to the offending member.

S10 relies on this to tell its user "I can't ask that" instead of guessing. A reference to geometry outside the resolved revision, or to an unknown camera or Track, is refused as `unknown_reference`. As on the analytic search, the refusal does not confirm whether a hidden run exists.

### 8. Surfaces

- `POST /api/query` evaluates a query.
- `GET /api/query/contract` returns the machine-readable vocabulary: units, predicates per unit, operations, dimensions, bounds, attribute vocabulary and rule ids. The Advanced Search builder composes only from it, and S10 can prompt from it.
- Both routes are read-only.
- The builder shows the resolved query and renders the envelope as a table, a count, grouped bars or time buckets, with drill-through to Tracks and Events. It shows the coverage and withheld states in the words the Analytics and Events pages use.

## Trade-off accepted

A closed contract trades **expressiveness** for **determinism, refusability and grounding**:

- There is no free-form filter language, no OR, no nesting, no joins across units, no arbitrary fields and no user-defined metrics.
- An operator or a language model can ask only what the table above allows. A question outside it is refused, not approximated.
- In exchange, every accepted query is checkable before it runs, gives the same answer from the same snapshot, carries its identity and coverage, and cannot be steered by S10 into reading something the operator could not read through the existing surfaces.

The 50 000-record bound and the absence of a continuation cursor keep evaluation simple and exact at PoC scale. Both are disclosed limits, not Production design.

## Consequences

- No new dependency, no schema migration and no new table. The contract is a read layer over existing data.
- Adding a predicate or operation is a new contract version, plus schema, parser, evaluator, golden-corpus cases and builder support in one change.
- The Entity unit becomes real only through ADR-023 and S7, under a new contract version if its semantics change.
- Latency is measured on the demo corpus at its real scale and recorded in the register (C8.2). It is a Development observation, not a performance qualification.

**Deferred.** OR and nested predicates; cross-unit joins (for example "Tracks with an event"); a continuation cursor for `find`; the appearance text predicate; multi-series time buckets; relative time inside the contract.

**Note 2026-10-30 (PoC S7; outside the ratified text, no contract version change).** The Entity unit is bound as §3 reserved it (ADR-023 §9): it reads operator-confirmed membership only, never candidates. An Entity is in scope when a member Track is visible in the snapshot, overlaps the window and is on an included camera; `groupBy`, `top` and `countDistinct` by camera count it once per camera. An installation with no confirmed Entity with a visible member still answers `empty` with `entity_data_unavailable`. Row results gain an optional `entities` list (`entityId`, `displayCode`, `entityType`, `firstStartUtc`, `lastEndUtc`, `cameraIds`, `memberTrackIds`), written only for Entity rows, so every envelope frozen before S7 is byte-identical. The request schema is unchanged. The Entity unit is read by operators only (401/403 otherwise; the contract route says `operator_required`), and membership is read as of evaluation in one REPEATABLE READ transaction, not at the visibility snapshot.
