# Stage 2 S2b — Attribute Lifecycle with Fixture Inferencer

**Status:** Implementation plan — amended after independent Claude 5 review and repository verification  
**Date:** 2026-09-28  
**Starting baseline:** `main@406172657599350ecbb27819865ecc9482c6c97d`  
**Governing:** ADR-013, ADR-014, ADR-006, ADR-009, Stage-2 parent plan, authoritative Stage-2 acceptance register  
**Exit gate:** D1–D8 plus S2b-owned E1–E4 PASS from executed evidence; deterministic fixture only; no real attribute model.

## 1. Objective

Implement the complete Visual Attribute asynchronous lifecycle and transport boundary without introducing a learned attribute model. S2b proves queueing, leasing, heartbeat, authorised evidence transport, bounded prediction upload, fenced completion/failure, recovery/retry, atomic publication, supersession and independent worker failure isolation. The deterministic fixture replaces only learned inference computation and traverses the same process/HTTP/evidence/upload/completion path that S2c will use.

## 2. Non-goals and ownership

S2b does not introduce real person/vehicle checkpoints, learned-model qualification, operational vocabulary, attribute search/cursor v4, final operator UI, Production/CUDA promotion, direct Python access to platform evidence/staging, or a generic IntelligenceJob abstraction.

S2b owns lifecycle persistence/integrity required to publish a completed analysis (acceptance E1–E4). S3 owns search/cursor/predicate/query-plan work (E5–E8). The acceptance register is authoritative for this split.

## 3. Reconcile current main before coding

Record exact `main` SHA and inspect intervening commits. Read ADR-006/009/011/013/014; Stage-2 parent plan/register; VisionJob and SceneAnalysis lifecycle code; accepted-evidence reader/sealing/finalization; current staging janitor; worker HTTP client; Component Binding/runtime resolver/launcher; request-limit middleware; and `EmbeddingExtractor` usages.

Do not assume “VisionJob shape” means identical failure semantics. Reuse only proven-common primitives. If this plan conflicts with a governing ADR, stop and reconcile documentation.

During S2b.1, resolve the currently unused `EmbeddingExtractor` explicitly: remove it if it remains unused, or retain it only with Stage-5-specific documentation. It must not become a generic inferencer abstraction for S2b.

## 4. Domain aggregate, identity and default selection

Create capability-specific `VisualAttributeAnalysis`, one unit per `(ProcessingRun, immutable analysis identity)`.

Semantic identity is exactly: ProcessingRunId; attribute schema version/SHA; attribute pipeline version; aggregation-policy version/SHA; ordered capability/Model Pack identities; parameters SHA-256. Runtime Pack/variant, actual device, worker id, platform build and repository commit are provenance, not semantic identity.

States: `Queued`, `Running`, `Completed`, `Failed`, `Superseded`.

The currently enabled Component Binding determines the **preferred/default identity** for a run. Completion order does not. On successful completion, lock the run's relevant analyses in deterministic id order. A completion matching the current preferred identity may supersede the previous default. A late completion of an obsolete identity completes directly as historical/Superseded and must not displace the preferred completed analysis. Failed replacement work never supersedes successful history.

If only obsolete identities have completed and the preferred identity has never completed, there is no default current analysis; readiness is `Stale` until the preferred identity completes or an explicit re-analysis is requested. On a binding rollback (for example B→A), default/readiness is re-derived from an already-successful analysis matching A rather than attempting to insert a duplicate `(run, identity)` unit. Historical Superseded state must not prevent an existing successful matching identity from becoming the derived default again.

Readiness derives `Stale` when the completed/default semantic identity no longer matches the currently enabled identity. Binding change does not rewrite history or automatically backfill old runs.

## 5. Independent attributes role

Activate an independently startable `attributes` role with its own READY/device/provenance/lease/heartbeat/crash/OOM domain. S2a provided multi-role schema but only `vision` is currently startable; S2b implements the second role explicitly.

The fixture identity is Development/test-only. Production profiles must refuse it; enabling fixture support must not make a Production component registry accept it.

The transport must not require shared filesystem access. “Future remote GPU node” means remote-capable transport topology; S2b does not silently claim worker authentication beyond the repository's current trust posture. Operator diagnostics must distinguish a Queued analysis with no READY attributes worker from ordinary pending work, without inventing a new lifecycle state.

## 6. Shared primitives — deliberately narrow

Extract/reuse only semantics that are genuinely common: lease capability generation/hash/constant-time validation/non-echo handling and canonical SHA-256 validation/representation.

Do not force a generic claim helper/state machine merely because all planes use `SKIP LOCKED`; eligibility/reclaim semantics differ. Completion replay/digest logic may be shared only if exact semantics are first proven identical. Regression tests prove VisionJob and SceneAnalysis behaviour is unchanged.

## 7. Persistence and migration

