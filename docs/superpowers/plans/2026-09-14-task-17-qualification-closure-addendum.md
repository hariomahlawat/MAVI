# Task 17 — Qualification Closure Addendum

**Status:** Normative addendum to `2026-09-14-task-17-phase1-hardening-qualification-acceptance.md`.

This addendum closes seven qualification-proof gaps identified during the PR #37 internal/final-review cycle. Where this addendum is stricter or more explicit than the earlier Task-17 planning text, this addendum controls. It does not expand Phase-1 product functionality; it makes existing qualification claims provable.

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

## E. Fresh offline installation and offline update are separate mandatory proofs

ADR-003 requires **both** offline installation and offline update procedures to be testable. They are separate acceptance claims: evidence for a clean installation shall never substitute for evidence that an existing supported deployment can be updated offline, and update evidence shall never substitute for a clean-install proof.

### E.1 Fresh offline installation

The final disconnected acceptance shall:

1. receive the versioned accepted MAVI application artifact through controlled offline media and retain its SHA-256;
2. begin from a clean/reprovisioned production-representative Windows/IIS application plane with outbound Internet unavailable and no accepted MAVI application already installed;
3. install those exact artifact bytes using only controlled offline media;
4. retain installation mechanism/tool version, commands/configuration, exit result and destination identity;
5. start Mavi.Api only after installation;
6. independently observe the running application build/commit identity and require it to match the accepted artifact/release identity;
7. prove the API and deployed React/static assets operate without remote dependencies.

A pre-existing deployment, copied working directory or already-running accepted build cannot satisfy this proof.

### E.2 Offline update from a supported prior release

A separate acceptance case shall:

1. provision an **explicitly supported prior MAVI release** using its retained immutable release/application identity;
2. establish representative pre-update configuration and authoritative database state sufficient to exercise the supported migration/update path;
3. record the prior release identity/hash and pre-update state/evidence needed for post-update comparison;
4. transfer the accepted target application artifact through controlled offline media and verify its SHA-256;
5. execute the supported offline update procedure with outbound Internet unavailable;
6. execute and retain the result of every applicable application, configuration and database migration;
7. independently observe the running target build/commit identity and require it to match the accepted target artifact;
8. verify representative pre-update authoritative data/configuration survives or is deterministically migrated as specified;
9. prove post-update API/UI/health/search/evidence operation without Internet connectivity.

The update proof fails if the starting release is outside the declared supported-update range, any required migration is skipped or fails, retained authoritative state is lost/corrupted/incompatible, different target bytes are used, hidden online dependencies are required, or the running target build cannot be bound to the accepted artifact.

### E.3 Evidence and negative coverage

Fresh-install and update evidence shall be retained as **distinct immutable hashed evidence objects** and both must be referenced by the final Phase-1 acceptance record.

Required negative coverage includes:

- valid target artifact hash + old pre-existing IIS deployment presented as a fresh install -> **cannot pass**;
- fresh install succeeds but no update case exists -> **cannot pass**;
- update from an unsupported/unknown prior release -> **cannot pass**;
- update skips or fails an applicable migration -> **cannot pass**;
- post-update running build or retained authoritative state does not match the expected target/migration result -> **cannot pass**.

---

## F. Offline backup and restore must be exercised before Phase-1 acceptance

ADR-003 also requires backup and restore procedures to be testable. Reprocessing a failed vision run is not a substitute for disaster-recovery proof.

After a successful controlled acceptance case has produced authoritative state, the final disconnected acceptance shall execute an offline backup and clean-target restore using only local/approved network storage.

The backup set shall cover, at minimum, every authoritative store required to reconstruct the accepted case:

- PostgreSQL/pgvector authoritative database state;
- managed source-video storage;
- platform-owned accepted evidence/artifact storage;
- any required local configuration/metadata whose loss would make the retained authoritative rows or artifacts unusable, excluding secrets that must be reprovisioned through the approved security process.

Backup evidence shall record exact tool/version identities, commands/configuration, source identities, backup-set file manifest, byte sizes and SHA-256 hashes. Restore shall occur into a clean/reprovisioned target rather than over the still-working source deployment.

After restore, acceptance shall independently revalidate:

- Camera, VideoAsset, ProcessingRun, Track and Artifact IDs and required relationships;
- managed source bytes by full SHA-256 + strong ETag against the pre-backup accepted media identity;
- representative evidence bytes by SHA-256 + strong ETag;
- Track search and Track detail for the retained accepted run;
- completed-run attestation/release provenance;
- API/UI/search/evidence-retrieval operation without Internet connectivity.

The proof fails if any authoritative store is omitted, required IDs/relationships are lost, restored bytes differ, search/evidence bindings break, restore depends on Internet access/unrecorded external state, or the post-restore product smoke cannot operate from restored state.

Required negative coverage includes an intentionally incomplete backup-set manifest (for example DB-only without managed media/evidence), which must be rejected before a restore can be accepted.

---

## G. Definition-of-done amendment

Task 17 cannot be declared fully complete unless, in addition to the main plan's existing Definition of Done:

- every scored annotation set is cryptographically/semantically bound to the exact processed media and authoritative duration before scoring;
- Windows CPU and CUDA functional qualification exercise the real worker -> detector -> ByteTrack -> secure native-Windows staging/publication path required by the accepted Task-10 contract;
- every candidate and production qualification host satisfies the complete frozen host-compatibility/native-ABI contract for its selected bundle;
- formal CCTV-quality evidence contains nonzero reviewed coverage and approved passing policy for both Person and Vehicle;
- a fresh offline installation of the exact hashed MAVI application artifact is executed on a clean/reprovisioned Windows/IIS plane and the running build identity matches it;
- a separate offline update from an explicitly supported prior MAVI release is executed with all applicable migrations and retained-state/post-update validation;
- offline backup and clean-target restore of PostgreSQL plus all required managed media/evidence stores is executed and post-restore integrity/functionality is revalidated.

These are acceptance-proof requirements. They must not be weakened to make unavailable evidence appear complete.

---

## H. Review closure rule

The engineering acceptance and stopping rule is recorded in:

`docs/superpowers/plans/2026-09-14-pr37-engineering-acceptance-review.md`

After these seven proof gaps are implemented in the authoritative Task-17 contracts, PR #37 shall undergo one final broad exact-head review. New comments are triaged against accepted requirements; only genuine material blockers keep the PR open. Optional hardening or scope expansion is recorded separately rather than extending the review indefinitely.
