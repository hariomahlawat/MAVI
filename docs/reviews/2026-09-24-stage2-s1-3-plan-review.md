# Stage 2 S1.3 implementation-plan cold review

**Date:** 2026-09-24  
**Reviewed branch:** `docs/stage2-s1-3-implementation-plan`  
**Baseline:** `main@2060599a9786651f36071742034076369520d0ce`  
**Plan:** `docs/superpowers/plans/2026-09-24-stage2-s1-3-evidence-read-ui-implementation.md`  
**Scope:** planning/documentation only; no S1.3 feature code

## Verdict

**No P1. Six P2 planning defects found across three independent cold passes; all resolved before implementation (third pass: P2-5, P2-6, below).**

The revised plan is implementation-ready. It preserves the one authoritative Evidence Set, the existing accepted-evidence security boundary, the one Evidence Player/media controller, historical Track readability, and the S1/S1.4 qualification boundary.

## Review method

The plan was checked cold against the post-PR #79 code rather than against the earlier S1-entry assumptions. The review specifically read:

- `TrackDetailResponse.cs`;
- `TrackSearchRepository.GetDetailAsync`;
- `TrackSearchService.GetDetailAsync`;
- `ITrackSearchRepository` and `TrackSearchResult.cs`;
- `ContentCatalog.GetEvidenceContentAsync`;
- `ContentReadService.OpenEvidenceAsync`;
- `api/tracks.ts`;
- `TrackEvidence.tsx`;
- `EvidencePlayer.tsx`, its `data-evidence-player` shortcut boundary, and `resultNavigation.ts`;
- the parent S1 plan §9 and S1.4 boundary;
- Stage-2 acceptance row B5.

The review attacked backward compatibility, query multiplicity, evidence authorization, source-video/crop semantic confusion, keyboard ownership, and hidden qualification claims.

## P2-1 — crop-strip focus would escape the existing shortcut ownership boundary

### Finding

The first draft placed the new Track Evidence Set strip beside the inner `EvidencePlayer` but only stated that global result navigation should continue to suppress itself “inside the evidence surface.”

That was not implementable from the current code as written.

Investigation binds J/K at the window level. `resultNavigation.isNavigationTarget` suppresses those keys only when the event target has an ancestor carrying the exported `data-evidence-player` attribute. The attribute currently exists on the inner `EvidencePlayer` root. A sibling crop-strip button would therefore sit **outside** that subtree, so pressing J/K while inspecting a crop could move to another Track.

### Resolution

Revision 2 makes the seam explicit:

- `TrackEvidence` owns the whole Track-evidence composition;
- player + crop strip + crop inspector share the existing `EVIDENCE_PLAYER_ATTRIBUTE` subtree contract;
- no second keyboard-suppression mechanism is introduced;
- the strip defines only native activation semantics and does not redefine J/K/L/arrows;
- a discriminating test must focus a strip item and prove Investigation result navigation does not fire.

This preserves the existing “one key, one meaning by focus context” rule.

## P2-2 — the first draft would reject legacy Tracks with no Representative relation

### Finding

The first draft stated that historical v2 Tracks naturally return exactly one Representative and required the first observation to be Representative.

The current Track-detail contract deliberately permits `Representative == null`, and historical/fixture records already exist with no direct Representative relation. S1.3 is a read-layer evolution; it must not retroactively turn an already-readable historical Track into an internal error or fabricate evidence to satisfy a newer completion invariant.

### Resolution

Revision 2 distinguishes:

- **S1.2/v3 Tracks:** expected to have the mandatory Representative under the current completion contract;
- **ordinary v2 completed Tracks:** normally return one Representative observation;
- **legacy records with `RepresentativeObservationId == null`:** remain valid reads with `representative: null` and `observations: []`.

The read seam still fails closed on real contradiction:

- a non-null `RepresentativeObservationId` that does not match rank 0;
- observations present without a coherent Representative;
- duplicate role/rank;
- invalid ordering/vocabulary.

Those are internal invariant failures, not repaired 200 responses.

A regression test for the legacy null-Representative case is now mandatory.

## Confirmed design decisions

### One collection, not two

The new `observations[]` collection is authoritative. The compatibility Representative is derived from it. No second writable/read-authoritative evidence collection is introduced.

