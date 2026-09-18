# PR #37 Engineering Acceptance Review and Stop Rule

**Status:** Normative planning-review record for PR #37 and the subsequent Task-17 implementation review.

**PR:** `hariomahlawat/MAVI#37`

**Audited planning head:** `0cdb9efcb28718cd65b3e8e29a0d42a04e382499`

**Purpose:** prevent Task 17 from becoming an unbounded reviewer-driven loop. Engineering readiness is determined by the accepted requirements, architecture and evidence; Codex is an independent reviewer, not the source of requirements and not an unlimited veto.

---

## 1. Review authority and stopping principle

A review finding is a **material merge blocker** only when engineering triage can demonstrate all of the following:

1. it applies to a supported Phase-1 deployment, qualification path or explicitly required failure case;
2. it violates an existing accepted requirement, ADR, Task-10/Task-17 contract, security property, release-integrity rule or acceptance claim;
3. the failure is reachable or the acceptance plan can falsely report success without proving the required property;
4. the impact is material to correctness, security, release provenance, supported-platform operation or formal qualification; and
5. the finding is not merely a new feature, broader product requirement, optional hardening idea or speculative future environment.

A Critical/P1/P2 label from an automated reviewer is therefore **input to triage, not automatic authority**. The repository's accepted contracts remain authoritative.

A valid hardening suggestion that does not satisfy the blocker test is recorded as follow-on work and does not keep the current PR open. A request that expands the accepted product/qualification scope requires an explicit roadmap/ADR decision rather than being silently absorbed into Task 17.

---

## 2. Six-dimension audit of PR #37

PR #37 is a planning/documentation PR. It changes the Phase-1 closeout/roadmap and defines the Task-17 acceptance plan; it does not change production code or release metadata. The audit therefore asks whether the plan is complete enough to implement Task 17 without discovering avoidable qualification ambiguity later.

### 2.1 Requirements completeness

**Assessment: NOT YET ACCEPTABLE on audited head.**

The plan is strong on evidence provenance, exact-head discipline, candidate-versus-production separation, offline installation and release promotion. However, four current exact-head review findings identify requirements already implied by accepted repository contracts but not yet stated strongly enough in the Task-17 execution plan:

- ground-truth annotations must be explicitly bound to the exact imported/scored media before evaluation;
- Windows functional qualification must exercise the real detector -> ByteTrack -> secure staging/publication worker path, not only standalone runtime inference;
- candidate and production evidence must validate the complete qualified host-compatibility contract, not only coarse OS/architecture/device variant names;
- formal CCTV-quality acceptance must include nonzero reviewed coverage and approved explicit thresholds for **both** supported Phase-1 classes, Person and Vehicle.

These are not new product features. They close proof gaps in existing qualification claims and therefore are material to the planning PR.

### 2.2 End-to-end architecture

**Assessment: ONE MATERIAL GAP.**

The plan correctly defines the complete product chain and final production topology. It also separates candidate evidence, per-variant production-bundle smoke and final topology acceptance. The remaining gap is Windows worker-path qualification. The earlier deferred Task-10 contract requires each of the four target variants to prove the detector -> ByteTrack -> Task-9 artifact path and secure staging. A Windows offline/runtime smoke that stops at startup + standalone inference is insufficient evidence for that contract.

**Required closure:** at least one Windows full worker/artifact qualification flow must execute on each required Windows device class for which the accepted Task-10 contract requires functional qualification, with exact run/artifact evidence and no substitution by the Linux production-topology worker.

### 2.3 Data provenance and integrity

**Assessment: ONE MATERIAL GAP; OTHERWISE STRONG.**

The plan already hashes controlled media, corpus manifests, ground-truth manifests, representative evidence and release identities. It independently attests the completed ProcessingRun. The missing link is a mandatory cross-check that the specific ground-truth manifest being scored names the exact same `videoSha256` and authoritative duration as the imported/scored VideoAsset/ProcessingRun media.

Without this edge, individually valid media and annotation hashes can still be paired incorrectly and produce a formally signed but meaningless score.

**Required closure:** before any metric computation, require `groundTruth.videoSha256 == streamedImportedVideoSha256 == authoritative VideoAsset content identity`; require ground-truth duration to equal the authoritative imported media duration under the documented normalization/timebase rule; require the corpus mapping to identify that exact annotation/media pair; mismatch must fail closed.

### 2.4 Platform qualification

**Assessment: ONE MATERIAL GAP.**

The plan correctly requires Windows/Linux CPU/CUDA bundles and production smokes. However, a coarse `windows-x86_64-*` or `linux-x86_64-*` match does not by itself prove that the host satisfies the bundle's qualified native-host ABI contract.

**Required closure:** qualification evidence must compare observed host compatibility against the exact `hostCompatibility` metadata carried by the selected runtime/bundle. For Linux this includes the qualified distribution/version and native ABI floors/identities represented by the bundle (for example glibc/libstdc++ compatibility where encoded). Equivalent Windows compatibility fields must be checked where present. A different host ABI requires separate qualification rather than being accepted under the same coarse variant label.

### 2.5 Quality acceptance

**Assessment: ONE MATERIAL GAP.**

