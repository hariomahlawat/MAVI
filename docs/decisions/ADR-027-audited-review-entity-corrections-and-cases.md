# ADR-027: Audited Track review, Entity corrections, cases and the audit read surface (PoC Stage 10)

**Status:** **Accepted** owner decision, 2026-10-31: the owner ratified the decision text in §Owner decision as written with option (a) ("Ratify, (a)", relayed by the PoC coordinator session; register decision D-S11-1). §1–§3 and §5–§6 implement the accepted design of `docs/superpowers/plans/2026-09-20-audited-review-and-cases-plan.md` §2 under ADR-010 with the two deviations named in §7; §4 (Entity merge, unlink and reopen) goes beyond ADR-023.

**Date:** 2026-10-31

**Related:** ADR-010 (operator identity, `OperatorPolicy`, append-only `audit_entries`, `IAuditWriter`); ADR-004 (time authority); ADR-020 (`poc-single-host`, Development evidence); ADR-023 (Entities, candidates, confirm/dismiss; §6 and §9 defer merge, unlink and reopen to this slice); ADR-024 (structured query, Entity unit); ADR-025 (analytic events; `repeated-visit` disabled); review plan §2 (requirements 1–8) and slices 2–5; plan `2026-10-28-mavi-poc-end-to-end.md` (S11-full, demonstration steps 8 and 12); register row C10.2.

## Context

S11-min (ADR-010) delivered operator identity and the append-only audit table. S7 (ADR-023) delivered Entity candidates and the confirm/dismiss decisions, final in that slice. The PoC now needs the human-decision layer the review plan designed: confirm or reject a Track's detection, collect evidence into cases, see the audit trail, and correct an Entity decision. Each is an operator decision that must be attributable, server-timed and impossible to rewrite afterwards, and none may assert identity.

## Decision

### 1. Track review decisions (review plan §2.1–§2.6, slice 2)

- **Meaning.** "Confirm detection" accepts the observed Track and its class as correctly detected; "Reject" says it is not a valid detection; "Clear" returns it to Unreviewed. None says who or which object it is, and none touches `Track.EntityId` or any Entity.
- **Append-only history, status as projection.** Each decision is one row of `track_review_decisions` (decision `Confirmed` | `Rejected` | `Cleared`, previous and resulting status, note ≤ 1000 characters, operator id, display name and identity source from `ICurrentOperator`, `decided_at_utc` from `TimeProvider`, the audit entry id, the client `decisionId`, the SHA-256 of the request, and a database sequence for a total order). UPDATE, DELETE and TRUNCATE are refused by triggers, as for `audit_entries`. `tracks.review_status` is the projection of the latest decision (`Cleared` → `Unreviewed`); no other path writes it. The plan's "superseded-by" column is not stored: supersession is the order of the sequence, so no decision row is ever updated.
- **One transaction.** `POST /api/tracks/{id}/review` (JSON, `OperatorPolicy`) opens a transaction, locks the Track (`FOR NO KEY UPDATE`), checks idempotency and expectation, inserts the decision, updates the projection and appends the audit row (`tracks.review-decided`, subject `track`) through `IAuditWriter.AppendInTransactionAsync`; all commit or none does.
- **Concurrency and replay.** The request carries `expectedReviewStatus`; a mismatch is 409 `track_review_conflict` with the current latest decision. The request carries a client `decisionId` (a UUID): an identical replay returns 200 with the stored decision and writes nothing (no second audit row); the same id with a different Track, decision, note or expectation is 409 `track_review_decision_conflict`. Two concurrent decisions on one Track are serialised by the row lock; the later one meets the expectation check. `Cleared` on an Unreviewed Track is refused (409 `track_review_nothing_to_clear`).
- **Reads.** `GET /api/tracks/{id}/review` (operator) returns the status, the latest decision and the reprocessing notice (§5); `GET /api/tracks/{id}/review-history` (operator) pages the history newest first. The anonymous Track search and detail keep returning `reviewStatus` from the same column, so search, inspector and Review show one persisted value; the reviewer's name is only on the operator routes (§7).

### 2. Cases (review plan §2.7, slice 4)

