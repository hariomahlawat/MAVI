# MAVI Stage 2 — S1.3 Evidence Read Contract and Minimal UI: implementation plan

**Status:** Implementation-ready plan, revision 3 — two independent cold passes completed 2026-09-24; no P1, all P2 findings resolved (see `docs/reviews/2026-09-24-stage2-s1-3-plan-review.md`)  
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

Pin at least:

- ranks strictly increasing after ordered read;
- rank in 0..3;
- if observations are present, the first is Representative rank 0;
- no duplicate role;
- no duplicate rank;
- count <= 4;
- `RepresentativeObservationId == null` is compatible only with an empty observation collection on the legacy read path;
- `RepresentativeObservationId`, when present, equals the rank-0 observation id.

Do not “repair” rank order, role vocabulary or Representative identity in API code. An impossible persisted combination is an internal server invariant failure, not `track_not_found`, `track_search_invalid`, or a partially repaired 200 response.

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
- existing `representative` callers remain source-compatible;
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

Selecting an item opens/updates one bounded crop-inspection region in the Track evidence composition.

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

The persisted bounding-box overlay remains tied to the Representative observation only in S1.3.

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
- no UI behavior change beyond web type compatibility needed to keep main green.

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

No migration is expected.

### S1.3b expected

Web:

- `src/web/mavi-web/src/api/tracks.ts`
- `src/web/mavi-web/src/features/video-review/TrackEvidence.tsx` (timeline markers only; no Track-specific crop rail inside the shared player)
- `src/web/mavi-web/src/features/video-review/VideoReviewPage.tsx` (Review evidence-rail placement)
- `src/web/mavi-web/src/features/visual-search/TrackInspector.tsx` (Investigation placement)
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
9. analytics identity detail accidentally multiplied by observation joins.

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
- focus in the strip suppresses Investigation window-level J/K result navigation via the existing `data-evidence-player` subtree contract.

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
- Representative compatibility mismatch -> fail closed in tests/read seam; do not choose one silently;
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

1. Track detail exposes all accepted observations in canonical rank order.
2. Representative compatibility is derived from the same rank-0 observation.
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