The evaluator design is substantially stronger after earlier review: spatially validated one-to-one global assignment, fixed-precision deterministic tie-breaking and held-out qualification discipline are appropriate. The remaining gap is that formal mode can still be satisfied by coverage of only one supported class if the corpus/profile leave the other class empty or thresholds null.

**Required closure:** the formal `cctv-quality-baseline` gate must require nonzero reviewed ground-truth coverage for both `Person` and `Vehicle`, and the frozen qualification profile must carry explicit approved acceptance thresholds/policies for both classes. Aggregate metrics cannot substitute for a missing class. A class with zero qualification coverage keeps the gate pending/failing rather than producing a pass.

### 2.6 Failure, security and recovery behaviour

**Assessment: ACCEPTABLE FOR PLANNING, SUBJECT TO THE FOUR CLOSURES ABOVE.**

The plan already includes fail-closed handling for superseded runs, stale/failed publication, evidence/hash mismatch, missing hardware, missing gates, candidate/production identity separation, no-op formal acceptance, duplicate-object reconciliation, disconnected operation, no target compilation, no silent CUDA-to-CPU fallback and release-evidence invalidation after behaviour-bearing changes.

No additional Critical/P1/P2 planning blocker was identified in this dimension during this audit. Implementation will still require negative-path tests and evidence as specified by the Task-17 plan.

---

## 3. Disposition of current exact-head Codex findings

At audited head `0cdb9efcb28718cd65b3e8e29a0d42a04e382499`, the four unresolved P1 findings are triaged as follows:

| Finding | Triage | Reason |
| --- | --- | --- |
| Bind annotations to processed media before scoring | **Material blocker** | Missing cross-proof can score valid annotations against the wrong valid video and falsely pass quality acceptance. |
| Exercise Windows worker artifact path | **Material blocker** | Existing deferred Task-10 qualification contract explicitly requires detector -> ByteTrack -> artifact path + secure staging on all four target variants. |
| Validate full host compatibility contract | **Material blocker** | Coarse variant matching can approve an unsupported distro/native ABI while bundle metadata defines a narrower qualified host contract. |
| Require quality coverage for both supported classes | **Material blocker** | Phase-1 supports Person and Vehicle; one-class evidence cannot truthfully qualify both. |

This classification is based on repository requirements, not the reviewer-provided P1 label.

---

## 4. Engineering stop rule for PR #37

PR #37 may be merged when **all** of the following are true on one frozen exact head:

1. the four material planning gaps in Section 3 are explicitly closed in the authoritative Task-17 plan/runbook contracts;
2. the six-dimension audit has no remaining internally identified Critical/P1/P2-equivalent defect;
3. every required exact-head workflow is completed successfully;
4. the PR remains cleanly mergeable;
5. there are zero unresolved **material** review threads;
6. documentation/source-of-truth references are internally consistent;
7. one final broad review is performed against that frozen head; and
8. every new finding from that review is triaged using Section 1 rather than accepted mechanically by severity label.

If the final broad review produces **no new material blocker**, PR #37 is accepted and merged. Optional hardening and speculative scope are moved to backlog/follow-on records and do not trigger another open-ended review cycle.

A review is repeated only when the head changes in a way that affects the reviewed plan or when a credible material defect is identified. Re-running independent review repeatedly against an unchanged accepted head merely to seek additional comments is not a completion requirement.

---

## 5. Engineering stop rule for Task-17 implementation

The implementation PR is ready to stop when the accepted Task-17 Definition of Done is demonstrated on the frozen exact head and all of the following hold:

- requirements are traceable to implementation/tests/evidence;
- end-to-end success and required failure/recovery paths are exercised;
- provenance and release identities are independently attested and fail closed on mismatch;
- every required platform/device/host-compatibility contract is qualified with the required evidence;
- formal quality evidence covers both Person and Vehicle under approved thresholds;
- all mandatory qualification gates are truthfully passed or the release remains explicitly pending;
- all exact-head required workflows are green;
- mergeability is clean;
- no unresolved material review thread remains;
- one final broad independent review of the frozen head yields no new material blocker under Section 1.

After those conditions are met, additional reviewer suggestions are handled as follows:

- **Merge blocker:** fix only if it satisfies the Section-1 materiality test; affected evidence is invalidated and rerun as required.
- **Hardening:** record as follow-on work; do not reopen acceptance unless it exposes a genuine requirement violation.
- **Scope expansion:** requires a new task/ADR/roadmap decision; do not absorb it into Task 17 by default.

This is the deliberate stopping boundary. "A reviewer can imagine one more test" is not itself evidence that the release is unready.

---

## 6. Review governance after freeze

Once the implementation/plan is frozen for final review:

1. do the internal six-dimension audit first;
2. correct all internally found material defects before requesting Codex;
3. request one broad Critical/P1/P2 review on the frozen exact head;
4. triage each result against accepted repository contracts;
5. fix genuine blockers together, adding regression/qualification coverage;
6. after a behaviour-bearing fix, rerun only the evidence/gates made stale by that fix plus the required full exact-head gate set;
7. perform a final broad review on the resulting frozen head;
8. if no new material blocker remains, stop and merge using expected-head protection.

The objective is **engineering closure**, not reviewer exhaustion.
