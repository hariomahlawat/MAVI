# ADR-025: Deterministic analytic events and the versioned rule catalogue (PoC Stage 7)

**Status:** **Accepted**, 2026-10-29. The owner ratified this ADR ("Ratify ADR-025"), relayed by the coordinator session, with point 2 conditional on a check. The check passed, so the Restricted-zone overlap form stands (see the owner decision below). Register: owner decision D-S8-1.

**Date:** 2026-10-29

**Related:**
- ADR-011 (scene configuration revisions, the `SceneAnalysis` unit, fencing, coverage, the resolved analytical identity). This ADR builds on it and amends its geometry with one additive field (§6).
- ADR-020 (`poc-single-host`, Development evidence class).
- Plan `docs/superpowers/plans/2026-10-28-mavi-poc-end-to-end.md`, slice S8. Register `docs/reviews/2026-10-28-poc-acceptance.md`, rows C7.1 and C7.2.
- S2 admissibility record `docs/qualification/poc/s2-demo-corpus-admissibility.md` §8 (thresholds, owner decision 10).
- ADR-023 (Entity semantics, S7), which has not been written yet. The entity-conditioned rule waits for it.

## Context

Stage 3 already turns persisted Tracks and a scene revision into facts: zone visits, zone summaries with the person-loitering verdict, line crossings and motion summaries with stationary intervals. These facts belong to one `SceneAnalysis` unit, keyed by run, revision and algorithm version (ADR-011 decision 3). Search and the aggregates read them under one resolved identity.

Stage 7 asks for **events**: discrete, explainable occurrences on a timeline ("vehicle stopped in the parking bay for 41 s", "person and vehicle together in the junction box"). Each event carries the evidence that produced it and the rule that fired. Before writing code, three things must be settled: where events come from, how they are keyed and recomputed, and what an event must carry.

## Decision

### 1. Events derive from Stage 3 facts, one fact-bearing unit at a time

An event derivation reads one fact-bearing `SceneAnalysis` unit (`Completed` or `Superseded`). It reads that unit's persisted facts, the classes of its analysed Tracks and the unit's own scene revision. From those it computes events with pure .NET rules. There is no model inference, no trajectory re-read, no Python and no new dependency. The derivation never edits a fact. It builds on Stage 3 and does not repeat it. Dwell **is** the Stage 3 loitering verdict, and line crossings **are** the persisted crossings.

The scope of v1 is one unit, so every rule sees one run against one revision. Rules that span runs or cameras are out of scope for v1.

### 2. The rule catalogue is versioned as a whole, in code

The catalogue is a code-defined, immutable list. It has a catalogue version (`mavi-events-v1`) and, for each rule, an id, an integer rule version, an enabled flag and a disabled reason. Each rule declares its parameters, and every parameter names its **source**:

| Source | Meaning |
|---|---|
| `scene-revision` | Read from the unit's own revision, for example a zone's loitering threshold. It is bound to the event through the revision id. |
| `owner-decision` | A value the owner accepted on the record. It is cited by decision id. |
| `catalogue` | A rule-definition constant. It is disclosed and has no tunable number. |

Changing a rule's semantics, or any parameter whose source is not `scene-revision`, creates a new catalogue version. A canonical SHA-256 of the catalogue is recorded with every derivation. Catalogue v1:

| Rule | v | Fires when | Parameters (source) |
|---|---|---|---|
| `line-crossing` | 1 | One event per persisted crossing of an enabled trip line. The read side counts these per line, direction and time bucket. | none |
| `zone-dwell` | 1 | A person's total dwell in an enabled zone reaches that zone's threshold. This is the Stage 3 loitering verdict, which is person-only. The event starts at the instant the threshold was reached and ends at the last exit. The first entry is recorded in the provenance. | threshold (`scene-revision`: zone `loiteringThresholdSeconds`, otherwise the engine default) |
| `stopped-vehicle` | 1 | A Vehicle Track's stationary interval overlaps a visit to an enabled `Restricted` zone for at least the minimum. | minimum 30 s (`owner-decision` S2-10); zone kind `Restricted` (`catalogue`) |
| `wrong-way` | 1 | A crossing goes against the line's permitted direction. Lines with no permitted direction never fire. | permitted direction (`scene-revision`, §6) |
| `co-occurrence` | 1 | Within one enabled zone, at least one Person and at least one Vehicle are inside at the same time, with positive overlap. There is one event per zone episode, and it lists every participant. | classes Person + Vehicle (`catalogue`); overlap > 0 ms, no tunable threshold (`catalogue`) |
| `repeated-visit` | 1 | **Disabled** (`requires_entity_confirmation`). One Entity (a confirmed `Track.EntityId`) enters the same zone through at least two distinct Tracks. It is defined and fixture-tested. It stays off until S7 confirmation exists. Enabling it is a new catalogue version. | minimum distinct Tracks 2 (`catalogue`) |

### 3. Keys, derivation units and recompute

- **The derivation unit is (`scene_analysis_id`, `catalogue_version`).** It is unique in the database. Each derivation records the run, revision, algorithm version, catalogue SHA-256, per-rule state (enabled, disabled with reason, event count) and a digest of all its inputs.
- **The event id is deterministic.** It is a UUID built from SHA-256 over the catalogue version, rule id, rule version, unit id and a rule-specific discriminator made of persisted identities and offsets: the crossing id, the Track and zone, the Track, interval and visit, or the zone and episode start. Re-deriving the same unit at the same catalogue version produces the same ids and the same digests. A drill-through link therefore stays valid, and determinism can be tested.
- **A derivation is one short transaction, not a leased job.** It takes a transaction-scoped advisory lock keyed by the unit, re-checks that no derivation exists, reads the facts, computes, inserts the derivation and its events, and commits. The unique key is the backstop against a concurrent second writer. This is safe because a unit's facts never change after it completes (ADR-011), and a derivation over one unit is bounded and small. The ADR-011 lease machinery is therefore not repeated here.
- **A scene revision change** follows ADR-011. Re-analysis creates a new unit, and the sweep derives that unit's events. The old unit's events stay, bound to the old revision. History is never reinterpreted.
- **A catalogue version change** is additive. The sweep derives the new version for fact-bearing units, and earlier versions' events stay queryable by their version. *Trade-off accepted:* unlike a Stage 3 algorithm change, which marks units `Stale` and waits for an explicit re-analysis, a new catalogue version is derived automatically. It is cheap, it is computed only from persisted facts, and it replaces nothing.
- **Scheduling.** A bounded background sweep in the API host (`AnalyticEvents:Enabled`) derives any fact-bearing unit that has no derivation at the current catalogue version.

### 4. The provenance envelope

Every event row carries two kinds of data.

**Typed columns** are what queries filter on: camera, video asset, run, analysis unit, scene revision, analytics algorithm version, catalogue version, rule id and version, primary Track, zone, line, direction, object class, start and end as media offsets and as UTC instants.

**The `provenance` document** is evidence detail only:
- the participants (Track id, role, class);
- the input facts, by id (zone visits, crossings) or by position (stationary interval);
- the parameters as applied, each with its value, unit, source and reference.

An `input_sha256` covers what the event claims, canonically serialised: rule id and version, unit, revision, algorithm version, instants, geometry, participants, input-fact references (ids and offsets) and applied parameters. The derivation's `inputs_sha256` covers the complete fact set the unit was read with. To re-check an event, re-read its unit's facts, re-derive, and compare both digests. A recompute is compared the same way.

### 5. Read surface

Like the Stage 3 aggregates (ADR-011 decisions 5, 6 and 8), the Events surface is **single-camera and window-bounded**. It is resolved under the processing-visibility barrier through the same scope and coverage implementation (`AnalyticsScopeQuery`). Every response returns:

