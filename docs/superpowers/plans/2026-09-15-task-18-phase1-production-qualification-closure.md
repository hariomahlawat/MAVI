# Task 18 — Phase-1 Production Qualification and Closure

**Status:** Authoritative operational qualification and Phase-1 closure plan.

**Planning baseline:** Task 17 implementation merged by PR #38. Accepted implementation head `b1b1595d99cbf2d4f85a20229dd95cf4188c3bac`; resulting integration merge commit `57f9efd5090f01486ff8a197c6a4aaeda285d065`.

**Primary objective:** execute the already-implemented Task-17 qualification framework on production-representative disconnected hosts, generate the mandatory immutable evidence, promote release metadata only after every mandatory gate passes, qualify the exact production bundles, and issue the final Phase-1 acceptance decision.

Task 18 is an **operational qualification and closure task**. It is not a feature-development task and shall not expand Phase-1 analytical scope.

---

## 1. Re-baselining decision

Task 17 completed the software implementation, deterministic acceptance tooling, schemas, runbooks, evidence verifiers and fail-closed promotion machinery. PR #38 was merged only after:

- Task 17 Acceptance Validation passed;
- MAVI Quality Gate passed;
- Task 12 Offline Bundle passed;
- all prior material Codex findings were remediated;
- final focused internal Critical/P1/P2 review was clean;
- the exact accepted implementation head was frozen.

The remaining work is materially different from implementation: it requires real Windows/Linux hosts, CUDA hardware, disconnected execution, controlled private qualification media, operational PostgreSQL/storage topology and retained evidence.

The roadmap is therefore explicitly re-baselined:

- **Task 17 — implementation complete;**
- **Task 18 — production qualification and Phase-1 closure active.**

This re-baselining preserves the Task-17 rule that evidence-pending implementation must not be mislabeled as a production-qualified release.

---

## 2. Scope and exclusions

Task 18 shall prove the final Phase-1 system on production-representative infrastructure.

### 2.1 In scope

1. freeze the exact qualification candidate identities;
2. inventory and validate qualification hosts;
3. execute Windows CPU and CUDA qualification;
4. execute Linux CPU and CUDA qualification;
5. execute disconnected Windows and Linux offline-install qualification;
6. execute formal Person/Vehicle CCTV-quality qualification;
7. execute Linux NVIDIA recovery/performance qualification;
8. execute clean fresh-install proof on the Windows/IIS operational plane;
9. execute offline update from an explicitly supported prior release;
10. execute formal production-topology E2E acceptance;
11. execute controlled failure/reprocess acceptance;
12. execute offline backup and clean-target restore;
13. independently validate all generated evidence;
14. promote release metadata only after mandatory candidate evidence is complete;
15. build exact production bundles;
16. execute disconnected production-mode smoke for every required production bundle;
17. execute final full production-topology acceptance after promotion;
18. issue a machine-readable and human-readable Phase-1 closure decision.

### 2.2 Out of scope

No Task-18 activity shall add or redesign:

- face recognition;
- cross-camera ReID;
- ANPR;
- embeddings/vector retrieval;
- trajectory visualization;
- VLM/LLM search;
- additional object classes;
- a new detector/tracker architecture;
- a new datastore;
- cloud dependencies;
- online runtime/package/model resolution;
- a new authentication architecture;
- arbitrary threshold tuning against the final held-out qualification corpus.

If qualification reveals a genuine product defect, Task 18 shall stop the affected evidence chain and open a focused remediation change. Qualification shall never hide, waive or tune around a functional defect.

---

## 3. Governing documents

Task 18 executes, rather than replaces, the accepted Task-17 qualification contracts.

Normative inputs are:

- `docs/superpowers/plans/2026-09-14-task-17-phase1-hardening-qualification-acceptance.md`;
- `docs/superpowers/plans/2026-09-14-task-17-qualification-closure-addendum.md`;
- `docs/runbooks/phase1-acceptance.md`;
- current acceptance/evidence schemas under `tools/phase1/`;
- current model/runtime/qualification metadata;
- current production prerequisite and supported-update policies;
- the accepted architecture decisions under `docs/decisions/`.

Where this Task-18 plan specifies execution order, evidence custody, stopping rules or final closure semantics more explicitly, Task 18 controls the operational sequence. It does not weaken any Task-17 proof requirement.

