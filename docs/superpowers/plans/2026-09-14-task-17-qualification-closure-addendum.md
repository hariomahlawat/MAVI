# Task 17 — Qualification Closure Addendum

**Status:** Normative addendum to `2026-09-14-task-17-phase1-hardening-qualification-acceptance.md`.

This addendum closes four qualification-proof gaps identified during the PR #37 six-dimension engineering audit. Where this addendum is stricter or more explicit than the earlier Task-17 planning text, this addendum controls. It does not expand Phase-1 product functionality; it makes existing qualification claims provable.

---

## A. Ground truth must be bound to the exact processed media

Before any formal metric is calculated, the acceptance harness/evaluator shall establish one immutable media identity across import, processing and annotation.

For each scored case it shall require:

1. the locally controlled MP4 SHA-256 computed before import;
2. the full streamed authoritative imported VideoAsset content SHA-256;
3. the strong ETag digest returned for that authoritative content;
4. the ground-truth manifest `videoSha256`; and
5. the corpus-manifest mapping for that case

all to identify the **same exact media bytes**.

The evaluator shall additionally require the ground-truth `durationMs` to equal the authoritative imported-media duration under the documented canonical duration/timebase rule. Any tolerated container/timebase normalization must be explicit, deterministic and covered by tests; it must not be an ad-hoc numeric tolerance.

The metric path shall fail closed before matching/scoring if any of the following is true:

- ground-truth `videoSha256` differs from the streamed imported-video SHA-256;
- the authoritative content ETag differs from those bytes;
- the corpus case maps the annotation to another media SHA-256;
- the authoritative duration is inconsistent with the annotation manifest;
- the scored ProcessingRun does not belong to that exact VideoAsset.

Formal evidence shall retain the VideoAsset ID, ProcessingRun ID, media SHA-256, authoritative duration, corpus-manifest SHA-256, ground-truth-manifest SHA-256 and the exact corpus mapping used for the score.

Required regression coverage includes a valid-video-A + valid-ground-truth-for-video-B case that must fail before evaluation.

---

## B. Windows functional qualification must exercise the real worker/artifact path

The accepted deferred Task-10 requirement remains authoritative: all four target variants are functionally qualified, not merely import/runtime-smoked:

- `windows-x86_64-cpu`;
- `windows-x86_64-cuda`;
- `linux-x86_64-cpu`;
- `linux-x86_64-cuda`.

For each variant, qualification shall prove the applicable end-to-end vision-worker contract on a controlled MP4:

`exact qualified runtime -> RTMDet -> class mapping -> class-separated ByteTrack -> Task-9 processing/result contract -> attempt-scoped secure staging -> authoritative artifact publication/completion`

For Windows CPU and Windows CUDA specifically, standalone model inference, `pip check`, runtime startup or bundle installation is **not sufficient** to satisfy the functional platform qualification. At least one controlled real worker run per required Windows device variant shall:

- lease/execute the exact queued ProcessingRun;
- run detector and ByteTrack under the expected device policy;
- produce the expected processing result contract;
- exercise native-Windows secure attempt-scoped staging/publication;
- complete through the authoritative API/persistence boundary;
- resolve at least one published representative artifact when the controlled case contains a target;
- retain exact run/runtime/bundle/platform/device/artifact identities in evidence;
- prove no silent CUDA-to-CPU fallback for the CUDA case.

The final production-topology acceptance may continue to use the qualified Linux NVIDIA worker. That topology choice does not waive the separate Windows functional-qualification obligation.

If a future product decision removes Windows worker execution as a supported/qualified target, that change requires an explicit accepted ADR and corresponding qualification-schema/roadmap update; it is not a Task-17 shortcut.

---

## C. Host compatibility must match the complete qualified contract

A coarse platform variant such as `linux-x86_64-cuda` or `windows-x86_64-cpu` is necessary but not sufficient evidence that a bundle is running on a supported host.

Every candidate and production disconnected install/runtime evidence package shall compare the **observed host** against the exact `hostCompatibility` contract carried by the selected runtime/bundle metadata.

The verification shall include every compatibility field encoded for that variant. For Linux, where present, this includes at minimum:

- distribution identity;
- distribution/version release;
- machine/architecture;
- glibc identity/version or minimum;
- libstdc++/`GLIBCXX` compatibility requirement;
- exact CPython identity already required by runtime metadata;
- any other native ABI floor explicitly frozen into `hostCompatibility`.

For Windows, verify the corresponding OS/release/architecture/native-runtime compatibility fields that are present in the frozen metadata, together with the exact CPython identity.

Rules:

- observed values shall be captured from the actual qualification host, not copied from expected metadata;
- comparison semantics shall be deterministic and versioned;
- a host outside the frozen compatibility contract fails qualification even when the coarse platform/device label matches;
- qualification on a materially different distribution/native ABI requires a separately qualified host compatibility entry/bundle rather than implicit widening of the existing one;
- evidence shall retain both expected and observed compatibility identities plus the selected bundle/lock hash.

Required regression coverage includes a same-architecture Linux host with mismatched distribution/native ABI that must fail compatibility validation.

---

## D. Formal quality qualification must cover both supported classes

The Phase-1 supported analytical classes are `Person` and `Vehicle`. A formal `cctv-quality-baseline` pass shall therefore qualify both classes independently.

Before the quality gate can pass:

1. the frozen held-out qualification corpus shall contain **nonzero reviewed ground-truth events for Person**;
2. the frozen held-out qualification corpus shall contain **nonzero reviewed ground-truth events for Vehicle**;
3. each class shall have explicit approved qualification policy/threshold values in the frozen acceptance profile;
4. per-class raw counts and required precision/recall/F1 (and any other approved class-level metric) shall be evaluated independently;
5. aggregate metrics shall be reported for observability but shall never substitute for a missing or failing class;
6. a null/undefined metric caused by zero required-class coverage is a qualification failure/pending condition, not a pass;
7. the evidence package shall record reviewed ground-truth count and threshold/result for each required class.

The baseline/measurement mode may still run with incomplete class coverage for development diagnostics, but such a run is explicitly non-qualifying.

Required regression coverage includes:

- Person-only corpus -> formal gate cannot pass;
- Vehicle-only corpus -> formal gate cannot pass;
- both classes present but one threshold missing -> formal gate cannot pass;
- both classes present but one fails its approved threshold -> formal gate cannot pass;
- both classes present and both satisfy approved thresholds -> gate may proceed subject to all other qualification requirements.

---

## E. Definition-of-done amendment

Task 17 cannot be declared fully complete unless, in addition to the main plan's existing Definition of Done:

- every scored annotation set is cryptographically/semantically bound to the exact processed media and authoritative duration before scoring;
- Windows CPU and CUDA functional qualification exercise the real worker -> detector -> ByteTrack -> secure native-Windows staging/publication path required by the accepted Task-10 contract;
- every candidate and production qualification host satisfies the complete frozen host-compatibility/native-ABI contract for its selected bundle;
- formal CCTV-quality evidence contains nonzero reviewed coverage and approved passing policy for both Person and Vehicle.

These are acceptance-proof requirements. They must not be weakened to make unavailable evidence appear complete.

---

## F. Review closure rule

The engineering acceptance and stopping rule is recorded in:

`docs/superpowers/plans/2026-09-14-pr37-engineering-acceptance-review.md`

After these four proof gaps are implemented in the authoritative Task-17 contracts, PR #37 shall undergo one final broad exact-head review. New comments are triaged against accepted requirements; only genuine material blockers keep the PR open. Optional hardening or scope expansion is recorded separately rather than extending the review indefinitely.
