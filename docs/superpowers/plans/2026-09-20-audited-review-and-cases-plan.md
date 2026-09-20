# Audited Human Review and Basic Investigation Cases — Implementation Plan

**Date:** 2026-09-20  
**Status:** Proposed; coding starts only after PR #50 is stable and the ADR in Slice 0 is accepted.  
**Base:** `main` after PR #50 merges.  
**Out of scope for this increment (separate, later increments per the capability roadmap):** image similarity, automatic entity grouping, face recognition, mission rules, live ingestion.

## 1. What exists today (inspected)

| Area | Finding |
|---|---|
| Domain | `Track.ReviewStatus` (`Unreviewed`/`Confirmed`/`Rejected`) is a private-set enum with no mutation method; `Entity` carries the same enum and is dormant. `Track.EntityId` is nullable and never set. |
| API / auth | `Mavi.Api` has no authentication or authorization middleware (`Program.cs` maps endpoints directly; no `AddAuthentication`). The Development topology is one Windows workstation; Production profiles run behind IIS on a Windows host (ADR-008). |
| Audit | `Mavi.Application/Modules/Audit`, `Identity`, `Investigations` are reserved boundaries containing only a README. No audit table exists. |
| Persistence | EF Core + PostgreSQL 18; migrations are applied at startup under an advisory lock; completion uses a database-owned visibility sequence (`ProcessingVisibilityBarrier`). |
| Search | The default search returns Tracks of the **latest completed run per video** only; a historical run is reachable through the `processingRunId` filter. Reprocessing therefore hides the earlier run's Tracks from default search but keeps them. |
| UI | Search inspector and Review page display `reviewStatus` via `StatusBadge`; no controls mutate it. |

## 2. Requirements resolved before coding

1. **Meaning of "Confirm Track".** Confirmation accepts the observed track and its object classification (person/vehicle) as correctly detected. It asserts nothing about who or which vehicle it is, and never links a Track to an Entity. The UI label is "Confirm detection"; the API and audit vocabulary is `TrackReviewDecision = Confirmed | Rejected`.
2. **Rejection and revision preserve evidence and history.** No decision deletes or alters Tracks, observations, artefacts or runs. Each decision is an append-only `TrackReviewDecision` row (track, decision, note ≤ 1000 chars, reviewer, server timestamp, superseded-by). `Track.ReviewStatus` is a denormalised projection of the latest decision. Reverting to `Unreviewed` is itself a recorded decision (`Cleared`).
3. **Trustworthy operator identity, server time, authorization.** Decisions record `ReviewerId` and `ReviewerDisplayName` from the server-side principal, never from the request body, and `DecidedAtUtc` from the platform `TimeProvider`. Identity comes from the host: Windows authentication (Negotiate) under IIS/Kestrel is the Phase-1 mechanism consistent with ADR-008 and the offline rule (no remote identity provider). Authorization: a `Reviewer` policy backed by a configured Windows group or allow-list (`Review:AuthorizedGroups`), with a Development-only fallback identity that is clearly labelled in the audit record (`identitySource=development-fallback`) and refused when `production_mode` is set. This is the subject of the Slice-0 ADR.
4. **Atomic state change + audit.** The decision insert and the `Track.ReviewStatus` update happen in one transaction with a row lock on the Track (`SELECT … FOR UPDATE`), and the audit row is the same insert (there is no separate audit write that could diverge).
5. **Concurrency and repeats.** Requests carry the `expectedReviewStatus` the operator saw; a mismatch returns 409 `track_review_conflict` with the current decision so the UI can show what changed. Requests carry a client `decisionId` (UUIDv7); an identical replay returns 200 with the existing decision, a different payload under the same id returns 409 `track_review_decision_conflict`. Two operators deciding concurrently are serialised by the row lock; the later one hits the expectation check.
6. **Consistent persisted state across surfaces.** Search results, inspector and Review read `reviewStatus` from the API; after a decision the UI invalidates the Track query and the search snapshot's item is patched from the response, so all three show the same persisted value. A `latestDecision` summary (decision, reviewer, time, note) is returned on Track detail; the full history is a separate paginated endpoint.
7. **Cases without identity assertions.** A `Case` is a named container (title, purpose, created-by, timestamps) holding `CaseItem`s that reference Tracks (and later other evidence) with an operator note. Adding two Tracks to one case records only that an operator grouped them for investigation; the API and UI never state or infer that they are the same entity, and no `EntityId` is written. Cases are append-only for items (removal is a recorded state change, not a delete).
8. **Reprocessing does not transfer judgements.** Decisions are keyed to the Track id, which is per processing run. A new run creates new Tracks in `Unreviewed`. The UI shows, on a Track of the latest run, that earlier-run Tracks of the same video carry decisions ("Earlier run has N reviewed Tracks") with a link to the historical-run search; nothing is copied automatically. A later increment may offer explicit, audited "carry decision" once overlap rules exist.