---

## 4. Accepted software baseline and freeze rule

The initial Task-18 software baseline is the Task-17 merge result:

`57f9efd5090f01486ff8a197c6a4aaeda285d065`

The exact implementation accepted inside PR #38 was:

`b1b1595d99cbf2d4f85a20229dd95cf4188c3bac`

Before any evidence-producing qualification begins:

1. confirm the integration branch still contains the Task-17 merge without unreviewed functional changes;
2. record the exact qualification source commit;
3. run the complete deterministic repository gate set;
4. compute and retain hashes for behavior-bearing manifests/profiles/policies;
5. freeze the private qualification corpus and ground-truth manifests by SHA-256;
6. freeze the candidate application artifact identity;
7. freeze the selected runtime/platform inputs applicable to the qualification stage.

### 4.1 Evidence invalidation rule

Any change to a behavior-bearing item invalidates all dependent downstream evidence.

Examples include:

- application code;
- API/UI/worker code;
- model manifest;
- checkpoint/config identity;
- pipeline profile;
- runtime profile;
- platform lock;
- acceptance profile;
- quality thresholds;
- qualification corpus or annotations;
- production prerequisite policy;
- supported-update policy;
- application artifact bytes.

A documentation-only correction that cannot affect behavior or the interpretation of evidence may be handled separately, but its non-behavioral nature must be explicitly recorded.

---

## 5. Qualification topology

The final production-representative topology shall use:

### Windows operational plane

- supported Windows Server host;
- IIS;
- accepted MAVI web/API application artifact;
- no production Internet dependency;
- stable operational host identity;
- configured managed-media and accepted-evidence roots.

### PostgreSQL plane

- approved PostgreSQL + pgvector deployment;
- explicit production prerequisite identity;
- controlled source and restore service identities;
- backup/restore tooling available offline.

### Linux vision plane

- supported Ubuntu/Linux host;
- NVIDIA GPU and driver matching the frozen compatibility contract;
- qualified CUDA runtime;
- exact Python/runtime bundle;
- no silent CPU fallback;
- outbound Internet unavailable during disconnected qualification.

The same physical machine may satisfy more than one role only where the accepted production prerequisite policy permits it. Evidence shall still retain role-specific topology identities.

---

## 6. Controlled evidence workspace

Qualification evidence shall not be committed indiscriminately to Git.

Create an approved evidence root outside the repository with at least:

```text
phase1-qualification/
  00-freeze/
  01-prerequisites/
  02-platform-qualification/
  03-offline-install/
  04-quality/
  05-recovery-performance/
  06-application-lifecycle/
  07-production-scenarios/
  08-backup-restore/
  09-promotion/
  10-production-bundles/
  11-final-acceptance/
  12-closure/
```

Every retained evidence file shall have:

- deterministic filename;
- SHA-256;
- capture timestamp where the schema permits/needs time;
- source commit;
- build identity;
- acceptance execution/context identity where applicable;
- originating host/role identity where applicable.

Private CCTV clips, private annotations, secrets, credentials and operational connection strings remain outside Git.

A final evidence manifest shall enumerate every retained evidence object and SHA-256.

---

## 7. Task-18 execution states

Task 18 shall use explicit states.

### T18-0 — Planned

Plan accepted; no evidence-producing qualification started.

### T18-1 — Candidate frozen

Source, application artifact, policy/profile/corpus inputs and initial host prerequisites frozen.

### T18-2 — Hardware/runtime qualified

All required platform/device runtime qualification is complete and immutable locks/platform identities exist.

### T18-3 — Candidate evidence complete

All mandatory pre-promotion candidate evidence is present and independently validated.

### T18-4 — Release promoted

Runtime/model/qualification metadata has been promoted only through the accepted deterministic promotion tooling.

### T18-5 — Production bundles qualified

Every exact production bundle has passed its required disconnected production-mode smoke.

### T18-6 — Production topology accepted

Full disconnected production-topology acceptance, lifecycle proof and backup/restore proof are complete.

### T18-7 — Phase-1 closed

All mandatory evidence has been independently revalidated and final closure status is `release-verified`.

A failed or pending mandatory gate prevents progression to any state that claims the missing proof.

---

## 8. Pre-qualification readiness review