Persist analysis identity, status, attempt, worker, lease material/expiry, heartbeat, absolute deadline, completion digest, prediction artefact descriptor/link, provenance, coverage/counts, visibility sequence and supersession/default linkage.

Implement lifecycle fact rows now:
- `VisualAttributeTrackOutcome(AnalysisId, TrackId)` — `Analysed | Unavailable`, deterministic reason where applicable;
- final `VisualAttribute` — exactly one per applicable `(AnalysisId, TrackId, AttributeType)` for Analysed Tracks, `Observed | Unknown`; Observed requires schema-coded value, confidence and supporting Observation; Unknown has no fabricated negative meaning.

Evidence FKs use Restrict. Producer provenance belongs on the analysis header. The existing placeholder `VisualAttribute` entity/table is explicitly replaced/reshaped rather than left as a contradictory second schema.

Constraints/indexes enforce one unit per `(run, identity)`, one outcome per Track, final-row uniqueness, and bounded queue claims. Do not add S3 search indexes except integrity/claim indexes required for S2b.

## 8. Queue, claim, heartbeat, retry, deadline and cancellation

A reconciler queues only when a completed/visible ProcessingRun has an enabled attribute identity and applicable Tracks. No capability => `NotConfigured`; no applicable Tracks => `NotApplicable`.

Worker supervisor does not call lease while required fixture/capability is unavailable. Startup-unavailable leaves work Queued and consumes no attempt. Use bounded readiness polling/backoff.

Claim uses domain-specific `FOR UPDATE SKIP LOCKED`, increments attempt, issues fresh capability and sets lease expiry. The absolute maximum-analysis deadline is anchored at the **first successful claim**, not queue creation; never-claimed Queued work therefore cannot deadline-fail merely because no worker was deployed. Heartbeat extends only an unexpired matching lease and runs concurrently with evidence reads, inference and upload using an explicit safety margin derived from the existing worker rule. Expired lease is reclaimable; new attempt/token fences the old executor.

Pin typed failure codes as **retryable** or **terminal**. Retryable failure returns unit to Queued if attempts/deadline permit, clears active lease and preserves diagnostic history. Terminal failure marks Failed. Attempt exhaustion or absolute deadline is terminal.

Deadline enforcement must not depend on another worker request: add a bounded reconciler/sweep or equivalent platform authority that can transition claimed units whose absolute deadline is exceeded even when no worker is polling. Model/capability loss after a legitimate claim follows failure taxonomy and consumes that attempt.

S2b does not invent an operator `Cancelled` state unless a concrete operator API is intentionally added. “Cancellation” in D7 means request/process cancellation and lease loss: stop work promptly, publish nothing, and let reclaim/deadline semantics decide the unit.

## 9. HTTP/token contract and replay precedence

Endpoints: lease, heartbeat, evidence read, prediction upload, complete, fail.

Attribute routes use **header-only lease capability**. Do not include `leaseToken` in JSON envelope, completion digest, persistence, URL/query, errors or logs. Reject a body token. Envelope contains schemaVersion, analysis/job id, worker id, attempt, provenance and typed payload.

Replay precedence:
- previously committed completion + same digest returns stored success even if old lease has expired;
- committed completion + different digest => conflict;
- first-time completion requires Running + matching active attempt + unexpired lease at Phase A; Phase C fencing is defined separately in §13;
- upload replay in same active attempt: same SHA/size => idempotent; different descriptor => conflict;
- fail replay is idempotent only for the same recorded transition and never overwrites/resurrects a later attempt.

Provenance fields required by ADR-013 remain in completion-digest replay identity; semantic analysis identity remains separate.

## 10. Lease-scoped evidence read

Lease grants no browsing capability. Requested Observation must join through Track to the analysis ProcessingRun and be an authorised accepted EvidenceCrop.

Before response headers, validate Running/attempt/lease, ownership, artefact type and accepted object's recorded size. Stream only through `IAcceptedEvidenceReader`; no listing/search endpoint; audit analysis/attempt/Observation/bytes/outcome without secrets. Worker verifies complete received size and SHA before decode.

Distinguish permanent evidence condition from transport failure:
- explicit platform-authoritative sealed-object missing/integrity failure, or a fully received body whose size/SHA disagrees, may produce deterministic Track `Unavailable` and raises an operator-visible integrity/audit signal;
- connection reset, timeout, 5xx, truncated transfer or other transient transport error gets bounded retry inside the active lease; persistent transport failure fails the **attempt as retryable** and must not publish Track Unavailable.

Foreign/stale/mismatched requests fail before body emission. Lease loss/cancellation aborts streaming.

## 11. Prediction artefact encoding

Do not add a .NET MessagePack dependency merely because Python already has msgpack. Correct ADR-013's non-normative dependency wording during implementation documentation reconciliation.