### Two bounded queries are preferable to one multiplying join

The current scalar Track-detail query is one row. Observations are bounded to four. The plan's preferred shape—one scalar query plus one ordered bounded observation query—avoids multiplying Track/run/video/analytics projection rows and is easy to audit.

Completed raw evidence is immutable, so no consistency problem is introduced by the two-query read.

### Existing evidence authorization is sufficient

S1.2 already widened the content catalog/read service to both historical `Thumbnail` and v3 `EvidenceCrop`, while still requiring an Observation relation under a Completed ProcessingRun. S1.3 needs no new content endpoint and must not weaken that predicate.

### Search rows should remain Representative-only

Loading supplemental evidence in every Ledger row would increase payload/image traffic and break the existing density contract without a search requirement. The full Evidence Set belongs to detail/Investigation/Review.

### Crop is not frame

A subject crop must never become the Evidence Player poster or source-video stage. The existing UI-5 divergence remains correct: full-frame overlay coordinates belong to the source frame, not to a crop.

### S1.3 is qualification-neutral for the raw pipeline identity

The slice changes read/API/UI behavior only. It must not change the pipeline profile SHA or qualification record and must not claim B6. S1.4 remains the qualification/closure slice.

## Residual implementation risks to watch

These are not plan blockers:

1. Constructor churn: adding `Observations` to `TrackDetailResponse` will touch several .NET contract tests/fixtures. Keep the change mechanical; do not weaken `JsonUnmappedMemberHandling.Disallow`.
2. Fixture drift: web visual-QA fixtures that hand-author Track detail must be updated together so the new non-null array is explicit.
3. Crop-image loading: fixed thumbnail geometry is needed so image success/failure does not cause layout shift.
4. Shared-player temptation: if implementation tries to put Track-specific crop semantics into `shared/evidence/EvidencePlayer`, stop and reconsider. The player should receive only generic timeline/layer evidence; the crop strip remains feature-local.
5. Internal invariant handling: do not translate corrupt persisted evidence into `track_not_found` or `track_search_invalid`; that hides a platform defect.

## Final decision

**Plan revision 2: implementation-ready.**

Recommended implementation sequence remains:

1. S1.3a — read contract / secure projection;
2. S1.3b — minimal Evidence Set UI;
3. S1.4 — hardening, bound proof and qualification closure.

No further architecture review is required before S1.3a unless implementation discovers one of the plan's stop conditions.


---

## Second independent cold pass

A second pass deliberately ignored the first review's conclusions and checked the revised plan against the current read projection and the adopted Review/Investigation archetypes.

### P2-3 — the plan could retain two independent Representative read projections

**Finding.** D1 correctly said `observations[]` must be authoritative, but §5 still allowed the existing scalar `TrackDetailRow` to survive with its full Representative payload while a second observation query was added. On today's code that row contains Representative frame, offset, timestamp, confidence, quality, bbox and artifact fields populated by a dedicated Representative join. An implementation could therefore satisfy the words “query Observations separately” yet still build the compatibility Representative from the old fields.

That leaves exactly the two independently projected representations the architecture says must not drift.

**Resolution.** Revision 3 makes the cleanup mandatory:

- remove the current Representative Observation join from the scalar Track-detail query;
- remove duplicated Representative evidence payload fields from `TrackDetailRow`;
- retain only `RepresentativeObservationId` as the persisted Track integrity pointer;
- read the bounded observation set once;
- derive `TrackRepresentativeResponse` only from rank 0;
- compare the retained pointer against rank 0 and fail on contradiction.

A discriminator is required: mutate the old-style scalar construction path in a scratch/broken variant and prove the tests cannot still pass without reading the canonical observations.

### P2-4 — composing the strip inside `TrackEvidence` violates the frozen Review archetype

**Finding.** Revision 2 put the Evidence Set component inside `TrackEvidence.tsx` to share it between Review and Investigation. In the actual Review page, `TrackEvidence` is the **player column** passed to `ReviewLayout`; the evidence rail is a separate `rail` slot. The adopted UI specification §4.5 explicitly states that Stage-2's bounded Track Evidence Set belongs in the **evidence rail**, with Representative primary, and §4.5.1 requires the Evidence Player plus primary summary to remain visible in the initial 1366×768 viewport.