Before the first hardware qualification run, complete one readiness review.

### 8.1 Repository readiness

Require:

- clean integration baseline;
- complete deterministic CI green;
- `python tools/verify_repo.py` green;
- Task-17 tooling tests green;
- .NET build/tests green;
- Python tests green;
- frontend tests/typecheck/build green;
- no unresolved material PR review findings affecting the frozen baseline.

### 8.2 Qualification inputs

Record exact hashes for:

- source commit;
- model manifest;
- checkpoint and resolved config;
- pipeline profile;
- runtime profile;
- pending qualification record;
- acceptance profile;
- qualification corpus manifest;
- each ground-truth manifest;
- production prerequisite policy;
- supported-update policy;
- application artifact manifest;
- candidate bundle inputs already available.

### 8.3 Host readiness

For each role, record:

- hostname/host identity hash;
- OS/distribution/version;
- architecture;
- Python identity where applicable;
- .NET/IIS versions where applicable;
- PostgreSQL/pgvector versions;
- NVIDIA driver/CUDA runtime where applicable;
- storage-root identities;
- database topology identity hash;
- available disk capacity;
- system time synchronization status;
- offline media transfer mechanism.

Any mismatch against a frozen prerequisite or host-compatibility contract is a **readiness failure**, not a qualification waiver.

---

## 9. Rehearsal before authoritative evidence

Perform one non-authoritative rehearsal using production-representative hosts and the same runbook.

The rehearsal may validate:

- command syntax;
- paths;
- permissions;
- IIS deployment mechanics;
- PostgreSQL service aliases;
- CUDA visibility;
- offline wheelhouse/bundle access;
- media/evidence root access;
- log locations;
- evidence transfer process;
- backup/restore command availability.

Rehearsal evidence shall be clearly labeled **NON-AUTHORITATIVE / REHEARSAL** and shall never be supplied to release promotion.

### Rehearsal stopping rule

If rehearsal exposes a functional defect, correct it through normal reviewed development, merge the fix, establish a new frozen baseline and restart all affected qualification sequencing.

Do not patch production hosts manually in a way that cannot be reproduced from repository-controlled artifacts.

---

## 10. Checkpoint A — platform and hardware qualification

Execute the four supported runtime variants against real controlled worker flow where required:

1. Windows x86_64 CPU;
2. Windows x86_64 CUDA;
3. Linux x86_64 CPU;
4. Linux x86_64 CUDA.

For each variant require:

- exact selected candidate bundle;
- exact source commit;
- exact target verified-manifest identity;
- exact acceptance-profile identity;
- host compatibility observed from the real host;
- `pip check`;
- runtime start;
- real inference;
- real worker-flow execution;
- expected device equality;
- no first-run downloads;
- outbound network unavailable for disconnected runs;
- CUDA variants prove actual `cuda:<device>`, never CPU fallback;
- evidence output validates against the canonical schema.

Windows CPU/CUDA must exercise the real native-Windows worker/artifact publication path required by the Task-17 closure addendum.

### Checkpoint A exit criteria

All four variant evidence objects are valid and the final runtime/platform identities required to construct the qualified runtime profile are immutable.

If any required CUDA hardware is unavailable or fails, Task 18 remains pending and release promotion is prohibited.

---

## 11. Checkpoint B — final runtime construction and candidate rebind

Once immutable platform/lock identities exist:

1. construct the final runtime profile;
2. set runtime qualification state only as allowed by verified platform evidence;
3. compute the exact runtime-profile SHA-256;
4. rebind the still-pending qualification record to the final runtime/profile/manifests;
5. keep unevidenced model/release gates pending;
6. verify the internally consistent unverified release selection;
7. build deterministic qualification-candidate bundles;
8. independently verify each candidate bundle;
9. retain each bundle manifest hash and selected lock hash.

No passed model/release gate is inferred merely from runtime qualification.

---

## 12. Checkpoint C — disconnected OS installation qualification

Execute the canonical Windows and Linux offline qualification wrappers on disconnected hosts.

### Windows

Composite evidence must bind:

- Windows CPU candidate evidence;
- Windows CUDA candidate evidence;
- exact Windows candidate bundles/locks;
- actual host compatibility;
- application/source/release identity.

### Linux

Composite evidence must bind:

- Linux CPU candidate evidence;
- Linux CUDA candidate evidence;
- exact Linux candidate bundles/locks;
- actual host compatibility;
- application/source/release identity.

### Network-isolation rule

The qualification host must not have usable outbound Internet connectivity.

An invalid proxy alone is insufficient if another network path remains available.

### Exit criteria

Both OS-level offline-install gates validate independently and cryptographically bind their CPU+CUDA subevidence.

---

## 13. Checkpoint D — formal CCTV quality qualification

Use the frozen private held-out corpus.

Require:

- exact corpus-manifest SHA-256;
- exact ground-truth-manifest hashes;
- exact source-video SHA-256 binding;
- authoritative imported-media SHA-256/ETag equality;
- authoritative duration equality;
- nonzero reviewed Person ground truth;
- nonzero reviewed Vehicle ground truth;
- approved per-class thresholds;
- deterministic one-to-one temporal/spatial evaluation;
- independent recalculation before promotion.

No threshold or annotation changes are permitted after seeing final qualification outcomes without invalidating and restarting the quality evidence chain.

### Exit criteria

Both supported classes independently satisfy the frozen qualification thresholds and the formal quality evidence validates.

---

## 14. Checkpoint E — recovery and performance qualification

Execute the Linux NVIDIA recovery/performance qualification against the exact frozen candidate.

Measure and retain at least the metrics required by the current acceptance profile, including:

- processing throughput/FPS;
- p95 end-to-end latency;
- soak memory growth;
- bounded failure/recovery behavior;
- runtime supervisor/retry behavior where specified.

Evidence must retain the exact approved thresholds and independently prove observed results satisfy them.

### Exit criteria

Recovery/performance evidence validates against the same source/build/profile identities used by the candidate qualification chain.

---

## 15. Checkpoint F — application lifecycle qualification

### 15.1 Fresh offline installation

On a clean/reprovisioned Windows/IIS application plane:

1. confirm no accepted MAVI application is already installed;
2. transfer the exact hashed application artifact using controlled offline media;
3. install using the approved repeatable process;
4. start the application only after installation;
5. observe live health/build/commit identity;
6. verify UI/API/static assets;
7. prove no remote runtime dependencies.

### 15.2 Offline update

Separately:

1. provision an explicitly supported prior release;
2. record the prior immutable identity;
3. establish representative authoritative state;
4. record a pre-update authoritative-state check;
5. transfer the exact accepted target artifact offline;
6. execute all required application/config/database migrations;
7. observe the target build/commit;
8. execute the post-update authoritative-state check;
9. verify retained data and product operation.

Fresh-install evidence and update evidence are separate mandatory proofs.

---

## 16. Checkpoint G — candidate production-topology scenarios

Before promotion, execute controlled candidate scenarios in the production-representative topology.

Required scenarios include:

### Formal target-containing E2E

`Camera -> managed import -> queue -> Linux CUDA worker -> completed run -> Track search -> Track detail -> representative evidence`

Require at least one reviewable accepted Track and integrity-verified representative artifact.

### Empty-scene diagnostic

Prove zero-target handling does not create false accepted objects and cannot masquerade as formal acceptance.

### Failure/reprocess

Prove a controlled failure is retained truthfully and reprocessing produces a separately identifiable authoritative run without stale/failed accepted artifacts contaminating the final result.

### Log inspection

Retain and inspect the required operational logs for the exact scenario window. Logs are supporting evidence, not a substitute for authoritative API/evidence state.

---

## 17. Checkpoint H — backup and clean-target restore

After a successful candidate acceptance case exists:

1. capture the live storage topology attestation;
2. bind the exact source database topology hash, managed-media root identity and accepted-evidence root identity;
3. create PostgreSQL backup;
4. create managed-source backup;
5. create accepted-evidence backup;
6. create immutable file manifests and SHA-256 values;
7. restore to a distinct clean database target and clean storage roots;
8. start the restored deployment against the restored topology;
9. query live restored storage topology;
10. require exact restored topology binding;
11. execute the authoritative-state verification;
12. re-read source media and representative evidence by API;
13. revalidate Camera/VideoAsset/ProcessingRun/Track/Artifact identities and relationships;
14. revalidate completed-run provenance.

A DB-only backup cannot pass. A restore check pointed at the still-working source deployment cannot pass.

---

