# Stage 2 S2b — implementation record

- **Plan:** `docs/superpowers/plans/2026-09-28-stage2-s2b-attribute-lifecycle.md` (merged in PR #113)
- **Starting baseline:** `main@ad01c2b181bc3ca8f45338ab706be870758c4c79` (merge of PR #113; no intervening commits)
- **Branch:** `feature/stage2-s2b-attribute-lifecycle`
- **Governing:** ADR-006, ADR-009, ADR-011, ADR-013 (amended in this slice, §3 below), ADR-014, the Stage-2 acceptance register

This is the running record for the slice. It states what was reused, what was extracted and what is new, the decisions made where the plan left an implementation choice, and the evidence produced. It is not an acceptance register: D1–D8 and E1–E4 status lives only in `docs/reviews/2026-09-23-visual-attributes-acceptance.md`.

## 1. Baseline reconciliation (plan §3)

| Requirement | Existing primitive | Decision |
|---|---|---|
| Lease capability: 32 random bytes, Base64Url, SHA-256 at rest, constant-time match | `ILeaseCapabilityService` / `LeaseCapabilityService` (VisionJob) | **Reuse unchanged.** It is already a shared service; the attribute plane is its second consumer, not a third copy. SceneAnalysis keeps its in-process raw-byte token: it is never on the wire and its ownership semantics differ (ADR-011 D4). |
| Canonical lower-case SHA-256 validation | about nine private copies (`VisionJob`, `SceneAnalysis`, `Artifact`, `AcceptedEvidenceStore`, validators …) | **Extract narrowly** to `Mavi.Domain.Common.CanonicalSha256`; the new aggregate and the domain types that already duplicate it use the one rule. Regression suites of VisionJob, SceneAnalysis and Artifact prove behaviour is unchanged. Contract-layer copies stay (Contracts has no Domain reference by design). |
| `FOR UPDATE SKIP LOCKED` claim | three hand-written claim queries | **Not genericised** (plan §6). Eligibility, reclaim and exhaustion differ per plane; the attribute plane writes its own claim with its own identity fence. |
| Completion digest | `VisionResultValidator.ComputeDigest` (frozen v2/v3/v3.2 domains) | **Not shared.** A shared writer would put frozen digest vectors at risk for no semantic gain. The attribute digest has its own domain tag `mavi:visual-attribute-completion-digest:v1`. |
| Accepted-evidence read | `IAcceptedEvidenceReader` (path-safe, handle-verified, no size bound, no hash) | **Reuse.** The endpoint adds the size check before headers and the lease/IDOR authorisation. |
| Sealing | `IAcceptedEvidenceStore.SealAsync` (streamed copy, fsync, create-once, adopt-if-identical) | **Reuse unchanged** for Phase B. The accepted key is content-addressed and not attempt-scoped (plan §12). |
| Staging | worker-written `staging/{job}/attempt-NNNN`; `StagingJanitor` authoritative on `vision_jobs` | **New platform-owned namespace** `staging-attributes/{analysisId}/attempt-NNNN/` under `MediaStorage:RootPath`, outside the directory the VisionJob janitor scans; a separate janitor authoritative on `visual_attribute_analyses`, reusing the handle-relative `StagingDirectory` deletion primitive. |
| Visibility barrier / sequence | `ProcessingVisibilityBarrier` (shared advisory lock and `processing_visibility_sequence`) | **Reuse.** Rows are written before the exclusive lock; the lock is held only for sequence allocation, completion and supersession. |
| Placeholder `VisualAttribute` entity / `visual_attributes` table | per-row model name/version, nullable `ObservationId` with SetNull, no `AnalysisId`; nothing reads or writes it | **Replaced** by the ADR-013 §14 shape in the S2b migration (table dropped and recreated; it has never held data written by any code path). |
| `EmbeddingExtractor` Protocol | declared, zero usages | **Removed** in S2b.1 (plan §3). Stage 5 designs its own contract; S2b's inferencer abstraction is attribute-specific. |
| Worker HTTP client | `WorkerApiClient` is VisionJob-shaped (routes, completion versions, video lease) | **New client** `mavi_vision.attributes.client` for the attribute plane; `LeaseGuard` is reused. |
| Role registry / resolver | `IMPLEMENTED_ROLE_ENTRY_POINTS = {vision}`, `IMPLEMENTED_CAPABILITIES = {detector}`, detector-only pipeline profile loading | **Extended in place:** the `attributes` role entry point `mavi_vision.attributes.main`, the attribute capability ids, the attribute pipeline profile loader and the attribute provenance contract are registered; the resolver dispatches pipeline-profile loading by role kind. No second composition path. |
| Shipped Component Binding (`phase1-bindings-v2.json`) | vision role only | **Unchanged** (plan §20: no Component Binding identity change). The fixture is bound only in Development/test overlays. |

No contradiction with a governing decision was found that required stopping. One mechanism the ADRs require but do not name — how the platform learns the preferred identity — is decided in §3 and recorded as an ADR-013 implementation amendment.

## 2. Plan items that are implementation choices

Recorded here as they are made; each is a P3-level choice inside the plan's decided semantics.

1. **Wire contract version** `mavi-visual-attribute-control-v1` for lease/heartbeat/fail/complete; the prediction artefact schema is `mavi-attribute-predictions-v1`.
2. **Routes** (all under `/api/attributes/analyses`): `POST /lease`, `POST /{id}/heartbeat`, `GET /{id}/evidence/{observationId}`, `PUT /{id}/predictions`, `POST /{id}/complete`, `POST /{id}/fail`.
3. **Header-only capability:** request header `X-Mavi-Lease-Capability`; the lease response returns the new capability in the same response header and never in a JSON body. Attempt and worker travel in the JSON envelope for POSTs and in `X-Mavi-Attempt` / `X-Mavi-Worker-Id` for the GET and the PUT. A JSON property named `leaseToken` is rejected.
4. **Encoding:** canonical UTF-8 JSON (sorted keys, no insignificant whitespace, no NaN), trailing LF. The platform never re-serialises: it hashes the bytes received and validates structurally with a streaming reader.
5. **Authoritative evidence failures** are HTTP 422 with `visual_attribute_evidence_missing` or `visual_attribute_evidence_integrity_failed`; everything else the worker cannot complete (resets, timeouts, 5xx, truncated bodies) is transport failure.

## 3. Platform source of the preferred identity (ADR-013 implementation amendment)

ADR-013 §9 fixes the identity at queue time from "the enabled capability bindings" and the plan makes "the currently enabled Component Binding" the authority for the default. The platform has never read the binding: until now it learned component identity only from completions. S2b therefore gives the platform a read-only view of the same release overlay the worker composes from:

- `VisualAttributes:ComponentBindingPath` — the release Component Binding (the file whose SHA is `componentBindingSha256`);
- `VisualAttributes:PipelineProfilePath` — the attribute pipeline profile (schema, aggregation policy, parameters, each pinned by SHA-256).

The platform derives the identity tuple and its fingerprint from exactly those bytes, with the same canonical derivation as the worker (cross-language test vector). Neither configured → readiness `NotConfigured` and nothing is queued; the shipped release configures neither. The worker presents its own resolved fingerprint on every lease request and the claim query is fenced on it, so a worker composed from a different binding can never take ownership of — or consume an attempt of — a unit it cannot reproduce (the SceneAnalysis engine-fence pattern).

**Trade-off accepted:** the platform now parses a narrow, fail-closed subset of the binding and the attribute pipeline profile. The alternative — a second, platform-local declaration of the identity — would create two authorities that can drift silently; the lease fence would catch the drift but only as permanently Pending work.

## 4. Numeric bounds

Derived and pinned in `VisualAttributeContractRules`; the derivations and the cap / cap+1 tests are recorded in §6 as they are produced.

## 5. Evidence produced

Filled in as each sub-slice lands (commands, SHAs, results).

## 6. Mutation matrix

Filled in at S2b.8.