## 3. Slices

### Slice 0 — ADR: operator identity and audit baseline (prerequisite, documentation only)
- ADR-010 "Operator identity, authorization and audit for human decisions": Windows-integrated identity, `Reviewer` policy, Development fallback labelling, append-only audit principle, server time authority. Trade-off stated: Windows-integrated auth ties Phase 1 to the Windows host (already the Production topology) and defers a portable identity provider.
- Update `docs/architecture/README.md` and the offline dependency policy if any package is added (Negotiate is in-box for ASP.NET Core).

### Slice 1 — Identity + authorization plumbing (small, testable)
- `AddAuthentication(Negotiate)`, `Reviewer` policy, `ICurrentOperator` (id, display name, identity source) in `Mavi.Application/Modules/Identity`.
- Development fallback only when `ASPNETCORE_ENVIRONMENT=Development` and `Review:AllowDevelopmentFallbackIdentity=true`; refused in Production.
- Endpoints remain anonymous except the new mutation endpoints. Tests: policy denies anonymous mutation; fallback identity labelled; Production refuses fallback.

### Slice 2 — Track review decisions (domain, persistence, API)
- Domain: `TrackReviewDecision` aggregate; `Track.ApplyReviewDecision(decision)` updates the projection only.
- Migration: `track_review_decisions` (append-only; index on `track_id, decided_at_utc desc`; unique `decision_id`).
- API: `POST /api/tracks/{id}/review` (`decision`, `note`, `expectedReviewStatus`, `decisionId`) → 200 with `latestDecision`; 404/409/403 as above. `GET /api/tracks/{id}/review-history?cursor` paginated. Track detail and search items gain `latestDecision` summary (search: reviewer and time only).
- Tests: DB-backed atomicity (decision row and projection in one transaction; failure rolls both back), idempotent replay, conflicting replay, expectation conflict under concurrent requests (two clients, row lock), server-time authority (mutable `TimeProvider`), reviewer from principal not body.

### Slice 3 — Review UI
- Inspector and Review page: "Confirm detection" / "Reject" / "Clear" with a note field; optimistic state disabled — the UI waits for the response and patches search/inspector/review from it. Conflict dialog shows the other operator's decision.
- Decision history disclosure on the Review page. Search filter `reviewStatus` (existing enum) added to the committed-filter contract (`searchState.ts`, canonical param `reviewStatus`).
- Tests: component tests for decision flow, conflict handling, consistent state across list/inspector/review; keyboard access.

### Slice 4 — Basic cases
- Domain/persistence: `Case`, `CaseItem` (track reference, note, added-by, added-at, removed-at nullable), `CaseNote`.
- API: create/list/get case; add/remove Track; add note. All writes record operator and server time; removal is a state change.
- UI: "Add to case" from inspector/Review (case picker + note); Cases page (list, detail with Tracks and notes, links back to search/review). No similarity, no grouping language.
- Tests: DB-backed append-only behaviour, authorization, UI flows.

### Slice 5 — Reprocessing awareness
- Track detail returns `earlierRunDecisions: { runId, reviewedCount }[]` for the same video; Review page shows the notice and link. Test: a reviewed Track on run A, reprocess to run B, new Track is `Unreviewed` and the notice appears; nothing copied.

## 4. Non-goals restated
No image similarity, no automatic entity grouping, no face recognition, no mission rules, no live ingestion. `Entity` stays dormant; `Track.EntityId` is not written by this increment.

## 5. Acceptance for the increment
- Every write is attributable (operator, identity source, server time) and append-only; `Track.ReviewStatus` equals the latest decision for every Track (checked by a DB-backed invariant test).
- Search, inspector and Review show the same persisted status after each decision (component + real-stack check).
- Offline: no new network dependency; any package added is recorded in `config/dependencies/offline-dependency-policy-v1.json`.
- Development evidence only; no change to Production qualification semantics.