Putting the strip under `TrackEvidence` would make it part of the player column, not the rail, and could push the primary player vertically while duplicating the rail's evidence role.

**Resolution.** Revision 3 separates **component reuse** from **placement**:

- one feature-local `TrackEvidenceSet` component is reused;
- Review mounts it in the evidence rail, after the primary Track summary;
- Investigation mounts it in the inspector body;
- timeline markers remain in `TrackEvidence` / the one Evidence Player;
- the Evidence Set component itself reuses the existing `data-evidence-player` attribute for keyboard suppression in Investigation;
- Review's 1366×768 visual QA must prove the player and primary summary remain initially visible.

This keeps one implementation without forcing one DOM location and matches the frozen archetypes.

## Second-pass residual checks

The second pass also confirmed:

- two bounded raw-evidence reads need no transaction because completed Track observations are immutable; Scene Analytics identity remains independently resolved as today;
- `ObservationType` is a closed enum with DB CHECK + unique role/rank/frame indexes, so the API may map it to a closed wire string without adding a new persistence vocabulary;
- S1.3a can merge independently because additive JSON fields do not break existing browser consumers, provided all .NET constructors/tests are updated and the web type change is mechanical;
- search rows should continue using the direct Representative thumbnail path; forcing the detail Evidence Set into search would be scope expansion;
- no new content authorization route is necessary because S1.2 already admits both `Thumbnail` and `EvidenceCrop` only through an Observation belonging to a Completed run.

**Second-pass verdict: implementation-ready after revision 3.**

## Third independent cold pass (final pre-implementation review)

**Reviewed:** PR #81 head `bfd433b4ae6e0c1a28e7d517a659898e660ebb48` against `main@2060599a9786651f36071742034076369520d0ce`, which is also the base (0 behind, 11 ahead, documentation only). The review read the current code the plan modifies, not only the plans:
- **Platform:** `TrackSearchRepository.GetDetailAsync`, `TrackSearchService`, `TrackEndpoints`, `Observation`/`ObservationConfiguration`, `Track`, `ProcessingResultStore`, `VisionResultValidator`, `ContentCatalog`, `SemanticAcceptanceTests`.
- **Web:** `api/tracks.ts`, `TrackEvidence`, `EvidencePlayer`, `resultNavigation`, `layouts`, `VideoReviewPage`, `TrackInspector`, `TrackDetailsPanels`, and the typed `TrackDetail` fixtures.

### P2-5 — the read-seam checklist admitted rank sets the write contract forbids

*Finding.* §5.3 required ranks that are strictly increasing, unique and in 0..3, with Representative first. It did not require ranks to be **contiguous `0..n−1` in `ROLE_ORDER`**, which is the rule the v3 completion validator enforces on write (S1.2 plan §6; `VisionResultValidator`). The database does not enforce contiguity or role order: its constraints are rank 0..3, `Representative ⇔ rank 0`, and unique (Track, rank) and (Track, role). So `Representative@0, NearView@2` or `Representative@0, LateDiverse@1, NearView@2` would pass the checklist and render as a 200, despite D1's fail-closed rule. This is the unresolved Codex review thread on the plan, and it is valid.

Two further gaps:
- The Track → Observation foreign key does not prove the Representative pointer names *this* Track's Observation.
- "Internal invariant failure" named no mechanism. `TrackEndpoints` maps a failed `Result` to 400, other endpoints map `DomainValidationException` to 400, and there is no global exception handler.

*Resolution (plan §5.3, §12.1, §13; clarification, no architecture change).*
- The seam checks the full write contract: contiguous ranks, rank order following role order, and pointer = rank-0 id of this Track's collection.
- Failure is an `InvalidOperationException`, which surfaces as HTTP 500 through the existing default handling.
- Discriminating tests seed each corrupt shape directly through the DbContext and assert 500, never 404/400/200.

### P2-6 — S1.3b left two Representative read paths and a duplicated Representative crop in the web

