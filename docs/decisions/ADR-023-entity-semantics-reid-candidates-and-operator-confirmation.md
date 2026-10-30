# ADR-023: Entity semantics, ReID candidates and operator confirmation (PoC Stage 6)

**Status:** **Accepted** owner decision, 2026-10-30. The owner ratified the decision text in §Owner decision as written ("Ratify, 0.85", relayed by the PoC coordinator session, and confirmed by the owner in the S7 session), with option (a) for the catalogue parameters (register C6.1; decisions D-S7-1 and D-S7-2), before any S7 code merged. **Amended 2026-10-30** (owner decision D-S7-3; §Amendment 2026-10-30 below): status unchanged.

**Date:** 2026-10-30

**Related:**
- ADR-010 (operator identity, `OperatorPolicy`, append-only `audit_entries` through `IAuditWriter` in the mutation's transaction; §8 names Entity confirm/dismiss);
- ADR-021 (SigLIP 2 Track vectors in `track_embeddings`; *Similarity candidates*, never identity; §5 "no automatic grouping");
- ADR-022 (face results are candidates with score, reference threshold and model identity; face reads need the operator, face searches are audited; §1 names this ADR as the only path to an Entity);
- ADR-024 (structured query; its Entity unit answers `entity_data_unavailable` until confirmed associations exist, §3);
- ADR-025 (analytic events; `repeated-visit` is disabled with reason `requires_entity_confirmation`);
- ADR-020 (`poc-single-host`, Development evidence class);
- `docs/superpowers/plans/2026-09-20-audited-review-and-cases-plan.md` §1 (dormant `Entity`, nullable `Track.EntityId`), §2.7 (no identity assertion, no automatic grouping) and §2.8 (reprocessing does not transfer judgements);
- plan `docs/superpowers/plans/2026-10-28-mavi-poc-end-to-end.md` (slice S7, demonstration step 8); register `docs/reviews/2026-10-28-poc-acceptance.md` (rows C6.1, C6.2).

## Context

Stage 6 asks: "is this person or vehicle the same one that appeared on another camera, or earlier on this one?" The domain has carried a dormant `Entity` aggregate and a nullable `Track.EntityId` since the first schema; nothing writes them. Three things now exist that make an answer possible, and each is weak on its own:

- **Appearance.** S4's SigLIP 2 Track vectors. ADR-021 is explicit that this is a general image–text model, not a re-identification model. On the frozen `s4-confirm-80-v1` sample (BDD100K, crops ≥ 80 px, read again for this ADR without re-running anything), two crops of the *same* Track score a median cosine of 0.935 and a 5th percentile of **0.850**, while Tracks of *different* vehicles from *different* videos score a median of 0.744, a 90th percentile of **0.855** and a 99th percentile of 0.915. The distributions overlap: appearance alone will pair look-alikes.
- **Time and camera.** Every Track has a camera and UTC start and end. A physical object cannot be in two places at once, and on one camera two Tracks that are visible at the same time are two objects. MAVI has **no camera topology**: no site map, no distances, no declared field-of-view overlap. It cannot know how long travel between two cameras takes.
- **Face.** S6 face templates, usable on 7 of 140 demo Person Tracks (ADR-022 amendment, coverage v2). Where both Tracks have a usable face, face similarity is a strong but separate signal with its own uncalibrated reference threshold.

A wrong automatic link would attach one person's or vehicle's history to another's and propagate into events (S8's repeated visit), structured queries (S9) and cases (S11). So the question this ADR settles is not "how good can automatic ReID be", but what MAVI may assert on its own, and what only an operator may.

## Decision

### 1. Meaning: candidates are machine output, an Entity is an operator decision

- An **Entity candidate** is a pair of Tracks of the same class (Person or Vehicle) that MAVI proposes might show the same object. It carries each factor separately: appearance score, time and camera plausibility, and (for persons, on request) a face factor. It is a *candidate*, never identity.
- An **Entity** is a group of Tracks that an operator has confirmed, one pair at a time, as the same person or vehicle. It is an **operator decision, not an identification**: `Entity.IdentityStatus` stays `Unknown`, no name, gallery entry or external identity is attached, and every surface labels it "Operator-confirmed Entity — not identification — Development". `Entity.ReviewStatus` is `Confirmed`.
- **Nothing merges automatically.** No score, threshold or rule writes `Track.EntityId`, creates an Entity or adds a Track to one. Candidate generation writes only `entity_candidates`.
- **Confirmation is the only writer of `Track.EntityId`.** The domain method that sets it is called from exactly one place, the confirmation service, and a test fails the build if any other code path calls it or writes the column.