**S2b encoding decision:** canonical UTF-8 JSON for `AttributePredictions`, unless implementation-baseline dependency review identifies an already-qualified cross-language format requiring no new package. JSON uses existing platform/Python stacks.

The platform hashes the **received bytes** and never re-serialises them to establish artefact identity. Structural validation uses a bounded/streaming reader rather than requiring a 64 MiB DOM. The artefact is the non-authoritative prediction/forensic record; relational Track-level rows are the authoritative query facts. Platform validation binds schema id/version, analysis identity fingerprint, deterministic Observation identifiers, bounded prediction/aggregation records, and descriptor/relational cardinalities. It is not required to reproduce every aggregation decision value-by-value unless implementation testing demonstrates that this is necessary for integrity; any such stronger check must remain streaming/bounded. Canonical serialization rules are pinned for deterministic worker output and replay stability. Maximum accepted artefact size: 64 MiB.

## 12. Upload staging and janitor authority

Use a dedicated platform-owned namespace `staging-attributes/{analysisId}/attempt-NNNN/`; never place uploads where the VisionJob `StagingJanitor` interprets them as unknown jobs.

Streaming writer writes a temp file under the authorised attempt, enforces declared/streamed cap while hashing, flushes/fsyncs as supported, atomically renames, and records size/SHA. SHA mismatch uses the pinned integrity failure code `vision_result_artifact_integrity_failed`. Attribute staging has its own janitor authority keyed by `VisualAttributeAnalysis`: keep current Running attempt; delete older attempts; delete terminal staging after defined grace; never delete current attempt merely because it is old. Add reclaim/janitor race tests. Worker cannot nominate arbitrary platform paths.

The accepted sealed key is content-addressed by artefact identity/hash and is **not attempt-scoped**. Attempt number belongs only to staging. Therefore a later attempt producing identical bytes may adopt the already-sealed accepted object after verifying its descriptor; same-attempt upload replay remains governed by §9.

## 13. Publication protocol — ADR-006 order

Sealing is filesystem publication and is **not** inside a DB transaction.

### Phase A — fenced validation
Under row locks validate state/attempt/lease (or committed replay), typed bounds, Track/Observation ownership, staged descriptor, exact outcome/final-row cardinality and completion digest. Release Phase-A transactional locks before potentially expensive filesystem sealing; correctness therefore depends on the mandatory Phase-C re-fence below.

### Phase B — idempotent seal
Seal staged `AttributePredictions` with create-new semantics to a content-addressed accepted key. Existing identical object is verified/adopted. Never delete an accepted sealed object as rollback compensation. Crash after seal/before commit leaves DB unpublished; retry adopts identical bytes. Ambiguous DB commit is resolved by committed-digest replay first.

### Phase C — re-fence and one DB publication transaction
Re-acquire the `VisualAttributeAnalysis` unit row `FOR UPDATE` and re-verify that the unit is still `Running`, the **attempt number** still matches, and the stored capability hash still matches the presented capability before publishing any relational fact. If another attempt reclaimed the unit after Phase A, abort publication; the already-sealed content-addressed object is a tolerated/reusable orphan. **Lease expiry by itself does not invalidate Phase C if no reclaim has occurred and the same attempt/capability still owns the unit**; ownership fencing, not wall-clock expiry after successful Phase-A validation, decides whether that validated completion may publish. Committed replay remains checked before this first-time publication path.

Within the same Phase-C DB transaction, persist final outcomes/attribute rows, accepted artefact reference, provenance, counts and digest; perform expensive row work before the visibility barrier where possible; acquire established visibility sequencing/barrier as late as correctness permits; mark Completed/assign sequence; apply deterministic preferred/default/supersession rule.

Any failure before DB commit leaves no fact-bearing analysis. Orphan accepted bytes are tolerated/reusable; partial relational publication is not.

### Completion execution mode
Synchronous completion is permitted only if measurement at the 10,000-Track supported bound demonstrates safe request/lock/visibility margin. Measure before freezing. If not, use the established asynchronous `Finalizing` hand-off pattern rather than arbitrarily increasing timeouts. Record decision/evidence in implementation PR.

## 14. Deterministic fixture inferencer

Fixture replaces only learned inference computation. It uses the real independent process, lease, concurrent heartbeat, HTTP evidence reads, byte verification, production prediction encoding, upload, completion/failure, fencing, sealing and publication paths.

Outputs derive from evidence/fixture identity, not clock/random state. It produces Observed and Unknown. Permanent platform-authoritative evidence failures exercise Unavailable; transport failures exercise retryable attempt failure. No fixture-only endpoint, direct DB/filesystem access or publication shortcut.

## 15. Numeric bounds and request limits

Derive concrete numbers before endpoints are complete. Do not inherit the repository-wide ~3 GiB Kestrel import limit.