*Finding.* §8 made the Evidence Set and its timeline markers read `observations[]`. It said nothing about the existing web consumers of `detail.representative`:
- the `RepresentativeEvidence` crop panel in the Review rail and in the Investigation "Representative frame" disclosure;
- the bounding-box layer and its accessible description;
- the player's `representative` prop and `E` seek target;
- the `TrackIdentity` Representative scalars.

Two implementers could therefore ship either a second Representative crop beside the strip in each host, or a web where marker and strip follow `observations[0]` while the box, `E` and scalars follow `representative`. That second outcome is a frontend dual authority that fixtures could make disagree while every test passes.

A related gap: the plan did not require the strip and its inspection region to render outside the `EvidencePlayer` root. The player's grammar is a React `onKeyDown` on that root, and `isShortcutTarget` passes every key except Space/Enter on a button. A crop control inside it would seek or step the video on J/L/arrows, while `data-evidence-player` suppressed only result navigation.

*Resolution (plan §7.2, §8.1, §8.3, §8.5, §11, §12.2; clarification, no architecture change).*
- The Evidence Set replaces `RepresentativeEvidence` at its existing position in each host, and no host renders the Representative crop twice.
- One pure rank-0 selector is the web's only Representative source. `detail.representative` stays on the wire and in the type, with no UI reader, enforced by a guard test.
- The strip and its inspection region live outside the player root.
- Tests prove player-grammar keys on a focused crop control do not change the video, Escape still closes the drawer, and a fixture with a deliberately disagreeing `representative` renders only `observations[0]`.

### P3 (resolved in the same revision)

- **P3-1, S1.3a golden.** `tests/fixtures/scene-analytics/c1-operator-contract.json` is compared byte-for-byte with the live Track-detail response, so S1.3a must regenerate it (`MAVI_UPDATE_GOLDEN=1`). The C1 Track has no Representative, so the diff is `"observations": []`, with no token shift. It is added to the S1.3a file map (§11).
- **P3-2, S1.3a web scope.** "Web type compatibility needed to keep main green" is replaced by "no web source change". `apiRequest<TrackDetail>` is an unvalidated typed cast, so the additive field is inert until S1.3b adds it to the type and updates every typed fixture. This is the concrete basis for S1.3a's independent mergeability (§10).

### Confirmed without change

- **One read authority (server):**
  - one bounded observation query;
  - `representative` derived from rank 0;
  - `TrackDetailRow` loses the joined Representative payload and keeps only `RepresentativeObservationId`.
  This is sound, and with P2-5 every contradiction fails closed.
- **Historical compatibility.**
  - `ProcessingResultStore` writes exactly one Representative per Track and attaches the pointer in the completion transaction, for both v2 (`Thumbnail`) and v3 (`EvidenceCrop`).
  - The only legitimate pointer-null shape is the empty legacy one. The C1 semantic-acceptance world exercises it, and the plan preserves it as `representative: null`, `observations: []`.
  - No other legitimate historical shape exists: no platform code deletes or updates Tracks, Observations or runs.
- **Read consistency.**
  - Completed-run Tracks and Observations are immutable, and they become visible only with the Completed status, in one completion transaction.
  - The un-transacted two-query read is therefore safe.
  - The Scene Analytics identity read is already separate and independent today.
  - There is no N+1: one scalar query plus one bounded query.
- **Evidence security.**
  - `ContentCatalog.GetEvidenceContentAsync` serves a `Thumbnail`/`EvidenceCrop` only while an Observation of a Completed run references it.
  - URLs are server-authored; the existing ETag/range/length behaviour is reused.
  - No new authorization layer is needed.
- **UI conformance.**
  - Review keeps player + summary first (§4.5.1), with the Evidence Set in the rail at the old Representative panel's position.
  - Investigation keeps it in the inspector body.
  - The result list is untouched.
- **Timeline / media controller.**
  - Markers come from `observations[]` in the Track evidence path, one per observation, with no duplicate Representative marker.
  - One `<video>`, one timeline, one transport.
- **Qualification.** S1.3 changes read/API/UI only. `pipelineProfileSha256`, the raw qualification records and B6 are untouched, and S1.4 owns closure.

**Third-pass verdict: implementation-ready after revision 4. No P1; P2-5 and P2-6 resolved by plan clarification; no further review cycle is required.**