### 2. How candidates are generated, and why platform-side

- **Source of truth:** the existing `track_embeddings` of the release's pinned embedding identity (ADR-021), the persisted Tracks with their cameras and UTC times, and the candidate catalogue (§3). No new model, worker, runtime or dependency.
- **Platform-side, not a worker role.** The S4 vectors are already in PostgreSQL; a pair score is one exact cosine between two stored vectors, and the plausibility model needs only Track times and cameras, which the platform owns. A worker role would add a lease protocol, a contract and a failure surface to move data out of the database and back for arithmetic the database already does. The S4 vectors suffice for a *candidate* (not for an identification), which is all this slice claims.
- **The pair rule is pair-local.** A pair is a candidate when, and only when:
  1. both Tracks are Person or both are Vehicle;
  2. both have an `Embedded` vector under the pinned identity, in a completed analysis;
  3. the appearance cosine is at least the floor (§3);
  4. the pair passes the plausibility model (§4).
  Because nothing in the rule depends on other pairs (no top-k, no ranking cut), the candidate set is the same whatever order analyses complete in. A per-Track top-k was rejected for exactly that reason: it would depend on which Tracks existed when a derivation ran.
- **Derivation unit:** one derivation per (completed embedding analysis, catalogue version), recorded in `entity_candidate_derivations` (unique). The hosted sweep, like ADR-025's, derives each completed analysis of the pinned identity that has none: it pairs that analysis's embedded Tracks with every embedded Track visible at a fresh snapshot (the latest completed run per video, the same base candidate set Track search and Find similar use) and inserts the pairs that pass. Derivations are serialised by one transaction-scoped advisory lock, so of two analyses completing together the later derivation always sees the earlier one's vectors: every pair is derived by whichever of its two derivations runs second. An analysis whose run is no longer visible when the sweep reaches it is recorded `not_visible` and pairs nothing.
- **Keys:** `entity_candidates` is unique on (catalogue version, embedding identity fingerprint, lower Track id, higher Track id). Re-deriving inserts nothing that exists; a candidate row is immutable apart from its decision.
- **Recompute:** a new catalogue version or a new embedding identity derives a new candidate set beside the old one. Decisions on the old set stay with it; they are not copied (§6).

### 3. The candidate catalogue `mavi-entity-candidates-v1`

The catalogue is code-defined and versioned as a whole, like ADR-025's. Its canonical SHA-256 is recorded on every derivation. Each parameter names its source; changing any of them is a new catalogue version.

| Parameter | Value | Source |
|---|---|---|
| Classes | Person–Person, Vehicle–Vehicle only | `catalogue` (the classes ADR-021 embeds) |
| Appearance floor | cosine ≥ **0.85** | `owner-decision` (D-S7-2). Proposed from the frozen `s4-confirm-80-v1` record before any demo-corpus pair was scored: 0.850 is the 5th percentile of same-Track crop pairs; about 10 % of different-object vehicle pairs from different videos also reach it (90th percentile 0.855). It is a workload control for the operator's list, not a match threshold |
| Same camera, overlapping in time | excluded (`same_camera_concurrent`) | `catalogue`: two Tracks visible at once on one camera are two objects |
| Different cameras, overlapping in time by more than the tolerance | excluded (`concurrent_elsewhere`) | `catalogue`: one object cannot be in two places at once |
| Concurrency tolerance | **2 s** | `owner-decision` (D-S7-2). Recording starts are set to the second (the MEVA clips 09:40:00–09:40:02), and a tracker starts or ends a Track a few frames from the true boundary; a hand-off across adjacent views can overlap briefly |
| Minimum travel time between cameras | **none** (0 s beyond the tolerance) | `owner-decision` (D-S7-2): MAVI has no camera topology to take it from. A camera-pair transit table is scene configuration for a later slice |
| Maximum gap | **none** | `catalogue`: the gap is shown as a factor, never used as a gate |

### 4. Plausibility model and what it does not know