- A **case** is a named container for investigation: title (≤ 200), optional purpose (≤ 2000), created by an operator at server time. It asserts nothing about what its items show. Every surface says: "A case collects evidence for investigation. Items in one case are not asserted to show the same person or vehicle."
- **Items** reference a Track, an analytic event or an Entity by kind and id, with an operator note (≤ 1000). Adding writes a `case_items` row (who, when, note, audit entry id). **Removal is a recorded state change, not a delete**: it sets the item's removal fields (who, when, note, audit entry id) once; a trigger refuses DELETE and TRUNCATE and any UPDATE other than that one transition from not-removed to removed. Re-adding a removed subject is a new item row. At most one active item per (case, kind, subject).
- **Notes** are append-only rows of `case_notes` (≤ 4000), refused UPDATE, DELETE and TRUNCATE.
- **References without foreign keys.** An item's subject is checked to exist when it is added; it is stored as kind and id, not as a foreign key, so no lifecycle that replaces events or Tracks can cascade into a case or be blocked by one. A subject that no longer resolves is shown as unavailable, never silently dropped.
- **No identity, no membership.** Case writes never touch `Track.EntityId`, Entity membership or review status.
- **Routes** (all `OperatorPolicy`; writes are JSON and audited in their transaction): `POST /api/cases` (`cases.created`), `GET /api/cases` (optionally filtered to cases holding a subject), `GET /api/cases/{id}`, `POST /api/cases/{id}/items` (`cases.item-added`), `POST /api/cases/{id}/items/{itemId}/remove` (`cases.item-removed`), `POST /api/cases/{id}/notes` (`cases.note-added`); the audit subject of each is the case.

### 3. The audit read surface (ADR-010 §4, "S11-full adds the read surface")

`GET /api/audit` (`OperatorPolicy`, read-only) pages `audit_entries` newest first (keyset on time and id) with: operator id and display name, identity source, action, subject type and id, server time, payload SHA-256 and correlation id. Filters: one or more `subject=<type>:<id>` (at most 50), `action`, `operatorId`. It is linked from the Track inspector, the Review page, the Entity view and the case view, each passing its own subjects (an Entity passes itself and the candidates that confirmed its members). The payload is not stored (ADR-010 §4), so the surface shows its hash and the subject's own table shows the state.

### 4. Entity corrections: merge, unlink, reopen (beyond ADR-023; owner ratification required)