- the resolved identity: camera, revision, algorithm version, catalogue version and snapshot;
- Stage 3 coverage, plus `eventsPendingRuns` for evaluated runs not yet derived.

Incomplete coverage is never shown as zero events. Counts exist only for rules that ran. A rule that is disabled, filtered out, or has no derived run in scope reports no count, never a zero. A response is bounded, and it says so when it was truncated.

Crossing counts per line, direction and bucket are computed from the crossing events of the same response identity. A test holds them equal to the Stage 3 aggregate for the same scope. The catalogue, including each disabled rule and its reason, is served to the UI. The UI shows the reason rather than hiding the rule.

### 6. Amendment to ADR-011 geometry: a permitted direction on trip lines

A trip line gains an optional `permittedDirection` (`AToB`, `BToA` or none), versioned with its revision like every other geometry property. A permitted direction requires `directed = true`. With none set, `wrong-way` cannot fire on that line. The field is additive and nullable. Existing revisions keep their meaning, and the Stage 3 algorithm and its version do not change. Changing a permitted direction saves a new revision like any other geometry edit. That makes the camera's runs `Stale` until they are re-analysed, even though Stage 3 facts do not depend on the field. This is accepted for a field that is rarely edited, and it avoids a second revision concept. *Trade-off accepted:* the existing `directed` flag could have been reinterpreted as "one-way, A to B". That was rejected, because `directed` currently means "both directions matter and are labelled", and reinterpreting it would change the meaning of revisions already saved.

## Consequences

**Positive.** Events are reproducible from persisted facts alone. Every event names its rule version, scene revision, inputs and parameter sources. Recompute is idempotent and testable. Stage 3 stays the single source of geometry and temporal truth.

**Accepted costs.** Event rows partly duplicate facts (one crossing event per crossing) so that every event has one uniform, drillable shape. Every catalogue version adds rows. Retention is a later housekeeping decision, as for superseded units. A rule spanning runs or cameras needs a new derivation scope and a later ADR.

**Deferred.** Entity-conditioned rules, until S7 and ADR-023. Physical speed and calibration, as in ADR-011. Alerting and notification. Operator-defined rules.

## Owner decision (2026-10-29)

Ratified as written: §1–§6, including these points:

1. Events are derived automatically and additively when the catalogue version changes (§3).
2. The 30 s stopped-vehicle minimum is reused from S2 owner decision 10. It is measured as the overlap of a stationary interval with a visit to a `Restricted` zone, rather than "anywhere".
3. Co-occurrence has no tunable threshold.
4. The trip-line `permittedDirection` amendment to ADR-011 (§6) is accepted.

The owner accepted point 2 on one condition: the rule must fire on the demo clip that justified decision 10. **Check result:** it does.
- **Clip.** s2-05, `POC-S2-05`, from the clean-import corpus run of PoC S8. Its three Vehicle Tracks stationary for at least 30 s are the three positives of the S2 audit.
- **Overlap.** Each Track's stationary interval lies wholly inside the `Restricted` zone "Parking bay": 30.8 s, 33.96 s and 33.44 s.
- **Result.** All three fire `stopped-vehicle`, so the Restricted-zone form is the ratified form.

**Corrections after ratification (2026-10-30).** The owner ratified the text above before these corrections were made. They came from the independent cold review and change no decision. §3 now says the derivation takes an advisory lock rather than locking the unit row, and names the actual discriminators. §4 states exactly what `input_sha256` covers. §5 states that rules which did not run report no count. §2 states that a dwell event starts when the threshold is reached. §6 states the re-analysis cost of editing a permitted direction. The two behaviour statements are pinned by tests: `EventRuleFixtureTests.DwellIsTheStageThreeLoiteringVerdictWithTheInstantTheThresholdWasReached` (the start is 25 s, not the first entry) and `AnalyticEventApiTests.EditingAPermittedDirectionSavesARevisionThatMakesTheRunStale`.