The model is a deterministic function of the two Tracks' cameras and UTC intervals. It returns `plausible` or an exclusion reason, and for a plausible pair the gap (signed milliseconds from the earlier Track's end to the later Track's start, negative when they overlap within the tolerance) and whether both are on one camera.

It does **not** know: where cameras are or how far apart; whether two views overlap; travel speed or route; whether a camera clock is wrong; whether two clips from unrelated places were given adjacent synthetic times (the seven Commons demo clips were); or anything about the object beyond its class and its appearance vector. It therefore cannot exclude a pair from two unrelated sites, and it will exclude a true pair when two cameras with overlapping views see the same object at once for more than the tolerance. Both are stated on the known-limits page and next to every factor in the UI.

### 5. The face factor: separate, read-time, audited

- For a Person pair, the face factor is the **best cosine between the usable faces of the two Tracks** under the current face release (ADR-022), shown with the reference threshold, whether the score is above it, the model identity and the two supporting faces. Where either side has no usable face it is **Unknown with that side's reason** (`notEnabled`, `notAnalysed`, `pending`, `failed`, `no_face_detected`, `face_too_small`, `no_evidence`, `evidence_unavailable`), never "no match".
- **Never folded in.** The face factor takes no part in generating, gating or ordering candidates, and no combined score exists. The operator sees appearance, plausibility and face side by side and decides.
- **Not stored.** It is computed when asked, from the face rows that exist then. Storing it would keep a biometric-derived value after ADR-022 deletes its templates (run deletion, camera opt-out, supersession).
- **Audited.** Computing it is a 1:1 biometric comparison, so it follows ADR-022 §6: it is a JSON `POST` under `OperatorPolicy` that writes one `entities.candidate-face-compared` audit row (ids only, no score or vector). The candidate list says only whether a face factor is available on both sides.
- A face-only link (different clothes, same face) is not proposed by this catalogue. That recall loss is accepted to keep face out of the generation rule; a face-sourced candidate kind would be a new catalogue version under this ADR.

### 6. Confirm and dismiss: attributable, one transaction, fail-closed

Both follow the plate re-analysis pattern (ADR-010 §8): JSON `POST`, `.RequireAuthorization(OperatorPolicy.Name)`, actor from `ICurrentOperator`, server time from `TimeProvider`, and one `audit_entries` row through `IAuditWriter.RecordAsync` in the same transaction as the state change. A refused decision writes neither.

- **Confirm** (`entities.candidate-confirmed`): locks the candidate, then both Tracks in id order, then any Entity involved, and re-checks under the locks:
  - the candidate is `Open` (otherwise 409 `entity_candidate_already_decided` with the current decision);
  - both Tracks are still visible (latest completed run of their video), otherwise 409 `entity_candidate_not_visible`;
  - neither Track has an Entity → a new Entity of the pair's type is created and both Tracks join it;
  - one Track has an Entity → the other joins it (**extension**), provided it is plausible (§4, same catalogue) against **every** existing member; otherwise 409 `entity_extension_implausible`, naming the conflicting member;
  - both Tracks are already in the same Entity → the decision is recorded, nothing else changes;
  - the Tracks are in two different Entities → 409 `entity_merge_unsupported`. Merging Entities is deferred to S11-full.
- **Dismiss** (`entities.candidate-dismissed`): records the decision on the candidate. A dismissed candidate is suppressed from the default list and is never re-proposed: re-derivation inserts nothing for an existing key. Dismissal writes no Entity and no `EntityId`.
- Each decision records the operator id, display name, identity source, server time, an optional note (≤ 500 characters) and the audit entry id on the candidate row. Decisions are final in this slice. Unlinking a Track from an Entity and reopening a dismissed candidate are deferred to S11-full; until then a mistaken confirmation stays visible and attributable, not silently undone.
- With `Identity:Mode=disabled` every Entity and candidate surface is refused (401), as for faces.

### 7. Reprocessing: new run, new Tracks, nothing carried over

Consistent with the review plan §2.8: candidates and decisions are keyed to Track ids, which belong to one processing run.

- A new run of a video creates new Tracks with no `EntityId`. The old run's Tracks keep their Entity membership and their candidates; both drop out of the default views because the old Tracks are no longer visible, and remain readable through the Entity itself (members marked "earlier run").
- The new Tracks get new candidates when their embedding analysis is derived. No confirmation, dismissal or membership is copied. A later slice may add an explicit, audited "carry over" once overlap rules exist.
- Deleting a run deletes its Tracks; their candidates go with them (cascade), and `Track.EntityId` disappears with the Track. An Entity left with no member Tracks stays as an empty record of the decision; every read surface counts Entities through their member Tracks only.