Pin/enforce:
- Tracks per analysis: existing maximum 10,000;
- descriptors per Track: Evidence Set bound;
- total lease descriptor count/serialized response bytes; if unsuitable for one response, use bounded lease-fenced paging;
- completion body maximum derived from 10,000 Tracks × applicable attribute types + protocol overhead;
- prediction upload: 64 MiB hard request/stream cap;
- heartbeat/fail: small explicit caps;
- evidence response: exactly recorded accepted-object size;
- no unbounded in-memory buffering.

Add route-specific limits and cap+1 tests. Synthetic worst-shape payloads may exercise validators without slow inference.

## 16. Required race/security tests

Prove: concurrent claim uniqueness; stale/expired/reclaimed lease denial; same-digest completion replay after expiry; **reclaim between Phase A and Phase C causes Phase-C re-fence rejection while the sealed orphan remains safe**; expiry after Phase A without reclaim remains publishable only by the still-owning same attempt/capability; foreign run/Observation denial before body; token absence from body/URL/log/error; transient/truncated evidence never becomes permanent Unavailable; authoritative integrity failure gives pinned reason/audit; no decode before size/SHA verification; same-SHA upload replay idempotent/different-SHA conflict; 64 MiB streaming cap; janitor current-attempt safety; crash after seal recovery; ambiguous commit replay; late obsolete identity cannot become default; binding rollback re-derives an existing successful matching identity without duplicate insertion; retryable vs terminal failure and exhaustion/deadline; never-claimed Queued work does not deadline-fail; deadline transition after first claim without polling worker; binding change => Stale; failed replacement preserves prior success; Production refuses fixture; VisionJob/SceneAnalysis regression tests remain green.

## 17. Test-first implementation sequence

1. **S2b.1 — contracts/shared primitives:** regression tests; narrow lease/SHA extraction; token/replay/request-limit contracts; explicit `EmbeddingExtractor` removal or Stage-5-only disposition.
2. **S2b.2 — domain/persistence/reconciler:** aggregate, migration, placeholder-table replacement, preferred identity/supersession/rollback, first-claim deadline/retry taxonomy.
3. **S2b.3 — independent role/lifecycle HTTP:** role activation, READY/operator signal, lease/heartbeat/fail/reclaim/sweep.
4. **S2b.4 — evidence transport:** authorised streaming, bounded retries, permanent-vs-transient split.
5. **S2b.5 — upload/staging/janitor:** dedicated namespace, streaming hash/caps, replay, cleanup races.
6. **S2b.6 — seal/publication:** three-phase ADR-006 protocol with mandatory Phase-C re-fence, crash/replay tests, completion-budget measurement; Finalizing if required.
7. **S2b.7 — fixture end-to-end:** real process/contracts only; Observed/Unknown/Unavailable; Production refusal.
8. **S2b.8 — bounds/reconciliation:** 10k worst-shape tests, mutation tests, ADR-013 serializer wording correction, docs/register evidence, cold review.

Each sub-slice leaves repository green.

## 18. Mutation/discriminating targets

Kill mutations that: omit attempt fencing; accept expired lease on ordinary lease-scoped operations; check expiry before committed replay; **omit the Phase-C re-fence or re-check only status but not attempt/capability hash**; permit foreign Observation/run; skip size/SHA verification; map transient transport failure to Unavailable; decode after integrity failure; remove request/upload cap; accept another attempt's upload; allow different-SHA upload replay; publish DB rows before successful publication transaction; delete sealed accepted object on rollback; supersede by completion order; fail to re-derive default on binding rollback; supersede on failed replacement; consume attempt when startup capability unavailable; anchor deadline at queue creation; remove deadline sweep/exhaustion; treat Unknown as Absent; permit Observed without supporting Observation; include runtime/device/commit in semantic identity; duplicate `(run, identity)` units; echo/persist token; use VisionJob janitor authority for attribute staging; let fixture bypass production transport; allow Production profile to accept fixture.

## 19. Verification and completion report

Run repository-prescribed verification plus focused S2b .NET/Python suites, VisionJob/SceneAnalysis regression suites, accepted-evidence tests, migration tests, request-limit/bounds tests, worker-role/offline/component checks affected by role activation, `verify_repo`, and mutation matrix.

Implementation PR reports exact starting SHA, final exact head, changed files, migrations, lifecycle/publication decision, measured completion budget, local results, exact-head CI, review-thread state and deferred items. Do not merge from the implementation session.

## 20. Scope guard

Real attribute Model Packs/checkpoints, learned qualification, search/cursor v4, final attribute UI, RTMDet Production/CUDA state, and Component Binding identity changes are out of S2b unless a governing contradiction is first raised and resolved.

S2b is complete only when executed evidence closes D1–D8 and S2b-owned E1–E4 in the authoritative register. Planned tests are not PASS evidence.