ADR-023 made confirmations final and deferred these three operations here. They are operator decisions under the same rules as confirm and dismiss (JSON, `OperatorPolicy`, actor from `ICurrentOperator`, server time, one audit row in the decision's transaction, fail-closed, locks taken Tracks first in id order then Entities in id order, `FOR NO KEY UPDATE`, re-checked under the locks). None asserts identity; each corrects or extends an operator's grouping.

- **Membership becomes an append-only history.** `entity_membership_changes` records every join and leave of a Track (Track, Entity, `joined` | `left`, cause `candidate-confirmed` | `unlinked` | `merged`, the candidate or operation that caused it, operator, time, audit entry id). `tracks.entity_id` is its projection. The migration back-fills one `joined` row per existing member from the confirmed candidate that brought it in, with that decision's operator, time and audit entry id. ADR-023 §1's rule becomes: **only an audited operator decision — confirmation, unlink or merge — writes `Track.EntityId`**, and a test enforces that no other code path does.
- **Candidate decisions become an append-only history.** `entity_candidate_decisions` records every confirm, dismiss and reopen; the candidate row's status and decision fields are the projection of the latest one. Back-filled from the decided candidates.
- **Merge** (`entities.merged`, `POST /api/entities/{id}/merge` with `intoEntityId`, note): every member of the source joins the target (a `left`/`joined` pair per Track, cause `merged`); the source becomes `Merged` with `merged_into_entity_id` set, keeps its history and is shown as merged. Refused unless both Entities are active, of one type and distinct, and every member of one is physically plausible with every member of the other under the current candidate catalogue (ADR-023 §4: not concurrent on one camera, not concurrent on two cameras beyond the tolerance); otherwise 409 `entity_merge_implausible` naming the pair. Confirming a candidate whose Tracks are in two Entities stays 409 (`entity_merge_unsupported`); the response points to the explicit merge. A merge is not undone as a unit: Tracks are unlinked one by one.
- **Unlink** (`entities.track-unlinked`, `POST /api/entities/{id}/unlink` with `trackId`, note): the Track leaves the Entity (`left`, cause `unlinked`), `Track.EntityId` becomes null. The Entity stays, with whatever members remain, including one or none (ADR-023 §7 already keeps an empty Entity as the record of a decision). The candidates that confirmed the Track stay `Confirmed` in history.
- **Reopen** (`entities.candidate-reopened`, `POST /api/entity-candidates/{id}/reopen` with note): a `Dismissed` candidate, or a `Confirmed` candidate whose two Tracks are no longer together in one active Entity, returns to `Open` and is listed again; it can then be confirmed or dismissed afresh. A `Confirmed` candidate whose Tracks are still together is refused (409 `entity_candidate_still_linked`: unlink first). Only a candidate of the current catalogue version and embedding identity can be reopened (409 `entity_candidate_superseded`).
- **Consequences for other units.** Membership is no longer monotonic. S9's Entity unit reads membership as of evaluation (ADR-023 amendment) and needs no change. S8's `repeated-visit` stays disabled; its future `mavi-events-v2` (ADR-023 §9) must key derivations on the membership-change ids it read and re-derive on any change, join or leave — the additive-only shortcut of ADR-023 §9 no longer holds.
- **Not decided here:** the open owner option of ADR-023's amendment (extension checked against visible members only) is unchanged.

### 5. Reprocessing awareness (review plan §2.8, slice 5)

Decisions, candidate decisions, memberships and case items are keyed to the Track id of one processing run. A new run creates new Tracks in `Unreviewed` with no Entity; nothing is copied. `GET /api/tracks/{id}/review` returns `earlierRuns`: for the same video, each other completed run with the number of its Tracks that carry a review decision, so the Review page shows "Earlier run has N reviewed Tracks" with a link to that run's search. A case item for an earlier-run Track stays in the case and is labelled "earlier run".

### 6. Storage summary

| Table | Mutability |
|---|---|
| `track_review_decisions` | append-only (triggers) |
| `tracks.review_status` | projection, written only by §1 |
| `cases`, `case_notes` | append-only (triggers) |
| `case_items` | append-only except the one removal transition (trigger) |
| `entity_membership_changes`, `entity_candidate_decisions`, `entity_operations` | append-only (triggers) |
| `tracks.entity_id`, `entities.state`/`merged_into_entity_id`, `entity_candidates` status fields | projections, written only by §4 and ADR-023 §6 |

All of it is local to the installation's database; the PoC uninstall removes it with the database. Case notes and review notes are free text an operator writes: they are shown only on operator routes and never logged.

### 7. Deviations from the review plan, stated

- **Reviewer names only on operator routes.** The plan put the reviewer and time on Track search items and the latest decision on the anonymous Track detail. They are personal data of the operator and part of the audit trail, which ADR-010 puts behind the operator policy; the anonymous routes keep `reviewStatus` only (the same column, so the three surfaces still agree), and the inspector and Review page read the decision from the operator route.
- **No superseded-by column** (§1): the order is the sequence, so no row is ever updated.

## Trade-offs accepted

- **History over convenience.** Corrections are new rows and projections, never edits: an operator cannot remove a mistaken decision, only record a later one, and every view of an Entity or Track can show how it came to be. Storage grows with every decision, which at PoC scale is negligible.
- **Merge is checked, not trusted.** Requiring every cross pair to be physically plausible refuses some merges an operator might want (two views overlapping in time); the alternative would let one click attach an impossible history. It is the same fail-closed rule ADR-023 applies to extension.
- **Cases hold references, not copies.** A case shows a subject as unavailable if its evidence is gone, rather than keeping a copy of evidence outside its lifecycle.
- **Non-monotonic membership** makes a future entity-conditioned event catalogue re-derive on leaves as well as joins.

## Owner decision (ratified 2026-10-31, option (a))

> **ADR-027 (PoC Stage 10) is accepted, with option (a) for the single-member case.**
> 1. Track review decisions, cases and the audit read surface as designed by the review plan §2 (append-only rows, `Track.ReviewStatus` a projection, `expectedReviewStatus` 409 and `decisionId` idempotency, one transaction with the audit row; cases with append-only items whose removal is a recorded state change, notes, no identity language; a read-only audit surface for operators), with two deviations: reviewer names only on operator routes, and no superseded-by column.
> 2. Entity membership and candidate decisions become append-only histories (back-filled from S7's decisions) with `Track.EntityId` and the candidate status as projections; only an audited operator decision (confirm, unlink, merge) writes `Track.EntityId`.
> 3. **Merge** two active Entities of one type when every cross pair is physically plausible (else 409); the source is kept as `Merged`. **Unlink** a Track from its Entity; the Entity stays with its remaining members, even one or none. **Reopen** a dismissed candidate, or a confirmed one whose Tracks are no longer together; current catalogue and identity only.
> 4. Membership is no longer monotonic: a future `repeated-visit` (`mavi-events-v2`) must re-derive on any membership change.
>
> **Options for the single-member case (3):** (a) keep the Entity with one or no member, as ADR-023 §7 does for an empty one — **recommended**: no implicit write the operator did not ask for; (b) dissolve an Entity automatically when it falls below two members — every remaining member is unlinked by the same decision, one more implicit change per unlink.
>
> Accepted trade-off: corrections are recorded, never edits; merge is refused rather than trusted when any cross pair is physically impossible.