### 8. Storage and retention

| Table | Content |
|---|---|
| `entity_candidate_derivations` | One row per (embedding analysis, catalogue version): catalogue SHA-256, identity fingerprint, outcome, candidate count, time |
| `entity_candidates` | The pair (lower, higher Track id), class, appearance score, plausibility verdict and gap, same-camera flag, catalogue and identity, derivation id; decision status (`Open`, `Confirmed`, `Dismissed`), operator, identity source, time, note, audit entry id, Entity id on confirmation |
| `entities` (existing) | The confirmed group: type, display code, `IdentityStatus = Unknown`, `ReviewStatus = Confirmed` |
| `tracks.entity_id` (existing) | Set only by confirmation |

A person Entity links appearances of one person across recordings: it is sensitive derived data, like an appearance embedding. It stays in the installation's database, is never exported, and the PoC uninstall removes it with the database. No face value is stored here (§5).

### 9. What later slices need

- **S8 (`repeated-visit`).** The rule stays disabled and catalogue `mavi-events-v1` is unchanged in this slice. Enabling it is `mavi-events-v2`, and it must: read membership only from confirmed `Track.EntityId`; treat Entity membership as an input that changes after the scene analysis completed, so the derivation of an entity-conditioned rule is keyed by the membership it read (the set of confirming audit entry ids of the Entities involved) and included in `inputs_sha256`; and mark that derivation stale and re-derive it when a confirmation adds a member Track inside its unit. Membership only grows in this slice (no unlink), which keeps that invalidation additive.
- **S9 (Entity unit, ADR-024 §3).** The Entity unit reads confirmed membership only, never candidates: an Entity is in scope when at least one of its member Tracks is visible in the snapshot, overlaps the time window and is on an included camera; `groupBy camera` and `countDistinct camera` count an Entity once per camera where it has such a member. That is the semantics ADR-024 §3 already reserved, so binding it needs no new contract version.
- **S11-full.** Unlink, reopen and Entity merge as audited operator mutations; the audit read surface; Entities and candidates in cases.

## Trade-offs accepted

- **Recall and convenience for a guarantee.** Candidates plus one-pair-at-a-time operator confirmation trade recall (true links that score below the floor, face-only links, pairs the plausibility model wrongly excludes) and operator effort (every link is a click, look-alikes must be dismissed) for the guarantee that **MAVI never asserts identity, or even sameness, on its own**. Every Entity link in the database has a named operator and an audit row behind it.
- **A weak appearance signal, stated.** The floor passes roughly one in ten different-object pairs on the S4 record; with no topology, unrelated cameras are not excluded. The operator's list will contain look-alikes. A specialist ReID model (ADR-021 §5) and a camera-topology model are the real fixes; both are later work.
- **No topology.** The plausibility model is time-only. It is honest about that rather than inventing transit times.
- **Final decisions.** No unlink or reopen until S11-full, so a mistake is corrected by a later audited action, not by editing history.
- **Face only on request.** The face factor costs one audited request per Person candidate opened, and is absent from the list ordering by design.

## Owner decision (ratified 2026-10-30)

> **ADR-023 (PoC Stage 6) is accepted:**
> 1. An **Entity** is an operator-confirmed group of Tracks of one class, an operator decision and **never an identification** (`IdentityStatus` stays `Unknown`). **Entity candidates** are machine proposals (pairs of same-class Tracks) with their factors shown separately. **Nothing merges automatically; confirmation is the only writer of `Track.EntityId`.**
> 2. Candidates are generated platform-side from the existing S4 vectors (no new model, worker or dependency) by a pair-local rule: same class, appearance cosine ≥ floor, and a time/camera plausibility model (same camera overlapping in time excluded; different cameras overlapping beyond a tolerance excluded; no transit time, because MAVI has no topology). Keyed per (catalogue version, embedding identity, Track pair); derived once per completed embedding analysis; never re-proposed after dismissal.
> 3. Catalogue `mavi-entity-candidates-v1` parameters (D-S7-2): appearance floor **0.85** (from the frozen S4 record, before any demo pair was scored), concurrency tolerance **2 s**, no minimum travel time, no maximum gap.
> 4. The **face factor** (Person pairs, ADR-022) is separate, computed on request, never stored, never part of generation or ordering, audited as a biometric comparison; Unknown with a reason where either side has no usable face.
> 5. **Confirm and dismiss** require `OperatorPolicy` and write one audit row in the decision's transaction. Confirm creates an Entity or extends one (the new member must be plausible against every existing member); merging two Entities, unlinking and reopening are deferred to S11-full. Dismiss suppresses the candidate.
> 6. **Reprocessing** carries nothing over: new run, new Tracks, new candidates, no copied decision or membership.
> 7. S8's `repeated-visit` stays disabled (enabling it is `mavi-events-v2`, keyed on membership as §9 states); S9's Entity unit reads confirmed membership only.
>
> Accepted trade-off: recall and operator convenience are given up so that MAVI never asserts identity or sameness on its own.

