# MAVI Stage 2 — S1.3 Evidence Read Contract and Minimal UI: implementation plan

**Status:** Accepted plan, revision 4 (merged in PR #81; three independent cold passes, no P1, all P2 resolved; see `docs/reviews/2026-09-24-stage2-s1-3-plan-review.md`). **S1.3a (read contract) is complete: PR #82, merged at `main@eb521172c3029750fb64ad0d1851250de926fdf9`.** **S1.3b (minimal Evidence Set UI) is implemented in PR #83, in review**; see §20. S1.3 is complete only once S1.3b is reviewed and merged. **S1.4 is outstanding.**  
**Date:** 2026-09-24  
**Baseline:** `main@2060599a9786651f36071742034076369520d0ce` — PR #79 merged; S1.2 complete  
**Parent plan:** `docs/superpowers/plans/2026-09-23-stage2-s1-track-evidence-set.md` §9  
**Governing architecture:** ADR-006, ADR-012, ADR-013, Stage-2 acceptance register B5  
**Scope:** S1.3 only — persistence/read projection already produced by S1.2, Track-detail API evolution, secure evidence retrieval, and a minimal Evidence Set operator surface  
**Non-goals:** S1.4 qualification claims; VisualAttributeAnalysis; attribute models; attribute search; capability binding v2; prediction UI; OCR/ANPR; embeddings; identity/ReID

---

## 1. Purpose

S1.2 made the bounded Track Evidence Set real in the raw-processing pipeline and platform persistence path. S1.3 makes that accepted evidence visible through the existing Track-detail/read boundary and the existing operator review surfaces without introducing Stage-2 attribute semantics.

The slice closes the gap between **persisted evidence** and **operator-readable evidence**:

1. `GET /api/tracks/{id}` exposes the bounded accepted observation set in canonical rank order.
2. the legacy/direct Representative shape remains available for compatibility but is derived from the same authoritative observation collection;
3. historical v2 Tracks continue to read as a one-observation Evidence Set;
4. every crop URL is platform-authored and served through the existing accepted-evidence boundary;
5. Review and Investigation expose supplemental observations in a compact, bounded, accessible evidence strip while keeping the source-video Evidence Player primary;
6. supplemental evidence does not create attribute, identity, model-quality or qualification claims.

S1.3 changes **read semantics and presentation only**. It does not change the worker, selector, encoder, completion v3, persistence schema, model/runtime profile, pipeline profile or qualification record.

---

## 2. Repository reality at the S1.3 baseline

The plan is based on the merged code at `main@2060599a…`, not the S1 entry state described in older plans.

### 2.1 Persistence is already Evidence-Set capable

S1.2 has already delivered:

- `Observation` rows for Representative / NearView / EarlyDiverse / LateDiverse;
- `EvidenceRank` and `SelectionScore`;
- one crop artifact relation per accepted Observation;
- `ArtifactType.EvidenceCrop` for v3 while historical v2 Representatives may still reference `Thumbnail`;
- `Track.RepresentativeObservationId` as the direct convenience relation;
- v3 validation, sealing, transactionality and replay semantics.

S1.3 MUST NOT introduce another evidence table, another crop relation, or a second authoritative Representative representation.

### 2.2 Current Track-detail projection is Representative-only

`TrackSearchRepository.GetDetailAsync` currently joins:

`Track -> ProcessingRun -> VideoAsset -> Camera -> Representative Observation`

and projects one Representative into `TrackDetailRow`.

`TrackDetailResponse` currently contains:

- Track/run/video/camera/provenance scalars;
- `Representative`;
- trajectory artifact/content URL;
- optional Scene Analytics detail.

This shape remains backward-compatible but gains one bounded `Observations` collection.

### 2.3 Accepted evidence serving already supports both crop generations

`ContentCatalog.GetEvidenceContentAsync` already authorizes:

- historical `Thumbnail` only while referenced by an Observation of a Completed run;
- v3 `EvidenceCrop` under the same completed-run ownership condition;
- Track trajectories through the Track relation.

`ContentReadService` already accepts:

- `Thumbnail + image/jpeg + AcceptedEvidence`;
- `EvidenceCrop + image/jpeg + AcceptedEvidence`;
- `TrackTrajectory + application/msgpack + AcceptedEvidence`.

The existing public read route remains:

`GET /api/artifacts/{artifactId}/content`

S1.3 therefore adds **no new content endpoint** and no filesystem path exposure.

### 2.4 The web has one Evidence Player

`features/video-review/TrackEvidence.tsx` composes the shared `EvidencePlayer` for both Review and Investigation. The player already owns:

- source-video transport and media clock;
- one timeline;
- exact marker seeking;
- typed spatial layers and their accessible descriptions;
- Track interval, Representative marker, trajectory, and Scene Analytics overlays.

S1.3 MUST extend this composition. It MUST NOT add a second video element, second timeline, independent media controller or crop-as-source-frame presentation.

---

## 3. Architectural decisions for S1.3

### D1 — one authoritative observation collection

The Track-detail response gains:

`observations: TrackEvidenceObservationResponse[]`

This collection is authoritative for Track evidence on the read side.

The existing `representative` field stays for compatibility/convenience during S1.3, but the API constructs it **from the rank-0 Representative observation in that same collection**. The repository/service must not maintain a separate Representative projection that can drift from `observations[]`.

Invariant:

- zero or one `representative` value;
- when present, it names the same Observation/artifact/scalars as `observations[0]`;
- an S1.2/v3 Track is expected to have exactly one Representative;
- an ordinary historical v2 Track returns one Representative observation;
- **legacy records with `RepresentativeObservationId == null` remain valid read history and return `representative: null` plus an empty `observations[]`**. S1.3 must not retroactively fabricate evidence or turn an already-readable legacy Track into a 500 merely because newer completion contracts require a Representative.

A corrupted persisted evidence set is not repaired in the read path. DB/domain invariants remain the authority. If `RepresentativeObservationId` is non-null but does not name the rank-0 Representative in the bounded collection, or the collection contains contradictory role/rank data, the read fails as an internal invariant violation rather than choosing one representation silently.

### D2 — neutral API vocabulary for crop artifacts

The database property remains the historical `ThumbnailArtifactId`, because S1.2 deliberately avoided an unnecessary storage-column rename.

The **new API record must not perpetuate that name** for supplemental evidence. It uses neutral names:

- `EvidenceArtifactId`
- `EvidenceContentUrl`

The compatibility `TrackRepresentativeResponse` keeps its existing `ThumbnailArtifactId` / `ThumbnailContentUrl` fields in S1.3.

### D3 — server-authored URLs only

The API constructs every evidence URL from the authoritative artifact relation:

`/api/artifacts/{artifactId}/content`

React consumes the URL returned by the server. It does not construct artifact paths from ids.

This preserves the existing Task-14 evidence boundary and lets a future route/signing policy change without changing the Track UI contract.

### D4 — bounded collection, canonical order

The API returns at most four observations, sorted by `EvidenceRank ASC`.

Each role is single-valued under the current S1 contract.

The API does not sort by score, timestamp or artifact id. Rank is the persisted presentation order defined by the Evidence Set contract.

### D5 — crop preview is not the source frame

Every EvidenceCrop is a subject crop. It is never stretched into the source-video stage and never used as a full-frame poster.

The source video remains the primary evidence surface. The crop strip is a secondary evidence/provenance surface.

### D6 — no qualification inference from Representative

The read/UI contract exposes role, rank and scores, but S1.3 adds no `qualified` boolean because completion 3.0 does not carry one and the accepted two-tier Representative may be fallback.

UI wording therefore MUST NOT say:

- “qualified Representative”;
- “best qualified frame”;
- “verified evidence”.

Supplemental roles remain qualified-only by the raw-pipeline contract, but S1.3 does not turn that implementation property into a general-purpose operator quality badge.

### D7 — no new persistence or runtime identity

S1.3 does not modify:

- worker code;
- pipeline profile;
- scorer/selector;
- model or runtime manifests;
- qualification record;
- completion schemas;
- DB schema.

It should therefore trigger ordinary platform/web correctness gates, not claim a new raw-pipeline qualification identity.

---

## 4. Track-detail contract

### 4.1 New response record

Add a bounded record conceptually equivalent to:

```csharp
public sealed record TrackEvidenceObservationResponse(
    Guid ObservationId,
    string EvidenceRole,
    int EvidenceRank,
    long SourceFrameNumber,
    long VideoOffsetMs,
    DateTimeOffset TimestampUtc,
    double Confidence,
    double QualityScore,
    double SelectionScore,
    TrackBoundingBoxResponse BoundingBox,
    Guid? EvidenceArtifactId,
    string? EvidenceContentUrl);
```

`TrackDetailResponse` gains:

```csharp
IReadOnlyList<TrackEvidenceObservationResponse> Observations
```

The exact collection type may follow existing Contracts conventions, but JSON is an array named `observations`.

Role wire values must be one closed vocabulary, matching persisted domain semantics:

- `Representative`
- `NearView`
- `EarlyDiverse`
- `LateDiverse`

Do not expose arbitrary strings to the web model.

### 4.2 Compatibility Representative

`TrackRepresentativeResponse` remains unchanged in this slice.

It is derived from the canonical Representative observation and maps:

- ObservationId;
- SourceFrameNumber;
- VideoOffsetMs;
- TimestampUtc;
- Confidence;
- QualityScore;
- BoundingBox;
- crop artifact id/url.

`SelectionScore` is available in `observations[]`; do not silently redefine the legacy `QualityScore` field.

### 4.3 Historical v2 behavior

Historical Tracks persisted under ordinary v2 completion return:

- `observations.length == 1`;
- role Representative;
- rank 0;
- existing historical crop artifact, which may be `ArtifactType.Thumbnail`;
- the existing Representative compatibility object with the same content URL.

A legacy Track whose existing direct Representative relation is null remains readable with `observations: []` and `representative: null`. No supplemental or Representative observation is fabricated.

### 4.4 Nullability and unavailable bytes

The Observation row is valid evidence metadata even if the artifact relation/content later cannot be opened.

Therefore:

- `EvidenceArtifactId` / `EvidenceContentUrl` may be null only where the persisted relation is legitimately absent under historical data rules;
- a non-null URL whose bytes later return unavailable is an evidence-content error state, not “no observation”;
- the UI keeps the observation item visible and marks the image unavailable.

The API does not probe artifact bytes while building Track detail.

---

## 5. Application/repository projection

### 5.1 Avoid a cartesian Track-detail query

Do not extend the current one-row Track detail query with a multi-row join that duplicates the whole Track/run/video projection.

Preferred implementation:

1. resolve the Track-detail scalar row once **without joining the Representative Observation**;
2. keep only the Track's direct `RepresentativeObservationId` on that scalar row as the compatibility/integrity pointer;
3. if the Track exists, query its Observations separately with `AsNoTracking()`;
4. order by `EvidenceRank`;
5. project only the bounded fields required by the API;
6. derive the compatibility `TrackRepresentativeResponse` exclusively from the rank-0 item in that bounded observation result.

**Required cleanup:** remove the current Representative observation join and the duplicated Representative frame/time/confidence/quality/bbox/artifact scalar fields from `TrackDetailRow`. Retaining those fields and also adding `observations[]` would preserve two independent read projections and recreate the drift risk D1 exists to eliminate. `RepresentativeObservationId` itself remains because it is the persisted Track integrity/convenience pointer that must be checked against rank 0.

The second query is bounded to four rows by domain contract.

An equivalent server-side grouped projection is acceptable only if it remains obvious, deterministic and does not create duplicate Track/analytics rows.

### 5.2 Repository/application types

Introduce a neutral read value, e.g. `TrackEvidenceObservationRow`, containing:

- observation id;
- role;
- rank;
- frame/time;
- confidence;
- quality/selection score;
- bbox;
- crop artifact id.

Do not return EF entities through the Application boundary.

The Track-detail application result carries:

- the scalar `TrackDetailRow` after removal of the duplicated Representative observation payload fields (retaining `RepresentativeObservationId` only);
- bounded observation tuple/list;
- existing analytics detail identity/result.

### 5.3 Validation at the read seam

Persistence constraints should make invalid combinations impossible, but the read mapping should still fail closed on impossible domain values rather than render contradictory evidence.

The read seam checks the **same Evidence Set contract the v3 completion validator enforces on write** (S1.2 plan §6: "ranks unique and contiguous `0..n−1` in `ROLE_ORDER`"; `VisionResultValidator`). The database enforces only part of it: rank in 0..3, `Representative ⇔ rank 0`, and unique (Track, rank) and (Track, role). **Contiguity and role order are not database constraints**, so the read seam must check them explicitly.

Pin all of:

- count <= 4;
- ranks are exactly `0..n−1` after the ordered read: contiguous, no gap, no duplicate. `Representative@0, NearView@2` is corrupt;
- roles are unique, and rank order follows the canonical role order `Representative < NearView < EarlyDiverse < LateDiverse`, the declaration order of `ObservationType`. `Representative@0, LateDiverse@1, NearView@2` is corrupt, while `Representative@0, LateDiverse@1` is a valid omission;
- if observations are present, the first is Representative rank 0;
- `RepresentativeObservationId == null` is compatible only with an empty observation collection. That is the legacy read path, and the C1 semantic-acceptance world is one such Track;
- `RepresentativeObservationId`, when present, equals the rank-0 observation id of **this** Track's collection. The Track → Observation foreign key does not itself prove the Observation belongs to the same Track, so a pointer to another Track's Observation fails this check.

Do not “repair” rank order, role vocabulary or Representative identity in API code.

**Failure mechanism.** An impossible persisted combination is an internal server invariant failure, not `track_not_found`, `track_search_invalid`, or a partially repaired 200 response. Implement it the same way at every check: the projection throws an `InvalidOperationException` with a stable message such as `track_evidence_set_invariant_violated: <rule>`. Do not throw `DomainValidationException`, which other endpoints map to 400, and do not return a failed `Result`, which `TrackEndpoints` maps to 400. `TrackEndpoints` has no exception mapping and the API has no global exception handler, so the exception surfaces as an ordinary HTTP 500 and is logged. S1.3a adds no new handler or error vocabulary for this.

---

## 6. Evidence content security and compatibility

No new authorization design is needed.

S1.3 reuses:

- `ContentCatalog.GetEvidenceContentAsync`;
- `ContentReadService.OpenEvidenceAsync`;
- `GET /api/artifacts/{id}/content`;
- accepted-evidence no-follow/root-integrity semantics;
- existing ETag/range/content-length behavior.

Add integration assertions that a Track-detail EvidenceCrop URL:

1. resolves with 200 while the completed Observation relation exists;
2. returns authoritative `image/jpeg`;
3. returns the stored length;
4. cannot be substituted with an arbitrary unreferenced Artifact id;
5. historical Thumbnail-backed Representative remains readable.

Do not broaden evidence reads by artifact type alone. The Observation/Completed-run relation remains required.

---

## 7. Web API model

### 7.1 Typed evidence role

Add:

```ts
export const TRACK_EVIDENCE_ROLES = [
  'Representative',
  'NearView',
  'EarlyDiverse',
  'LateDiverse',
] as const;

export type TrackEvidenceRole = (typeof TRACK_EVIDENCE_ROLES)[number];
```

Add `TrackEvidenceObservation` mirroring the server contract.

`TrackDetail` gains:

`observations: TrackEvidenceObservation[]`

Keep `representative` during S1.3.

### 7.2 Contract tests

Pin:

- exact role vocabulary/casing;
- observations always treated as bounded ordered input;
- the `representative` field stays in the `TrackDetail` type, so the type is source-compatible. S1.3b migrates every UI reader of it to the rank-0 selector (§8.1);
- no React component constructs an artifact URL from `evidenceArtifactId`.

---

## 8. Minimal Evidence Set UI

### 8.1 Placement

Implement one feature-local component such as:

`features/video-review/TrackEvidenceSet.tsx`

and **reuse that same component in both hosts**, but place it according to each adopted archetype:

- **Review:** in the `ReviewLayout` evidence rail, after the primary Track summary so §4.5.1 still keeps the Evidence Player + primary summary visible in the initial 1366×768 viewport. It must not be inserted beneath the player column as a second primary canvas.
- **Investigation:** in the existing Track inspector body, near the Track evidence/player and before lower-priority provenance/details as space permits.

“Do not duplicate the strip” means one implementation/component, not one identical DOM location. The UI specification explicitly assigns Stage-2's bounded Evidence Set to Review's evidence rail while Investigation owns it inside the inspector.

**The Evidence Set replaces the existing Representative crop surfaces; it does not sit beside them.** Today both hosts render `RepresentativeEvidence` (`TrackDetailsPanels.tsx`), which shows the Representative crop from `detail.representative.thumbnailContentUrl`:
- **Review:** the rail's "Representative evidence" panel, after Track summary and Scene analytics.
- **Investigation:** the inspector's "Representative frame" disclosure.

In S1.3b the Evidence Set takes exactly that position in each host, and its rank-0 item is the Representative crop:
- **Review:** the panel keeps its place after Track summary and Scene analytics, so §4.5.1 holds at 1366×768. It shows the Evidence Set followed by `TrackIdentity`.
- **Investigation:** the Evidence Set replaces the disclosure's content at the same position in the inspector body. It is rendered uncollapsed, as the compact strip of §8.8.

`RepresentativeEvidence` is removed. No host may render the Representative crop twice.

**One Representative authority in the web.** The web derives the Representative from the rank-0 entry of `observations`, through one pure feature-local selector (for example `representativeObservation(detail)`).

Every Track-detail consumer uses that selector:
- the Evidence Set;
- the timeline marker;
- the Representative bounding-box layer and its accessible description (§8.5);
- the player's `representative` prop and `E` seek target;
- the Representative scalars in `TrackIdentity` (source frame, video offset, confidence, quality score).

`detail.representative` stays on the wire and in the TypeScript type for compatibility, but S1.3b leaves **no UI reader of it**. A guard test fails if feature code outside `api/tracks.ts` reads `.representative`. Search result cards are unaffected: they use `TrackSearchItem`, not `TrackDetail`.

**DOM boundary.** The Evidence Set, including its crop-inspection region (§8.3), is rendered **outside** the `EvidencePlayer` root element. It is never passed into the shared player as a child or slot, and never rendered inside `TrackEvidence`'s player subtree. The player's grammar is a React `onKeyDown` on its own root, and `isShortcutTarget` lets every key except Space/Enter through on a button. A crop button inside the player root would therefore seek or step the video on J/L/arrows.

**Keyboard-scope seam:** Investigation's window-level J/K navigation is suppressed only for targets under the exported `data-evidence-player` boundary. The Evidence Set component itself must therefore reuse `EVIDENCE_PLAYER_ATTRIBUTE` on its own root (or an equivalent wrapper using that exact exported contract), so a focused crop control is recognised as evidence interaction. Do not invent a second shortcut-suppression mechanism and do not wrap the whole inspector merely to obtain suppression. A focused strip button must never move the selected search result when J/K is pressed.

Do not promote the component to `shared/` in S1.3: its semantics are Track-specific and the existing shared Evidence Player remains the correct shared abstraction.

### 8.2 Layout

The Evidence Player remains visually dominant.

The Evidence Set renders as a compact bounded strip in the **Review evidence rail** and the **Investigation inspector body**, with at most four items. It is not placed beneath Review's player column.

Each item shows:

- crop thumbnail or unavailable placeholder;
- operator label:
  - Representative
  - Near view
  - Early diverse
  - Late diverse
- video offset;
- selected state.

Do not show:

- attribute chips;
- classifier/model names;
- “qualified” badges;
- raw selection-score numbers by default;
- detector confidence badges on every thumbnail;
- additional status-badge families.

Technical/provenance scalars remain available in existing secondary detail surfaces where appropriate; S1.3 is not a score-dashboard.

### 8.3 Crop inspection

Selecting an item opens/updates one bounded crop-inspection region **owned by the `TrackEvidenceSet` component**: in Review's rail panel or Investigation's inspector body, outside the Evidence Player root (§8.1).

The inspection region may show:

- larger crop;
- role;
- timestamp/offset;
- detector confidence;
- source-frame number.

It does not replace the source video.

Do not open four full-size crops simultaneously.

### 8.4 Timeline integration

Every accepted observation becomes an Evidence Player timeline marker using its persisted `videoOffsetMs`. Timeline-marker construction stays in the Track evidence/player adapter (or a pure feature-local helper consumed by it); the rail/inspector crop component does not gain transport ownership.

Marker labels are role-specific, e.g.:

- `Representative frame`
- `Near view evidence`
- `Early diverse evidence`
- `Late diverse evidence`

The existing timeline already owns exact marker seeking. Reuse that path instead of adding a second seek controller.

The existing Representative marker is therefore generated from the same `observations[]` set; do not add a duplicate Representative marker from the compatibility field.

Analytics markers remain additive.

### 8.5 Bounding-box layer

The persisted bounding-box overlay remains tied to the Representative observation only in S1.3. It reads the Representative through the rank-0 selector of §8.1, not through `detail.representative`.

Do not dynamically swap the source-video bounding box to a selected supplemental crop unless a later design explicitly defines that interaction. Selection in the crop strip is crop inspection, while timeline markers seek source video.

This keeps the spatial layer semantics unchanged and prevents crop-selection state from silently changing the source-frame overlay.

### 8.6 Missing and error states

Handle independently:

- Track with Representative only;
- 2, 3 or 4 observations;
- supplemental role legitimately omitted;
- crop URL null;
- crop image request fails;
- video unavailable while crop remains readable;
- crop unavailable while video/trajectory remain usable.

A failed crop image must not collapse the strip item. Show an explicit “Evidence image unavailable” placeholder while preserving role and offset.

Do not present an omitted supplemental role as an error.

### 8.7 Accessibility

The strip is a labelled list.

Each item is a real focusable button/control, with a label such as:

`Near view · 00:12.3`

Requirements:

- keyboard selection with Enter/Space;
- visible focus ring;
- selected state exposed with `aria-current`, `aria-pressed`, or the semantically correct equivalent;
- image alt text uses the role + offset, not “image”;
- unavailable image state is textual, not colour-only;
- DOM order equals EvidenceRank;
- no keyboard conflict with Evidence Player/result-navigation grammar when focus is inside the strip: strip-specific controls handle only selection activation; the Evidence Set root reuses the existing evidence-player subtree attribute so window-level result navigation refuses those events. J/K/L/arrows are not redefined by the strip.

### 8.8 Responsive behavior

Acceptance viewports:

- 1366×768;
- 1600-class;
- approximately 2560×1080 sanity check.

At 1366×768 the strip must not push the primary player out of useful view. Prefer horizontal bounded cards/tiles with overflow behavior that remains keyboard reachable rather than a second tall gallery.

At <=1100 px it may wrap/stack under the existing specification rules.

---

## 9. Search/result-card compatibility

S1.3 does **not** change Track search result semantics.

Search rows continue to use the direct Representative thumbnail convenience path.

Do not add supplemental crops to every search row: that would multiply payload/image traffic and make the Ledger denser without a search requirement.

The complete Evidence Set belongs to Track detail / Investigation / Review.

This preserves:

- current cursor semantics;
- current result-row density;
- current Search -> inspector -> Review navigation;
- historical search behavior.

---

## 10. Implementation split

Implement S1.3 as two mergeable PRs.

### S1.3a — read contract

Scope:

- Application/repository bounded observation read;
- `TrackDetailResponse.observations[]`;
- Representative derivation from the canonical observation collection;
- server-authored evidence URLs;
- integration/contract/security tests;
- **no web source change.** The web client decodes Track detail as a plain typed cast (`apiRequest<TrackDetail>`) with no runtime validation, so an extra `observations` field is ignored until S1.3b adds it to `TrackDetail` and updates every typed fixture. This is what makes S1.3a independently mergeable. If S1.3b never lands, `main` serves a backward-compatible superset that no UI reads.

Exit condition:

- v2 and v3 Track details return coherent observation sets;
- Representative compatibility is proven equal to rank 0;
- EvidenceCrop and historical Thumbnail reads are secure and functional;
- all platform/application tests green.

### S1.3b — minimal Evidence Set UI

Scope:

- typed web contract;
- one reusable feature-local `TrackEvidenceSet` component;
- Review rail placement and Investigation inspector placement per the UI specification;
- observation timeline markers in the existing TrackEvidence/EvidencePlayer path;
- compact crop strip + one inspection region;
- loading/unavailable/error/accessibility states;
- visual QA.

Exit condition:

- operator can inspect every persisted Track observation and seek the source video to each observation through the existing timeline;
- Representative remains primary;
- no Stage-2 attribute semantics leak into the UI.

Do not combine unrelated S1.4 performance/qualification work into either PR.

---

## 11. File-impact map

### S1.3a expected

Platform / contracts:

- `src/platform/Mavi.Contracts/Api/Tracks/TrackDetailResponse.cs`
- `src/platform/Mavi.Application/Modules/Intelligence/ITrackSearchRepository.cs` or current repository contract location
- `src/platform/Mavi.Application/Modules/Intelligence/TrackSearchResult.cs`
- `src/platform/Mavi.Application/Modules/Intelligence/TrackSearchService.cs`
- `src/platform/Mavi.Infrastructure/Persistence/Repositories/TrackSearchRepository.cs`
- `src/platform/Mavi.Api/Endpoints/TrackEndpoints.cs`

Tests:

- `tests/Mavi.IntegrationTests/TrackSearchApiTests.cs`
- `tests/Mavi.IntegrationTests/ContentApiTests.cs`
- existing Track analytics contract/detail tests that construct `TrackDetailResponse`
- `tests/fixtures/scene-analytics/c1-operator-contract.json`: a golden that `SemanticAcceptanceTests` compares byte-for-byte against the real Track-detail response. Regenerate it deliberately with `MAVI_UPDATE_GOLDEN=1`. The C1 world's Track has no Representative, so the only expected diff is `"observations": []`, and no id token shifts. `c1OperatorContract.test.tsx` casts it `as unknown as TrackDetail`, so the web suite is unaffected.

No migration is expected.

### S1.3b expected

Web:

- `src/web/mavi-web/src/api/tracks.ts`
- `src/web/mavi-web/src/features/video-review/TrackEvidence.tsx` (observation timeline markers; the Representative box layer, `representative` prop and `E` target move to the rank-0 selector; no Track-specific crop rail inside the shared player)
- `src/web/mavi-web/src/features/video-review/VideoReviewPage.tsx` (Review evidence-rail placement)
- `src/web/mavi-web/src/features/visual-search/TrackInspector.tsx` (Investigation placement, replacing the "Representative frame" disclosure content)
- `src/web/mavi-web/src/features/video-review/TrackDetailsPanels.tsx` (remove `RepresentativeEvidence`; `TrackIdentity` Representative scalars via the rank-0 selector)
- new feature-local Evidence Set component/style as needed
- Review/Investigation fixtures and tests
- web visual-QA fixtures/states if those fixtures model Track detail

Shared Evidence Player changes should be minimal. If implementation discovers that crop-strip interaction requires a generic player API change, stop and justify the seam before adding Track semantics to `shared/evidence/`.

---

## 12. Test matrix

### 12.1 Platform contract tests

Must discriminate against:

1. only Representative projected despite supplemental rows;
2. observation ordering by timestamp instead of rank;
3. duplicate/mismatched Representative compatibility object;
4. legacy null-Representative Track incorrectly rejected or given fabricated evidence;
5. historical Thumbnail rejected because code assumes EvidenceCrop only;
6. EvidenceCrop URL constructed from an unrelated artifact id;
7. arbitrary/unreferenced EvidenceCrop becoming readable;
8. null/absent supplemental treated as corruption;
9. analytics identity detail accidentally multiplied by observation joins;
10. a rank gap (`Representative@0, NearView@2`) accepted as valid;
11. rank order contradicting role order (`Representative@0, LateDiverse@1, NearView@2`) accepted as valid, while `Representative@0, LateDiverse@1` is still accepted;
12. `RepresentativeObservationId` naming another Track's Observation, or a non-rank-0 Observation of this Track, accepted as valid;
13. observations present while `RepresentativeObservationId` is null accepted as valid;
14. any of 10–13 reported as 404, 400 or a repaired 200 instead of HTTP 500.

Cases 10–13 need rows the write path never produces, so the tests seed them directly through the DbContext, bypassing `ProcessingResultStore`. Each asserts a 500 from `GET /api/tracks/{id}`.

### 12.2 Web unit/component tests

Cover:

- Representative-only historical Track;
- four-role v3 Track;
- 2/3-role partial sets;
- DOM order equals rank;
- role labels and exact offsets;
- selecting each crop changes only crop inspection;
- all observations produce one timeline marker each;
- no duplicate Representative marker;
- crop error placeholder retains role/offset;
- source video remains the only video element;
- no direct `/api/artifacts/` construction from ids in the new component;
- keyboard activation and focus state;
- the same Evidence Set component is reused in Review and Investigation while respecting their different archetype placement;
- Review keeps the Evidence Set in the evidence rail after the primary summary;
- focus in the strip suppresses Investigation window-level J/K result navigation via the existing `data-evidence-player` subtree contract;
- with focus on a crop control, the player grammar's non-activation keys (J, L, ←, →, Home, End, E; `EvidencePlayer.onKeyDown`) leave the video's `currentTime` and play state unchanged, and Space/Enter only activate the crop control. This proves the strip is outside the player's key grammar, not just outside result navigation;
- Escape still closes the Investigation drawer from a focused crop control (the workspace's window-capture handler is not gated by `data-evidence-player`), and unrelated inspector controls outside the Evidence Set still receive J/K result navigation;
- neither host renders the Representative crop twice, and `RepresentativeEvidence` is no longer mounted;
- the timeline marker, bounding-box layer, `E` target and `TrackIdentity` Representative scalars follow `observations[0]`, not `detail.representative`. A fixture whose compatibility `representative` deliberately disagrees with `observations[0]` renders only the `observations[0]` values;
- guard: no feature source outside `api/tracks.ts` reads `.representative` of a `TrackDetail`.

### 12.3 Composition guards

Preserve existing source-level guard:

- only the shared Evidence Player mounts the review video;
- TrackEvidence composes rather than reimplements transport/rAF.

Add a focused guard if useful:

- Evidence Set component does not import `useEvidenceTransport`;
- Evidence Set component does not mount `video`;
- no artifact URL template literal is created in feature code.

### 12.4 Visual QA

Capture at least:

1. Representative only;
2. all four roles;
3. one supplemental image unavailable;
4. compact Investigation inspector;
5. Review wide layout with the Evidence Set in the rail;
6. Review at 1366×768 proving the player and primary summary remain in the initial viewport after the Evidence Set is added.

Check 1366×768 and 1600-class acceptance widths; include an ultra-wide sanity capture.

No badge swarm, no layout shift when thumbnails load, no crop stretched as source video.

---

## 13. Failure semantics

S1.3 preserves these truths:

- missing Track -> existing `track_not_found`;
- malformed analytics detail identity -> existing Track-detail 400;
- crop metadata exists but bytes unavailable -> Track detail still succeeds; crop UI shows unavailable;
- trajectory unavailable -> existing trajectory warning remains independent of crop evidence;
- one supplemental role absent -> valid bounded omission;
- Representative compatibility mismatch, rank gap, role-order contradiction, or observations present while the Representative pointer is null -> HTTP 500 through an `InvalidOperationException` from the read seam (§5.3); never 404/400 and never a silently chosen or repaired representation;
- analytics unavailable -> independent from raw Evidence Set;
- crop load failure does not invalidate source-video evidence.

---

## 14. Performance and payload bounds

Track detail adds at most four small observation records.

S1.3 does not add supplemental crops to Track search lists.

API acceptance target:

- Track-detail JSON remains trivially bounded by four observations;
- no N+1 artifact-content reads during API projection;
- crop bytes are loaded by the browser only for the selected/open Track;
- at most four crop image requests per open detail if the strip eagerly renders all thumbnails; lazy loading is acceptable but not required at this bound.

Measure the final Track-detail JSON size for a four-observation fixture and record it in the PR. No new global request-body limit is required.

---

## 15. Offline and dependency impact

Expected dependency impact: **none**.

S1.3 must add no:

- npm package;
- NuGet package;
- Python package;
- native binary;
- model;
- database extension;
- online service.

Disconnected path to prove in S1.3b:

`completed v3 Track -> GET Track detail -> source video + EvidenceCrop URLs -> Review/Investigation Evidence Set`

All bytes come from MAVI-owned media / accepted evidence.

---

## 16. Qualification consequence

S1.3 changes the read/API/UI layer, not the raw-processing pipeline profile.

Therefore:

- do not alter `pipelineProfileSha256`;
- do not alter RTMDet/Runtime Pack qualification records;
- do not claim S1 B6;
- do not mark pending raw-pipeline gates passed merely because S1.3 CI is green.

Required merge evidence:

- exact-head Quality Gate;
- relevant platform/integration tests;
- web unit/build tests;
- Task 17 acceptance if path filters trigger it;
- visual/accessibility QA for S1.3b;
- no unresolved P1/P2.

S1.4 remains responsible for the end-to-end bound proofs and qualification rebinding/acceptance closure.

---

## 17. Acceptance criteria

S1.3 is complete only when all are true:

1. Track detail exposes all accepted observations in canonical rank order. Any persisted set that breaks the Evidence Set contract (§5.3) fails as HTTP 500.
2. Representative compatibility is derived from the same rank-0 observation. The web reads the Representative only through that rank-0 entry, and no host renders the Representative crop twice.
3. ordinary historical v2 Track detail still works and returns one observation; legacy Track detail with no Representative relation remains readable with an empty observation set.
4. EvidenceCrop and historical Thumbnail bytes are served only through the existing authorized accepted-evidence route.
5. Search rows remain Representative-only and unchanged in density/semantics.
6. Review and Investigation show the same bounded Evidence Set component.
7. Representative remains primary; the source-video Evidence Player remains the dominant evidence surface.
8. every observation has a role-labelled timeline marker and exact existing marker seek behavior.
9. one crop-inspection region shows the selected subject crop without pretending it is a source frame.
10. omitted supplementals, unavailable crop bytes and trajectory errors are distinct states.
11. keyboard/focus/alt-text requirements pass.
12. no attribute/model/identity semantics are introduced.
13. no dependency, migration, pipeline-profile or qualification-record change is introduced.
14. exact-head CI is green and final cold review has no open P1/P2.

---

## 18. Stop conditions

Stop and amend the plan rather than coding around any of these:

- current persisted Observation rows cannot be projected as one bounded authoritative collection without schema change;
- serving EvidenceCrop through the existing content boundary requires weakening Completed-run/reference authorization;
- a UI implementation requires a second video/media controller;
- crop selection would require presenting a crop as full-frame source evidence;
- backward compatibility requires two independently writable Representative representations;
- implementation begins adding attribute predictions/search/model semantics;
- a new dependency is proposed for a four-item strip or image preview.

---

## 19. Handoff after S1.3

After S1.3 merges:

- S1.4 runs hardening, resource/bound evidence, disconnected end-to-end evidence and qualification rebinding/closure for B1–B6;
- Stage-2 model work still does **not** start merely because crops are visible;
- after S1 closes, the Stage-2 parent sequencing proceeds to S2a Component Binding v2, then S2b fixture attribute lifecycle and later real Model Packs.

The architectural boundary remains deliberate:

**S1 produces and exposes trustworthy raw Track evidence. Later Stage-2 slices derive replaceable model-based intelligence from that evidence.**

---

## 20. Implementation status

### 20.1 S1.3a — read contract (PR #82, merged)

Baseline `main@0eb969a6e9205467f1dd275995e09aa5b9acd887` (PR #81 merged). Merged as `main@eb521172c3029750fb64ad0d1851250de926fdf9`; S1.3a is complete. This implements §4–§6, §10 S1.3a and §12.1. It makes no web source change (§10).

**Implemented:**
- **Evidence Set.** `TrackDetailResponse.observations[]`, typed `TrackEvidenceObservationResponse`, is the authoritative read-side Evidence Set.
- **Representative.** The compatibility `representative` is built only from `observations[0]`.
- **Scalar row.** `TrackDetailRow` no longer carries the joined Representative payload. It keeps only `RepresentativeObservationId`, and a structural test guards against its return.
- **Bounded read.** The Evidence Set is read by `ITrackSearchRepository.GetEvidenceSetAsync`: one statement, ordered by `EvidenceRank`, `LIMIT` `MaximumCount + 1`. `TrackDetailQueryShapeTests` pins exactly two raw-evidence statements for one Observation or four, and a constant whole-detail statement count.
- **Validation.** `TrackEvidenceSet.FromPersisted` checks the full §5.3 contract: count, contiguous `0..n−1`, strictly canonical role order, and the Track-local rank-0 pointer. It never re-sorts, repairs or trims.
- **Legacy shape.** No pointer and no Observations reads as `representative: null`, `observations: []`.
- **Evidence URLs.** They are server-authored from each Observation's own crop relation. `ContentCatalog`'s accepted-evidence boundary is reused unchanged.
- **Golden.** `c1-operator-contract.json` is regenerated. The only diff is `"observations": []`.

**Implementation refinements (recorded; no architecture change):**

| # | Plan text | Implemented | Why |
|---|---|---|---|
| R1 | §5.3: the read seam throws `InvalidOperationException`; with no global handler it surfaces as an ordinary 500; no new handler or error vocabulary | `TrackEvidenceSetInvariantException` (an `InvalidOperationException` carrying the violated rule) is caught in `TrackEndpoints.GetAsync` and returned as `Problem(500, "track_evidence_integrity_failure", "The Track's persisted evidence is invalid.")`. The rule and Track id are logged (event 1420, `track_evidence_integrity_failure`). | This follows the repository's existing integrity-failure convention (`ProcessingEndpoints`: `processing_attestation_integrity_failure`). It gives an RFC 7807 body with no internal detail, and avoids a developer exception page in Development. The status is the same, and it is still never a 404, 400 or repaired 200. |
| R2 | §5.3: canonical role order | The role order moves from `VisionResultValidator`'s private array to Domain `EvidenceRoleOrder.Canonical`, used by both the write validator and the read seam. | One definition instead of two; write-side behaviour is unchanged. |
| R3 | §5.1: scalar row, then the Evidence Set | The Evidence Set is read after the analytics identity resolves. | Every existing 404/400 outcome stays identical, even over corrupt evidence, and evidence is not read for a refused request (`TrackDetailEvidenceServiceTests`). |
| R4 | §4 D4: at most four | The query reads up to five rows. | An over-full set is refused as `TooManyObservations` rather than silently truncated into a valid-looking four. |

**Measured (§14):** Track-detail JSON is 2,250 B with one Observation and 3,655 B with four (seeded fixture; about 470 B per Observation).

**Not done in S1.3a:**
- the web type, the Evidence Set UI and timeline markers (S1.3b, §20.2);
- bound proofs at volume and qualification closure (S1.4).

The pipeline profile, the model/runtime records and the qualification record are unchanged. B5 stays OPEN.

### 20.2 S1.3b — minimal Evidence Set UI (PR #83, in review; not merged)

Baseline `main@eb521172c3029750fb64ad0d1851250de926fdf9` (PR #82 merged). This implements §7, §8, §10 S1.3b and §12.2–§12.4. It changes no server, worker, persistence, schema, pipeline-profile or dependency.

**Implemented:**
- **Web contract.** `TRACK_EVIDENCE_ROLES`, `TrackEvidenceObservation` and `TrackDetail.observations` mirror the S1.3a response. `representative` stays on the type for wire compatibility only.
- **One Representative authority.** `features/video-review/evidenceSet.ts` `representativeObservation(detail)` returns rank 0. The bounding-box layer and its description, the player's `representative`/`E` target, the Representative timeline marker and the `TrackIdentity` Representative scalars all read it. A source guard fails if feature code reads `.representative` of a Track detail, and a test fixture whose compatibility `representative` disagrees with `observations[0]` renders only `observations[0]`.
- **One Evidence Set component.** `features/video-review/TrackEvidenceSet.tsx`, mounted by both hosts: Review's evidence rail in the old Representative panel's place (after Track summary and Scene analytics, followed by `TrackIdentity`), and the Investigation inspector in place of the Representative-frame disclosure, uncollapsed. `RepresentativeEvidence` is removed.
- **Timeline.** Every Observation is one exact-seek marker from the existing `TrackEvidence` → `EvidencePlayer` path, the Representative marker included, so it is never duplicated. Supplemental markers use a shorter tick than the Representative's.
- **Crop inspection.** Selecting an Observation changes only the one inspection region: no seek, play, pause, overlay or media change. The crop is contained in its own matte and never presented as the source frame.
- **States.** A failed crop and a never-persisted crop each keep the Observation's role and offset and say so in words; an omitted supplemental role is not an error; the legacy shape states that no Evidence Set was persisted; video and crop failures are independent.
- **Visual QA.** The harness cuts each Evidence Set crop from the generated footage at the Observation's offset and box at run time (no committed binaries), and adds the Evidence Set states at 1366, 1600, 1920 and 2560.

**Implementation refinements (recorded; no architecture change):**

| # | Plan text | Implemented | Why |
|---|---|---|---|
| R5 | §8.1, §12.2: Escape still closes the Investigation drawer from a focused crop control because "the workspace's window-capture handler is not gated by `data-evidence-player`" | That handler belongs to `WorkbenchLayout`; Investigation closes its inspector only through `VisualSearchPage`'s window handler, which refused every key from the evidence subtree, Escape included. Escape is now decided before that gate (`isDismissTarget`): it closes the inspector from the Evidence Set and from the Evidence Player alike. J/K/↑/↓/Enter stay refused there, and text fields still keep Escape. | The audit found the plan's premise contradicted the code; the owner chose this resolution before implementation. No evidence grammar binds Escape, so the subtree never needed to refuse it. The same subtree attribute is reused; no second suppression mechanism exists. |
| R6 | §8.2: "a compact bounded strip" of cards/tiles | The inspected crop sits beside a rank-ordered list of the four Observations (thumbnail, role, offset). | In a four-tile row at 1366 the rail truncated "Representative" and "Early diverse"; the list keeps every role and offset legible and costs the height of one crop rather than a crop plus a gallery. |
| R7 | §8.7: selected state via `aria-current`, `aria-pressed` or equivalent | `aria-current="true"` on the inspected Observation, plus a doubled accent border. | The selection is one-of-n and never toggled off, which is `aria-current`'s meaning; the result list uses the same semantics. The border weight carries the state without relying on hue. |
| R8 | §8.4: every Observation is a timeline marker | Unchanged; recorded consequence. The shared timeline caps marker rows at three, so four instants inside a short Track on a long video can saturate the rail. The unplaced marker is then carried by the timeline's existing dense navigator, still once and still an exact seek (pinned by test). | Changing the shared rail is a generic Evidence Player change and out of S1.3 scope (§11). A Track-zoomed timeline would remove the saturation; it is a later player decision. |

**Not done in S1.3b:** bound proofs at volume, the disconnected end-to-end run and qualification closure (S1.4). Search rows are unchanged and remain Representative-only (§9). B5 stays OPEN until the S1.4 evidence.