## 18. Checkpoint I — independent evidence assessment

Before promotion, run the canonical independent closure/evidence assessment against every candidate evidence object.

Require:

- exact source commit;
- exact MAVI build;
- exact acceptance-profile hash;
- exact target verified-manifest hash;
- exact qualification-corpus hash;
- exact platform/lock/bundle hashes;
- evidence schema validity;
- all mandatory gate results passed;
- cross-gate hash consistency;
- no stale evidence from a previous candidate.

The independent assessor must report no mandatory pending/failed candidate evidence except the deliberate release-promotion state itself.

---

## 19. Checkpoint J — release metadata promotion

Only after Checkpoint I is clean:

1. run the canonical promotion constructor;
2. reopen and validate the underlying evidence for every mandatory gate;
3. construct candidate promoted metadata in an output location;
4. verify the promoted release selection independently;
5. review the metadata-only diff;
6. commit the status/evidence-only promotion through a dedicated reviewed PR/commit;
7. do not hand-edit JSON to say `passed`.

Expected truthful result after promotion:

- runtime profile qualified;
- qualification overall result passed;
- mandatory gates passed with evidence references;
- model manifest verified with matching qualification ID.

Any mismatch aborts promotion.

---

## 20. Checkpoint K — exact production bundle generation

From the promoted exact source/release state:

1. generate every required production bundle;
2. verify deterministic bundle manifests;
3. retain bundle SHA-256 values;
4. ensure no online resolution or first-run download path exists;
5. ensure shipped platform lock exactly matches promoted runtime metadata.

Required production variants remain:

- Windows x86_64 CPU;
- Windows x86_64 CUDA;
- Linux x86_64 CPU;
- Linux x86_64 CUDA.

---

## 21. Checkpoint L — disconnected production-bundle smoke

Each exact production bundle must independently pass disconnected production-mode install/runtime smoke on a compatible host.

Candidate-bundle evidence is not sufficient.

Require per variant:

- exact production bundle hash;
- exact platform lock hash;
- actual host compatibility;
- installation from local artifacts only;
- runtime startup;
- correct device selection;
- no first-run downloads;
- no usable outbound Internet;
- functional worker/inference path as required.

Any production-bundle failure reopens the release even if candidate evidence had previously passed.

---

## 22. Checkpoint M — final full production-topology acceptance

After production bundles pass:

1. deploy the exact promoted application artifact;
2. deploy exact qualified production worker bundle;
3. use the approved PostgreSQL/storage topology;
4. enforce disconnected operation;
5. execute the formal target-containing scenario again;
6. validate live application build/commit;
7. validate live storage topology;
8. validate completed-run provenance;
9. validate Track search/detail;
10. validate source and representative evidence bytes;
11. validate UI operational paths and deep links;
12. perform final log inspection;
13. confirm no cloud/Internet dependency.

This is the final product-level proof after promotion and exact production-bundle generation.

---

## 23. Final closure assessment

Run the canonical Phase-1 closure assessor with `--require-complete` and the full retained evidence set.

The only acceptable Phase-1 success state is:

`release-verified`

The closure package shall contain:

- exact source commit;
- merge/release baseline;
- promoted release metadata hashes;
- application artifact hash;
- all mandatory qualification evidence hashes;
- production bundle hashes;
- lifecycle evidence hashes;
- production scenario evidence hashes;
- backup/restore evidence hashes;
- final acceptance record hash;
- closure-status JSON;
- human-readable qualification summary.

---

## 24. Final acceptance decision

The Task-18 closure report shall state exactly one of:

### ACCEPTED

All mandatory evidence passed and independent closure assessment reports `release-verified`.

### NOT ACCEPTED

A mandatory requirement failed and requires engineering correction.

### QUALIFICATION INCOMPLETE

No failure is being waived, but a mandatory external prerequisite/evidence item could not be executed, such as unavailable required hardware.

There is no `accepted by assumption` state.

Any operational limitation that does not violate a mandatory requirement may be listed separately, but it must not be used to reinterpret a failed mandatory gate as passed.

---

## 25. Defect handling during Task 18

If a defect is discovered:

1. stop the affected qualification sequence;
2. classify severity and affected proof chain;
3. reproduce the defect outside authoritative evidence capture where practical;
4. implement the smallest professional correction;
5. add regression coverage;
6. perform independent internal review;
7. merge the correction normally;
8. establish a new frozen source/build identity;
9. invalidate every dependent evidence object;
10. resume qualification only from the earliest affected checkpoint.

Do not continue collecting evidence against a candidate already known to be defective.

---

## 26. Rollback and recovery

Qualification actions must never jeopardize the only working copy of operational state.

Before destructive lifecycle/restore actions:

- confirm source and target identities are distinct;
- retain pre-action manifests/hashes;
- use clean/reprovisioned targets;
- retain rollback media/configuration;
- document the operator responsible for restoring the rehearsal/qualification environment.

Release metadata promotion shall occur through reviewed repository changes and can be reverted through normal version control if a later production-bundle or final-topology proof fails. A reverted promotion does not make earlier failed evidence valid.

---

## 27. Review and stopping rule

Task 18 is operationally expensive; review shall remain rigorous but bounded.

Before each irreversible state transition:

- verify the exact candidate SHA;
- verify all prerequisite evidence exists;
- verify all prior mandatory checkpoints are green;
- run one focused Critical/P1/P2 review of the transition artifacts.

External Codex review may be requested when available, but tool availability shall not be allowed to manufacture or waive evidence. If Codex is unavailable, the accepted engineering rule from PR #38 applies: a clean independent Critical/P1/P2 internal review plus all mandatory deterministic gates may authorize the software/repository transition. **This exception never substitutes for hardware, disconnected-host, quality, performance, lifecycle or backup/restore evidence.**

Stop iterating once the accepted requirements are proven. Optional hardening discovered after closure becomes Phase-2 backlog unless it invalidates Phase-1 acceptance.

---

## 28. Recommended execution ownership

Task 18 should be run as a controlled qualification campaign rather than one long feature PR.

Recommended repository structure:

1. this planning branch/PR;
2. qualification execution against the accepted integration baseline;
3. focused remediation PRs only if defects are discovered;
4. a dedicated release-metadata promotion PR after candidate evidence is complete;
5. a final Phase-1 closure documentation PR containing non-sensitive hashes/status only.

Operational evidence remains in the approved evidence workspace and is referenced by immutable hashes rather than copied wholesale into Git.

---

## 29. Definition of done

Task 18 is complete only when all of the following are true:

- exact qualification baseline is recorded;
- production prerequisites are observed and approved;
- Windows CPU runtime qualification passed;
- Windows CUDA runtime qualification passed;
- Linux CPU runtime qualification passed;
- Linux CUDA runtime qualification passed;
- Windows offline-install qualification passed;
- Linux offline-install qualification passed;
- formal CCTV-quality baseline passed for both Person and Vehicle;
- Linux NVIDIA recovery/performance passed;
- fresh offline Windows/IIS installation passed;
- offline update from a supported prior release passed;
- formal candidate production-topology scenario passed;
- empty-scene diagnostic passed;
- failure/reprocess scenario passed;
- required production log inspection passed;
- offline backup and clean-target restore passed;
- authoritative post-restore state verification passed;
- all mandatory candidate evidence independently validated;
- release metadata promotion completed through deterministic tooling;
- all four exact production bundles generated and verified;
- all four production bundles passed disconnected production-mode smoke;
- final full disconnected production-topology acceptance passed;
- closure assessor returns `release-verified`;
- final Phase-1 closure report is approved;
- repository documentation records Phase 1 as accepted without overstating any unavailable evidence.

Only then may Phase 2 become the active product-development phase.

---

## 30. Immediate first action after plan approval

Do **not** begin by changing code.

Begin with **Task 18 Qualification Readiness Pack**:

1. identify the actual Windows operational host;
2. identify the actual Windows CUDA qualification host;
3. identify the actual Linux NVIDIA production/qualification host;
4. identify the PostgreSQL source and clean restore target;
5. confirm required GPU/driver/CUDA availability;
6. identify the supported prior release for offline-update proof;
7. identify/freeze the controlled private Person+Vehicle qualification corpus;
8. create the approved external evidence root;
9. run prerequisite collectors;
10. produce a readiness matrix of **READY / BLOCKED / MISSING** before any authoritative evidence capture.

This readiness pack is the next execution artifact. It should expose infrastructure gaps before expensive formal qualification begins.
