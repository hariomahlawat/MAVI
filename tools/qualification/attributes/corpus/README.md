# S2c.1 corpus, partition and annotation tooling

**Slice:** Stage 2 S2c.1 — Task + corpus + labels (S2c plan §10, §22). **Status:** tooling delivered; no operational corpus, pilot or seal exists yet, so **F1 stays OPEN** (`docs/qualification/stage2-s2c/corpus/f1-evidence-record.json`).

**What it does:**
- freezes task semantics;
- produces leakage-safe partitions;
- runs recurrence and duplicate audits;
- runs independent labelling with adjudication;
- computes agreement;
- seals the frozen qualification test;
- checks F1 evidence.

**What it never does:** evaluate or select a model, tune a threshold, or score the frozen test.

**Dependencies:**
- the Python standard library;
- **Pillow**, already a declared MAVI Vision project dependency (`src/vision/pyproject.toml`; `config/dependencies/offline-dependency-policy-v1.json`), used only for the near-duplicate fingerprint.

No dependency is added. The tooling is fully offline: no network module is imported (a test enforces this), and no cloud labelling service is used.

```
python tools/qualification/attribute_corpus.py <command> --help
```

## 1. Where things live

| Kept in Git (reviewable, no imagery) | Kept outside Git (Corpus Custodian's access-controlled store) |
|---|---|
| this tooling and its tests (synthetic fixtures only) | evidence crops (JPEG), addressed by SHA-256 |
| the candidate/frozen task file, annotation guide, F1 evidence record | frozen-test ground truth (`ground-truth --frozen-out`) |
| the SHA-256 of every retained record, in the F1 evidence record | the **retained-record store**: every record as `<sha256>.json`, plus `annotation-ledger.jsonl`, `frozen-access-log.jsonl`, and one `frozen-access-log-<sealSha256>.jsonl` per superseded seal. The records are: corpus manifest, audits, partition, candidate and frozen task, every assignment and batch, adjudications, pilot and main agreement reports, sealed evaluation view, and every seal |
| | labelling spreadsheets and any local configuration naming evidence paths |

Reviewable, image-free copies of the non-frozen records may also be committed once an operational corpus exists. The F1 checker never relies on them: it re-verifies from the store (§10).

Records never contain local paths or locators; parsers refuse them (`canonical.refuse_path_leaks`). `tools/verify_repo.py` refuses any tracked image under the S2c corpus areas.

## 2. Canonical encoding and identity

- **Encoding:** every record is canonical JSON: sorted keys, `","`/`":"` separators, ASCII, no NaN, one trailing LF.
- **Identity:** a record's identity is the SHA-256 of those bytes.
- **Ordering:** lists are normalised into a documented order before hashing, so producer order never changes identity:
  - sources by `sourceId`;
  - tracks by `trackId`;
  - observations by `evidenceRank`;
  - assignments and moves by `trackId`;
  - labels by unit key then attribute.
- **Revisions:** a revised corpus manifest has `revision + 1`, `supersedes` = the previous SHA-256, and a new identity (`manifest.revise_corpus`).
- **Text files:** the annotation guide is identified by its LF-normalised SHA-256 (CRLF → LF only).

## 3. Records

| Record (`schemaVersion`) | Content | Module |
|---|---|---|
| `mavi-attribute-task-v1` | attributes, values, conditional values, unscorable reasons, subject validity, pre-declared merge candidates, pilot decision rules | `task.py` |
| `mavi-attribute-corpus-manifest-v1` | corpus id, revision, `corpusKind` (`operational` / `synthetic-fixture`), raw-evidence pin, sources, tracks, observations | `manifest.py` |
| `mavi-attribute-recurrence-audit-v1` | reviewer-declared recurrence groups (Track UUIDs only), status, decision | `recurrence.py` |
| `mavi-attribute-duplicate-audit-v1` | method, dHash fingerprints, exact/near pairs, groups, decisions | `duplicates.py` |
| `mavi-attribute-partition-manifest-v1` | policy, clusters, moves with reasons, per-Track assignment, coverage checks | `partition.py` |
| `mavi-attribute-annotation-assignment-v1` / `-batch-v1` | units and allowed attributes; submitted labels | `annotation.py` |
| `mavi-attribute-reveal-packet-v1` / `mavi-attribute-adjudication-v1` | adjudication view; decisions with rationale | `annotation.py` |
| `mavi-attribute-ground-truth-v1` | every original label, resolution (`single` / `consensus` / `adjudicated`), final label, partition | `annotation.py` |
| `mavi-attribute-agreement-report-v1` / `mavi-attribute-pilot-report-v1` | agreement statistics; pilot prevalence, timing and recommendations | `agreement.py`, `pilot.py` |
| `mavi-attribute-frozen-test-seal-v1` | frozen member set hash, frozen ground-truth hash, annotation-ledger head, custodian | `frozen.py` |
| `mavi-attribute-corpus-report-v1` | diversity distributions (§8) | `report.py` |
| `mavi-s2c-f1-evidence-record-v1` | F1 evidence by hash; checker verdict | `f1.py` |

### 3.1 Corpus manifest: MAVI's own evidence identity

- **Source:** one VideoAsset processed by one ProcessingRun. It carries:
  - the MAVI UUIDs, `processingRunId` and `videoAssetId`;
  - `siteId` and `cameraId`, as corpus-local pseudonyms;
  - `recordingDate`, as a date only;
  - conditions: lighting, setting, frame size, source class.
- **Site:** MAVI has no Site entity (a Camera has only a free-text `LocationName`), so the Corpus Custodian assigns site pseudonyms.
- **Track:** the MAVI Track UUID and object class.
- **Observation:** exactly the S2b lease fields (`LeaseObservation`): Observation UUID, role (`representative` / `near-view` / `early-diverse` / `late-diverse`), evidence rank, size, SHA-256; plus optional crop width and height. A Track needs its Representative, and roles and ranks are unique.
- **Raw-evidence pin:** one pin for the whole corpus (vision pipeline profile SHA-256, Evidence Set selector and scorer versions). A selector or profile change re-derives the affected crops; mixing pins is impossible (S2c plan §10.2). S1.4 (register B1–B6) is still open, which makes this a live stop condition.
- **Refused:** duplicate Track, Observation, ProcessingRun or VideoAsset identities.

## 4. Partitioning (`partition.py`)

1. **Cluster** = `(siteId, dateBlock)`, where `dateBlock = floor((recordingDate − policy.dateEpoch) / dateBlockDays)`. The epoch is pinned in the policy, so adding an earlier source in a revision cannot shift every block boundary. A source dated before the epoch is refused. All cameras of a site within one contiguous block share a partition. Tracks are never split individually.
2. **Frozen test:**
   - `heldOutSites` whole sites, ordered by seeded SHA-256, give cameras unseen elsewhere;
   - plus the latest `frozenLatestBlockFraction` of every other site's blocks, a temporal hold-out of contiguous blocks.
3. **Training / tuning / selection:** the remaining clusters, in seeded hash order, go greedily to the partition with the largest Track deficit against `targetFractions`. Tuning and selection are separate partitions (R2 item 7). Every partition must be non-empty.
4. **Link resolution:**
   - when a *confirmed* recurrence group or an applied duplicate group spans partitions, every **cluster** it touches moves wholly to **training**, and this repeats to a fixpoint;
   - whole clusters move, never single Tracks, so a site-date block is never fragmented;
   - moves only ever go into training, so an evaluation partition can lose clusters but never gain a leaking one;
   - every move is recorded (`clusterId`, `from`, `to`, `reasons`), and each cluster keeps its `initialPartition`. Nothing is deleted.
5. **Checks:** Track and camera counts per partition, and cameras unseen outside the frozen test. Shortfalls (fewer than `minimumCamerasPerPartition`, no unseen frozen camera) are recorded as **limitations**, never waived.
6. **Audits are bound.** The manifest records the recurrence and duplicate audit hashes. An operational corpus cannot be partitioned without both audits (`partition_operational_requires_audits`).

`verify_partition` takes the audits actually supplied, re-derives everything and refuses:
- audit hashes that differ from the manifest's;
- a Track assigned twice or missing;
- an empty partition;
- a Track whose partition differs from its cluster's;
- a move that is not into training;
- a link group spanning partitions;
- any non-reproducible difference.

## 5. Leakage controls

- **Recurrence** (`recurrence.py`): humans decide. Groups hold Track UUIDs only; there is no name, identity or embedding.
  - A proposal from an evaluation-only similarity pass (S2c.3, never shipped, never a bake-off candidate's family) must declare its proposer family, and applies only once a reviewer confirms it.
  - Rejected groups are retained.
  - This is bookkeeping, not re-identification.
  - **Recall is bounded by the reviewers.** The optional `recallSample` records a second review of a random sample of cross-partition Track pairs (`sampledPairs`, `missedRecurrences`). F1 requires it. With no biometric matcher (excluded by design), recall remains an estimate, and that is a recorded limitation.
  - **Deviation from the plan's wording:** the plan describes recurrence pairs by crop SHA-256. The audit records Track UUIDs, since a Track owns its crops through the manifest. The link is the same, and it is also robust to crop re-derivation under a new raw-evidence pin.
- **Duplicates** (`duplicates.py`): two methods.
  - Exact duplicates: same SHA-256 under two Observation UUIDs. These always apply and cannot be rejected.
  - Near duplicates: dHash-64. Greyscale, 9×8 `BOX` resize, horizontal gradient bits, Hamming distance ≤ `hammingThreshold` (0–7). These apply unless a reviewer rejects them: for leakage, the conservative error is to link too much.
  - Candidate pairs come from a pigeonhole byte index.
  - Crop integrity is checked against the manifest before fingerprinting.
  - The audit must equal what the method produces from the recorded fingerprints, so no pair can be dropped by hand.

## 6. Annotation workflow (`annotation.py`)

1. `confirm-rules`: the owner confirms the pilot thresholds, which may be raised but never lowered. Pilot assignments are refused until this is done.
2. `register-annotator`: register each annotator by pseudonym, with `--independent` for annotators independent of model selection and threshold tuning.
3. `pilot-sample`, then `assign --phase pilot`: the pilot sample is camera-stratified and training-only. Assignments carry no labels.
4. `submit --labels-csv`: the batch must cover every assigned unit × attribute exactly once, and each label must be valid under the task. If `subject-validity` is not `valid`, every attribute must be `unscorable/non-subject`.
5. `pilot-report`, then `freeze-task`: the owner decision may apply only the pre-declared merges and removals, never an addition. The artefact bound therefore can only fall from the candidate vocabulary's measured value (S2c plan §12.3).
6. `assign --phase main` (requires the frozen task), then `submit`.
7. `reveal`, then `adjudicate` (records the JSON decision file in the ledger), then `ground-truth`, then `agreement --phase main`.
   - An adjudication counts only if the ledger issued its reveal packet to that adjudicator, covering every unit it decides.
8. `seal` commits both views, records a `seal-created` event in the annotation ledger, writes the sealed evaluation view and creates the access log. Then use `frozen-access` / `seal-status` for any later access.
   - A second seal on the same ledger is refused unless it names the latest seal with `--supersedes`, `--supersedes-reason` and `--superseded-access-log`. That old log must show the old seal compromised, and the new frozen member set must differ.

**The ledger** is append-only and hash-chained. It enforces independence:
- no reveal packet while an independent assignment covering its units is unsubmitted;
- no independent batch from an annotator already shown others' labels for those units.

Agreement and pilot reports accept only ledger-registered batches.

**Ground truth:**
- It is built from main-phase batches under the frozen task only. Duplicate batches are refused.
- **Every** main batch the ledger registered must be supplied. A subset is refused, since dropping one annotator's batch would hide its disagreements.
- The final labels must agree with the final `subject-validity`: `non-subject` if and only if the subject is not valid. This holds after adjudication too. A batch that marks a valid subject `non-subject` is refused.
- It keeps every original label beside the final one.
- A conflict without an adjudication recorded in the ledger is an error.
- `unscorable` stays `unscorable`.
- Consensus is on the outcome and value. When raters agree a unit is unscorable but give different reasons, the final reason follows `REASON_PRECEDENCE` (guide §3.1), and the row carries `reasonDisagreement: true`.

## 7. Agreement (`agreement.py`)

- **Labels used:** independent labels only.
- **Facets**, per attribute:
  - **full**: value or `unscorable`;
  - **scorability**: scorable vs `unscorable`;
  - **value**: among raters who scored the unit.
- **Statistics:** raw pairwise agreement, Cohen's κ (exactly two raters) and Krippendorff's α, nominal (any raters, missing allowed).
- **Undefined statistics** are `null` with a reason, never a number.
- **Also reported:**
  - confusion by value pair;
  - category counts;
  - unscorable rate;
  - adjudicated units;
  - double-labelled units with an independent annotator;
  - support by partition, camera and site.
- **Adjudications:** `agreement --adjudications` accepts only adjudications recorded in the ledger.
- **Scope:** reports cover the evaluation partitions (training/tuning/selection) by default (`scope: evaluation-partitions`). Frozen-test label statistics appear only with `--include-frozen-custodian-only`, for the custodian's own qualification of the frozen set. Such a report is never committed and never shown to selection work.
- **Rendering:** reports render as Markdown. A synthetic fixture is labelled as such in the rendering.

## 8. Frozen test (`frozen.py`)

- **Seal:** it commits:
  - the frozen member set (Track UUIDs with crop SHA-256s);
  - the frozen ground-truth SHA-256 and the evaluation-view SHA-256, both views of one ground truth;
  - the annotation-ledger head.

  Every frozen Track must be labelled first.
- **Access log:**
  - The access log opens with the seal. Only `seal` creates it; every other command refuses a missing or empty log, so deleting it cannot reset it.
  - Every access is logged **before** anything is returned.
  - Before S5, only `integrity-verify` (returns a hash only) and `custody-transfer` are proper; `s5-scoring` is proper only at stage `S5`.
  - Any other access, or one declared after the fact (`declare-improper-access`), marks the seal **compromised**.
- **After a compromise:** qualification plan R1 requires a new frozen set. A superseding seal must name the compromised one and have a different member set.
- **Truncation:** a hash chain cannot reveal a cut-off log on its own, so recorded heads (F1 record, MSR) are checked with `seal-status --recorded-head`.
- **Evaluation view:** model-selection tooling reads only the evaluation view, via `load_evaluation_view(view, seal)`. It refuses:
  - frozen rows;
  - a view not stamped with the seal;
  - a view whose content differs from the one the seal committed.
- **Stage is declared, not detected.** The `stage` of an access is the actor's own declaration; the tool cannot know which stage really asked. The controls that make a false declaration visible are custody (the frozen file lives outside the evaluation environment), logging before release, and review of the log.

## 9. Diversity report (`report.py`)

The report gives, overall and per partition:
- sites, cameras and sources;
- site-date clusters and dates;
- Tracks by class, and Tracks per camera;
- lighting, setting, frame-height band and source class;
- crops by role, and crop-height (subject-size) bands;
- with ground truth, annotated difficulty by unscorable reason.

This is the foundation for later camera/site generalisation analysis, and deliberately **not** a 500-camera, load or scale claim (S2c plan §14.1 owns scale).

## 10. F1 (`f1.py`)

`check-f1 --record <record> --store <retained-record store>` computes the verdict.

The committed record names each artefact by SHA-256 and asserts nothing else: no annotator count, statistic, seal status or camera support. The checker trusts none of it. It loads everything from the store, re-derives identities, and **recomputes** every conclusion from the primary inputs: assignments, batches, adjudications and the ledger. The labelling state it uses is the ledger as it stood at the ground truth's head.
- **Partition**, from the corpus and both audits (`verify_partition`).
- **Pilot report**, recomputed from the candidate task and every ledger-registered pilot batch. It must equal the retained report, the pilot must have used the final partition, and the frozen task must derive from it.
- **Main agreement report**, recomputed from every registered main batch and every ledger-recorded adjudication. It must equal the retained report, so compute it after adjudication. The adjudications listed in the record must equal the ledger's.
- **Both ground-truth views**, recomputed. Their hashes must equal the seal's, so the frozen labels are verified without leaving the store.
- **Seal:**
  - its frozen member set is recomputed;
  - it must be the latest `seal-created` in the ledger;
  - every earlier seal must be compromised (by its own retained log) and superseded by a different set.
- **Access log:** it must begin with this seal, extend the recorded head and show no improper access.
- **Camera support**, from the partition's checks. The record must carry every partition limitation.

**PASS additionally needs:**
- an operational corpus (synthetic fixtures never count);
- the guide unchanged since its frozen SHA-256, with every main assignment made under that guide;
- at least two annotators, at least one independent;
- for **every** attribute of the frozen task and `subject-validity`: double-labelled units, each with an independent annotator;
- at least three cameras in every partition, and a frozen camera unseen elsewhere;
- a recurrence recall sample that found no missed recurrence; otherwise, re-audit and re-sample;
- a named custodian.

A malformed retained record is refused. The guide path must resolve inside the repository. Without the store the verdict is OPEN. A record may never claim more than the checker computes.

**Residual trust (recorded, not solved):**
- The custodian holds the store. Someone who deletes and hand-recreates an access log outside the tool can hide an improper access unless an earlier recorded head exists. Commit the F1 record's `accessLogHead` whenever the log changes, so Git history anchors it.
- Double-labelling agreement on the frozen test itself is computed only in custodian-only reports (`--include-frozen-custodian-only`). It is not part of F1, because F1's agreement evidence must stay free of frozen-test label statistics.

## 11. Mutation and adversarial record

| # | Fault | Killing test |
|---|---|---|
| 1 | random Track-level split instead of cluster split | `test_mutation_random_track_split_is_detected` |
| 2 | same camera/date block placed in two partitions | `test_mutation_camera_date_block_in_two_partitions_is_detected`, `test_no_site_date_cluster_crosses_partitions` |
| 3 | recurring subject left across partitions | `test_mutation_recurring_subject_left_across_partitions_is_detected` |
| 4 | duplicate crop crosses partitions | `test_mutation_duplicate_crossing_partitions_fails_verification` |
| 5 | tuning and selection collapsed | `test_mutation_tuning_and_selection_collapsed_is_detected` |
| 6 | frozen test exposed to selection | `test_selection_view_refuses_frozen_labels`, `test_the_selection_view_must_be_the_one_the_seal_committed`, `test_selection_stage_access_is_refused_logged_and_compromises_the_seal` |
| 7 | manifest hash ignores labels/partition | `test_manifest_hash_covers_content`, `test_mutation_partition_hash_covers_assignments`, `test_seal_is_stable_and_any_mutation_changes_it` |
| 8 | annotator B sees A's label before independent submission | `test_mutation_annotator_b_cannot_submit_after_seeing_a` |
| 9 | adjudication overwrites original labels | `test_conflicts_require_adjudication_and_originals_are_kept` |
| 10 | unscorable silently converted to negative | `test_unscorable_is_an_outcome_not_a_negative`, `test_conflicts_require_adjudication_and_originals_are_kept` |
| + | F1 PASS from self-asserted hashes | `test_without_the_store_the_named_hashes_prove_nothing`, `test_an_edited_retained_record_fails_its_hash`, `test_a_record_that_names_a_hash_it_does_not_retain_fails` |

These tests were written against the implemented rules. They kill each fault by asserting the refusal, or the invariant, that the fault breaks.

**Source-mutation run** (each guard removed in turn, the named tests re-run, the source restored):

| Guard removed | Result |
|---|---|
| cluster-fragmentation check in `verify_partition` | killed (camera/date-block test fails) |
| empty-partition check (tuning/selection collapse) | killed |
| frozen-row refusal in `load_evaluation_view` | killed |
| independence check in `submit_batch` | killed |
| unresolved-conflict check in `build_ground_truth` | killed |
| improper-access refusal in `access_frozen` | killed |
| operational-corpus requirement in `f1_verdict` | killed |
| training-only check for pilot assignments | killed |
| link-span check in `verify_partition` | **survived, equivalent**: `verify_partition` re-derives the partition from the audits and refuses any non-reproducible manifest first, so a manifest that leaves a confirmed group across partitions is still refused (`partition_not_reproducible`). The explicit check is retained as defence in depth and as the clearer error |

**Second source-mutation run** (after the cold-review fixes, same method; `mut2`):

| Guard removed | Result |
|---|---|
| store requirement in `f1_verdict` | killed |
| hash check in the F1 store | killed |
| seal-status check in F1 | killed |
| access-log head check in F1 | killed |
| ledger-registered batches in F1 | killed (after adding `test_a_main_report_naming_an_unregistered_batch_is_refused`; it first survived). Superseded in the third run by full recomputation |
| sealed-view binding in `load_evaluation_view` | killed |
| create-only access log | killed |
| same-ground-truth check in `build_seal` | killed |

**Third source-mutation run** (after the second cold review: F1 recomputation, seal chain, batch completeness):

| Guard removed | Result |
|---|---|
| main-report recomputation in F1 | killed |
| pilot-report recomputation in F1 | killed |
| every task attribute required in F1 | killed |
| frozen guide for main labelling in F1 | killed |
| latest seal in the ledger, in F1 | killed (after adding `test_f1_refuses_a_seal_the_ledger_does_not_name_as_latest`; the first test was masked by the view binding) |
| seal member recomputation in F1 | killed (after adding `test_f1_recomputes_the_sealed_member_set`; it first survived) |
| re-seal requires `--supersedes` (ledger) | killed |
| batch completeness in ground truth | killed |
| valid subject never `non-subject` | killed |