## Amendment 2026-10-30 (owner decision D-S7-3): catalogue `mavi-entity-candidates-v2`

The owner accepted this change ("do that", 2026-10-30, relayed by the PoC coordinator session). The decision text above is otherwise unchanged; where it differs, this amendment governs. Status stays Accepted.

**Why.** On a clean import of the 13 demo clips, catalogue v1 proposed **48,898** candidates (47,567 Vehicle, 1,331 Person); re-deriving gave a byte-identical set. The floor did not bound the operator's list, contrary to §3:
- 41,076 (84 %) were same-camera pairs on one clip, the s2-04 night highway: every car paired with every later car, their headlights alike. At floor 0.95 that clip alone still gave 15,659.
- Most of the rest paired cameras of unrelated places: the seven Commons clips come from different cities, given adjacent synthetic recording times. Such a pair is meaningless by construction, not merely implausible.

Both come from two assumptions of v1's scope: that a same-camera revisit is plausible at any later time, and that any two cameras may be paired. Evidence: `E:\MAVI-Controlled\PoC\S7\corpus-run\` (v1 breakdown, the options compared, the same-site breakdown).

**Decision.**
1. **§2 and §3, scope.** Catalogue `mavi-entity-candidates-v2` proposes a pair only when the two Tracks are on **different cameras** that **declare the same site**. A camera with no declared site pairs with nothing. Floor 0.85, tolerance 2 s, no minimum travel time and no maximum gap are unchanged, and the rule stays pair-local. Every parameter names its source in the catalogue.
2. **The site is configuration, never inference.** `cameras.site_code` is an optional, lower-case token set when the camera is created (`POST /api/cameras`, `siteCode`) and fixed afterwards: cameras have no update path in this slice. The PoC demo configuration declares it in `tools/poc/demo-corpus/demo-corpus-v1.json` and both byte-identical `demo-cameras-v1.json` copies, which the S1 installer seeds and the S2 import uses:
   - the six MEVA clips s2-08 to s2-13 (one release, one capture slot, 2018-03-11 16:20) are site `meva-2018-03-11-1620`;
   - each Commons clip s2-01 to s2-07 is its own site (`commons-poc-s2-01` …).
3. **§4, plausibility.** The physical model is unchanged: a Track cannot be in two places at once. The scope rule is separate from it. Confirmation (§6) still checks only physical plausibility against every member, so an Entity may hold two Tracks of one camera when an operator linked each through another camera.
4. **Recompute (§2).** v2 is a new catalogue version: its derivations and candidates are new rows beside v1's; decisions on v1 candidates stay with them and are not shown in v2 lists.
5. **Recorded follow-up option, not part of v2.** A deterministic per-Track bound (top 3 per Track over the whole snapshot, ties by score then candidate id) would cut the demo's same-site cross-camera list from 502 to 127. It is not pair-local, so each new analysis would re-derive the site's whole set. It is to be taken only if 502 proves heavy in use.

**What is lost.**
- Same-camera revisit ("this person came back to the gate") and tracker-fragment linking are never proposed.
- On the demo corpus there are **no vehicle candidates**: the only MEVA camera with vehicles is the car park s2-09, and nothing within the site pairs with it. Demonstration step 8 shows Person candidates across the MEVA cameras.
- A camera without a declared site, including every camera of an installation that predates this amendment, gets no candidates until it is recreated with a site.

