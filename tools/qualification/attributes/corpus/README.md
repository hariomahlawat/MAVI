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

**C+ source policy (2026-10-02):** ADR-015 governs **public-first development, protected final qualification**. Approved public data may support training, tuning, component evaluation, selection with contamination/domain caveats, reference benchmarks and regression/challenge; public origin alone does not imply `REFERENCE_ONLY`. Final frozen qualification requires eligible protected newly commissioned/owner-captured real video, verified checkpoint/capture chronology, rights/privacy, real processing, audit/separation, annotation and seal/access evidence. Missing evidence never admits a file automatically.

Keep Training, Development/Tuning, Public Benchmark/Reference, Selection, Qualification Candidate, Frozen Qualification and Regression/Challenge separate, plus the existing engineering-calibration/E3 split. Still-image training/evaluation uses a separate manifest and is component evidence, never an invented Track or an operational camera. Raw holdout capture may precede final executable freeze only under protected custody inaccessible to development/selection; the annotated seal still follows R1 before candidate corpus execution. Final-test exposure to change the system requires a new independent holdout, preserving the existing recovery history.

**Enforcement boundary:** the machine-checkable part of the ADR-015 §3 frozen contract is enforced in code. A source's `provenance` (§3.1) must show a protected origin, an approved `frozen-qualification` purpose and no prior exposure. The partitioner never holds out or freezes other footage (§4.5), and `verify_partition` and the seal re-check every frozen Track. Passing that check is necessary, not sufficient: chronology, capture evidence, rights and privacy remain human inputs, and a valid manifest does not prove them. Existing grouping, camera floors, audits and F1 gates remain unchanged, and neither two nor ten raw hours establishes support. B0 S1 closure and all 63 human decisions remain immutable; a new approved engineering purpose does not change the original decision. Policy concepts are not new corpus schema/state values.

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
| the SHA-256 of every retained record, in the F1 evidence record | the **retained-record store** (including the owner freeze decision and any earlier corpus revisions): every record as `<sha256>.json`, plus `annotation-ledger.jsonl`, `frozen-access-log.jsonl`, and one `frozen-access-log-<sealSha256>.jsonl` per superseded seal. The records are: corpus manifest, audits, partition, candidate and frozen task, every assignment and batch, adjudications, pilot and main agreement reports, sealed evaluation view, and every seal |
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
  - conditions: lighting, setting, frame size, source class;
  - optional `provenance` (`provenance.py`, owner decision C+): `origin` (`public` / `private` / `commissioned` / `owner-captured`), `approvedPurposes`, `acquisitionReceiptSha256` (required for public footage) and `priorExposures` (`{use, recordSha256}`). A corpus revision may not change a source's origin or drop an exposure, even if the source is renamed (it is matched by VideoAsset as well). A source whose provenance was undeclared may be declared later, but never as frozen-eligible. `frozen-qualification` may be combined only with `training`/`tuning`/`selection`, whose exposure the partitioner records.
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
5. **Frozen eligibility (C+).** A Track may be frozen only if its source's provenance has a protected origin (`commissioned` / `owner-captured`), approves `frozen-qualification` and records no exposure. An operational source with no provenance is never eligible; a synthetic fixture without provenance keeps its earlier behaviour. Ineligible clusters are never held out or temporally frozen: they join the training/tuning/selection pool, and the limitation `frozen_ineligible_clusters:<n>` is recorded. With every cluster eligible, the assignment is unchanged. `partition_exposures` lists each source's training/tuning/selection exposure, for `priorExposures` in a later revision.
6. **Checks:** Track and camera counts per partition, and cameras unseen outside the frozen test. Shortfalls (fewer than `minimumCamerasPerPartition`, no unseen frozen camera) are recorded as **limitations**, never waived.
7. **Pinned training Tracks.** The optional `policy.pinnedTrainingTrackIds` names Tracks that must stay in training. Their clusters move to training (reason `pinned-training`) before link resolution. The policy is embedded in the manifest, so this is reproducible.
   - Pinning moves whole clusters, so it can cost the held-out camera: a pinned Track in a held-out site pulls that site's cluster into training. That shortfall is recorded as a limitation.
   - The optional `policy.excludedFromFrozenTrackIds` names Tracks that may not enter the frozen test. A cluster holding one that would be frozen goes to training (reason `excluded-from-frozen`).
   - **R1 recovery after a compromised seal:**
     - every Track of the old seal's partition was exposed (frozen labels leaked; training, tuning and selection were open to candidates), so the replacement frozen test must come from **new footage**;
     - revise the corpus to add it, label the new Tracks, and re-partition with the pilot pinned and every previously exposed Track in `excludedFromFrozenTrackIds`;
     - `test_r1_recovery_needs_new_footage_and_then_reaches_pass` walks this path.
8. **Audits are bound.** The manifest records the recurrence and duplicate audit hashes. An operational corpus cannot be partitioned without both audits (`partition_operational_requires_audits`).

`verify_partition` takes the audits actually supplied, re-derives everything and refuses:
- audit hashes that differ from the manifest's;
- a Track assigned twice or missing;
- an empty partition;
- a Track whose partition differs from its cluster's;
- a frozen Track from footage that is not frozen-eligible (`partition_frozen_track_not_eligible`);
- a move that is not into training;
- a link group spanning partitions;
- any non-reproducible difference.

## 5. Leakage controls

- **Recurrence** (`recurrence.py`): humans decide. Groups hold Track UUIDs only; there is no name, identity or embedding.
  - A proposal from an evaluation-only similarity pass (S2c.3, never shipped, never a bake-off candidate's family) must declare its proposer family, and applies only once a reviewer confirms it.
  - Rejected groups are retained.
  - This is bookkeeping, not re-identification.
  - **Recall is bounded by the reviewers.** The `recallSample` is a reproducible human second look, with no ReID, embeddings or face matching:
    - `recall-sample` draws it deterministically (method `recall-sample-v1`) from the population of same-class Track pairs in different partitions;
    - the seed is **derived** from Track identity only (`recall_seed`: every Track ID and its object class), never chosen, and independent of the partition, the audits and any metadata. The pair order is therefore fixed for the corpus. No edit that leaves the Track assignments unchanged can redraw the sample, whether a new recurrence group, a policy field or a metadata revision;
    - the size is fixed at `RECALL_SAMPLE_PAIRS` (100) by the method, so a reviewer cannot draw more pairs and stop before a found one. Raising it is a reviewed change to that constant. With no recurrence found in n random pairs, the one-sided 95% upper bound on the miss rate is about 3/n;
    - the population is identified by the corpus, the final partition and the recurrence groups (`populationSha256`);
    - the sample holds the exact sampled pairs, and the reviewer records one decision per pair: `recurrence`, `not-recurrence` or `uncertain`;
    - F1 regenerates the sample and requires the same population and the same pairs, in order. An altered, added or foreign pair is refused;
    - a count-only claim is refused;
    - F1 stays OPEN while any pair is unreviewed, marked `uncertain`, or marked `recurrence`. A found recurrence must be added to the audit, the corpus re-partitioned, and a new sample drawn on the new partition;
    - the partition binds the recurrence **groups** (`recurrence_groups_sha256`, the audit without its sample), so attaching the sample does not change the partition. The evidence record names the whole audit (`recurrence_document_sha256`).

    The per-pair decisions remain a human attestation, and recall remains an estimate.
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
   - The pilot verdicts bind the freeze. `freeze_task` (and F1, independently) recomputes each attribute's verdict from the report's statistics, under the confirmed rules, which the report must carry unchanged:
     - `keep`: the attribute may stay;
     - `insufficient-evidence` (fewer double-labelled units than the minimum, or no labels): the attribute must be removed, or more pilot labels collected under the same rules and a new report produced. It is never an implicit pass;
     - `merge-or-remove`: the attribute must be removed, or merged by a pre-declared attribute merge the pilot recommended. If only value agreement failed, a pre-declared value merge the pilot recommended also resolves it; a value merge cannot repair a scorability failure.
6. `assign --phase main` (requires the frozen task), then `submit`.
   - **No assignment may be abandoned.** `require_phase_complete` (used by `pilot-report`, `agreement`, `ground-truth` and F1) refuses while any issued assignment of the phase lacks its one submitted batch. Leaving hard units unsubmitted cannot shrink the sample.
   - `cancel-assignment` is the only exception, and it is narrow. It needs an actor, a reason and a **fresh replacement**:
     - issued after the cancelled assignment, and still unsubmitted;
     - exactly the same phase, round and units;
     - held by an annotator with no other assignment of that phase on those units;
     - not already replacing another assignment.

     Neither the sample nor its double labelling can shrink, and another rater's existing assignment cannot stand in. Cancellation is refused once the assignment's labels exist, or once any reveal has shown labels for its units. A cancelled assignment cannot be submitted; its replacement must be. Reveals ignore cancelled assignments.
7. `reveal`, then `adjudicate` (records the JSON decision file in the ledger), then `ground-truth`, then `agreement --phase main`.
   - **A reveal packet is canonical.**
     - `build_reveal_packet` builds it from the raw batch documents: every label, with its source batch, plus `conflictKeys` (outcome or value differ) and `reasonConflictKeys` (all say `unscorable`, with different reasons).
     - `issue_reveal` requires exactly the set of submitted batches of that phase that cover the packet's units, and rebuilds the packet: omitting a batch or trimming a label is refused.
   - An adjudication counts only if the ledger issued its reveal packet to that adjudicator, in the main phase, covering every unit it decides.
   - It may decide **only** keys in the packet's `conflictKeys` or `reasonConflictKeys`. It cannot override consensus. For a reason-only conflict, it may choose the reason but must keep `unscorable`.
   - Ground truth independently refuses an adjudication of a key with no disagreement in the submitted labels.
   - F1 rebuilds each effective adjudication's reveal packet from every main batch at the ground-truth head, and requires it to equal the retained packet. An adjudication based on incomplete evidence, including a packet forged straight into the ledger, is refused.
   - A unit × attribute already decided can be decided again only by a correction that names the earlier adjudication in `supersedes`. The superseded adjudication stays in the ledger but stops counting.
   - An adjudication with no decisions is refused, so an adjudication cannot be withdrawn without replacing it.
8. `seal` commits both views, records a `seal-created` event in the annotation ledger, writes the sealed evaluation view and creates the access log. Then use `frozen-access` / `seal-status` for any later access.
   - The command refuses output paths that already exist, so it never overwrites and a cleanup never destroys another file. It validates every input and output path, then writes the seal, the sealed view and the access log to `.partial` files, and moves them into place with a hard link, which fails rather than overwrite. A filesystem without hard links (FAT, some SMB shares) makes sealing fail closed; keep the custody store on a local NTFS or ext4 volume. Only then does it append `seal-created`, the one irreversible step. Any failure removes every file the run created, so a retry needs no manual cleanup and is never mistaken for a re-seal.
   - A second seal on the same ledger is refused unless it names the latest seal with `--supersedes`, `--supersedes-reason`, `--superseded-access-log` and `--superseded-partition` (plus `--superseded-corpus` when the corpus was revised since that seal).
   - That old log must show the old seal compromised.
   - Both member sets are recomputed from their partitions, and the new frozen set may contain **no** Track of the compromised one.
   - `seal-created` records each seal's frozen Track IDs and all of its partition's Track IDs (the exposed set), recomputed from the corpus and partition. A new seal's frozen set may contain no Track exposed by **any** earlier seal in the chain, not only by its predecessor.
   - The seal's annotation-ledger head must equal the head both ground-truth views were built at. A batch or adjudication registered in between would otherwise be silently omitted.

**The ledger** is append-only and hash-chained. An append is all or nothing: the line is flushed and fsynced, and on any failure (for example a full disk) the file is truncated back, so no partial entry survives and a retry starts from a verifiable chain. It enforces independence:
- no reveal packet while an independent assignment covering its units is unsubmitted;
- no independent batch from an annotator already shown others' labels for those units.

Agreement and pilot reports accept only ledger-registered batches.

**Ground truth:**
- It is built from main-phase batches under the frozen task only. Duplicate batches are refused.
- **Every** main batch the ledger registered must be supplied. A subset is refused, since dropping one annotator's batch would hide its disagreements.
- The final labels must agree with the final `subject-validity`: `non-subject` if and only if the subject is not valid. This holds after adjudication too. A batch that marks a valid subject `non-subject` is refused.
- It keeps every original label beside the final one.
- A conflict without an adjudication recorded in the ledger is an error. Every effective (not superseded) recorded adjudication must be supplied, and a superseded one is refused.
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

  Every frozen Track must be labelled first, and its footage must be frozen-eligible (§4.5; `seal_frozen_tracks_not_eligible`).
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

The committed record names each artefact by SHA-256 and asserts nothing else: no annotator count, statistic, seal status or camera support. The checker independently re-verifies all machine-verifiable retained evidence, and fails closed when required retained evidence or human attestations are missing or inconsistent.
- **Ledger replay:** a hash chain proves order, not validity. `AnnotationLedger.replay` re-applies every write rule (registration, assignment, submission, cancellation, reveal, adjudication) to every retained entry, loading the documents it names. Each payload must equal what the rule computes. A hand-written entry the tool would have refused is refused again: a cancellation without a fresh replacement, an adjudication on a packet never issued, widened conflict keys.
- **Assignment rebuild:** every retained assignment must equal what `build_assignment` produces from the corpus, partition and task it names: the candidate for the pilot, the frozen task for main. Units, object classes and per-unit attribute lists cannot be edited. Main labels made on an earlier corpus revision count only if the labelled crops are byte-identical in the final corpus.
- **Candidate binding:** `attributeTask.candidatePath` must be the committed candidate file (pinned), and the candidate behind the pilot must equal it, apart from an owner confirmation of its pilot rules. The raisable thresholds may only be equal or higher, and every other rule (for example `mergeConfusionShare`) is unchanged. It loads everything from the store, re-derives identities, and **recomputes** every conclusion from the primary inputs: assignments, batches, adjudications and the ledger. The labelling state it uses is the ledger as it stood at the ground truth's head.
- **Partition**, from the corpus and both audits (`verify_partition`).
- **Pilot report**, recomputed from the candidate task and every ledger-registered pilot batch, on the partition and corpus the pilot ran on (both retained). It must equal the retained report.
- **Frozen task**, re-derived with `freeze_task` from the candidate, the pilot report and the retained owner decision. It must equal the retained frozen task, so only pre-declared merges and removals can shape it. Every pilot Track must be in **training in the final partition**; after a re-partition, pin them (§4).
- Main assignments' `partitionManifestSha256` is informational. Main labels do not depend on the partition, and the recomputed reports and views use the final partition.
- **Assignment completeness**: every issued pilot and main assignment at the ground-truth head was submitted exactly once, or cancelled in favour of an identical replacement.
- **Recall sample**, regenerated from the corpus, the final partition and the recurrence groups (§5).
- **Reveal packets**, rebuilt for every effective adjudication (§6).
- **Main agreement report**, recomputed from every registered main batch and every ledger-recorded adjudication. It must equal the retained report, so compute it after adjudication. The adjudications listed in the record must equal the ledger's.
- **Both ground-truth views**, recomputed. Their hashes must equal the seal's, so the frozen labels are verified without leaving the store.
- **Seal:**
  - its frozen member set is recomputed;
  - it must be the latest `seal-created` in the ledger;
  - every earlier seal must be compromised, as shown by its own retained log;
  - every seal's frozen set is recomputed from its own retained corpus and partition and must match the ledger's `frozenTrackIds`;
  - no Track may appear in two frozen sets anywhere in the chain;
  - no frozen Track may have been exposed by an earlier seal's partition.
- **Ledger after the ground truth:** the seal's head must equal the ground truth's head. No assignment, batch, reveal or adjudication may be recorded after it, because the sealed truth would then be incomplete.
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

**Human-attestation boundary (external trust inputs; the tool checks presence and consistency, not truth):**
- the recurrence review and the per-pair recall-sample decisions;
- each annotator's labels and each adjudicator's decisions, and the annotators' declared independence;
- the declared `stage` of a frozen-test access;
- the custodian's handling of the store outside the evaluation environment.

**Residual trust (recorded, not solved):**
- The custodian holds the store. Someone who hand-edits the files outside the tool can hide history unless an earlier recorded head exists:
  - deleting and recreating an access log hides an improper access;
  - truncating the annotation ledger after a `seal-created` entry, then re-sealing plainly, hides a compromised seal.

  Hash chains cannot detect truncation on their own. Commit the F1 record (seal SHA-256, `annotationLedgerHead`, `accessLogHead`) at sealing and whenever either log changes, so Git history anchors the heads.
- The pilot units are chosen by the operator (`assign --tracks`, from training). F1 checks that they are training Tracks, but not that they are the seeded `pilot-sample`. Selecting easy pilot units could inflate pilot agreement; the pilot sample seed and size belong in the MSR.
- Re-partitioning with a different policy seed or duplicate threshold changes Track assignments (visible, to be justified in the MSR); it cannot reseed the recall sample, but it changes which of the ordered pairs are cross-partition. A found pair can therefore be pushed out of the fixed-size sample even though its Tracks still cross partitions. Treat any re-partition after a recall review as requiring the MSR to report the previous sample and its findings.
- The pilot's own retained partition is loaded by hash but not re-verified against its audits. Only the check that matters for leakage is enforced: every pilot Track is in training in the final partition.
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
| pilot-report recomputation in F1 | killed. After the third review it survived (the strict partition check had been masking it) until `test_a_forged_but_self_consistent_pilot_report_is_refused` was added |
| every task attribute required in F1 | killed |
| frozen guide for main labelling in F1 | killed |
| latest seal in the ledger, in F1 | killed (after adding `test_f1_refuses_a_seal_the_ledger_does_not_name_as_latest`; the first test was masked by the view binding) |
| seal member recomputation in F1 | killed (after adding `test_f1_recomputes_the_sealed_member_set`; it first survived) |
| re-seal requires `--supersedes` (ledger) | killed |
| batch completeness in ground truth | killed |
| valid subject never `non-subject` | killed |

Tests added after the third review:
- `test_r1_recovery_after_a_compromise_re_verifies_with_a_disjoint_frozen_set` covers compromise, a re-partition pinning the pilot and the compromised Tracks, and a superseding seal. The whole chain re-verifies, and F1 stays OPEN only for the unseen camera, which needs new footage. It also shows two refusals: a set that pins only the pilot is refused, and F1 refuses without the superseded seal's log;
- `test_an_adjudication_is_corrected_only_by_superseding_it`;
- `test_a_failed_seal_leaves_no_ledger_entry_and_can_be_retried`.
- A→B→C chain reuse (fifth review): `ledger_seal_reuses_earlier_frozen_tracks` and `f1_seal_chain_reuses_frozen_tracks`, in the recovery test; `test_f1_refuses_a_ledger_seal_entry_that_misstates_the_frozen_tracks`. In the targeted mutation run, all four chain guards were killed (two only after these tests were added).

**Source-mutation run on the trust-boundary repairs** (after the cold review of `afda79e`; `mut5`, each guard removed in turn):

| Guard removed | Result |
|---|---|
| phase completeness in the ledger (`require_phase_complete`) | killed |
| main completeness in ground truth | killed |
| pilot completeness in F1 | killed |
| main completeness in F1 | **survived, equivalent**: F1 rebuilds ground truth with `build_ground_truth`, which runs the same check on the same ledger prefix. The explicit call is kept for clarity |
| a cancelled assignment cannot be submitted | killed |
| cancellation needs an identical replacement | killed |
| no cancellation after a reveal | killed |
| reveal batch completeness | killed |
| canonical reveal packet | killed |
| adjudication needs a packet conflict (ledger) | killed |
| adjudication needs a label conflict (ground truth) | killed |
| reveal packet rebuilt in F1 | killed |
| freeze consistency inside `freeze_task` | killed |
| explicit freeze check in F1 | **survived, equivalent**: F1 also re-derives the frozen task with `freeze_task`, which runs the same check. Removing both copies together is killed |
| pilot rules equal the confirmed rules | killed |
| insufficient evidence must be removed | killed |
| a failing attribute must be resolved | killed |
| recall-sample population identity | killed |
| recall-sample regeneration | killed |
| a found recurrence keeps F1 open | killed |
| an unreviewed pair keeps F1 open | killed |
| cleanup after a failed seal write | killed |

**Second focused review of the repairs** (`4b7cb06`), guards added and removed in turn (`mut6`, plus two follow-ups):

| Guard removed | Result |
|---|---|
| ledger replay in F1 | killed (after adding `test_f1_replays_the_ledger_and_refuses_a_hand_written_cancellation`; it first survived because the only F1 forgery test was also caught by the reveal rebuild) |
| replay: payload must equal the rule's | killed (after adding `test_replay_refuses_a_reveal_entry_with_invented_conflict_keys`) |
| cancellation: fresh replacement | killed |
| cancellation: replacement annotator not already labelling | killed |
| reveals ignore cancelled assignments (liveness) | killed |
| ground truth: reason-only override | killed |
| recall minimum size | killed |
| recall seed derived | killed |
| committed-candidate binding in F1 | killed |
| candidate thresholds never lowered | killed |
| other candidate rules unchanged | killed |
| candidate vocabulary unchanged | killed |
| seal never overwrites outputs | killed |
| seal moves by hard link, not `os.replace` | **survived, equivalent**: the up-front existence check already refuses existing outputs, and the link only closes a race between that check and the move |
| ledger append rollback on failure (Codex review of `4b7cb06`) | killed (`test_a_failed_ledger_append_leaves_no_partial_entry_and_the_seal_retries`) |
| one replacement per cancellation | killed (`test_one_replacement_cannot_cover_several_cancellations`) |
| recall seed from sample-deciding content only (confirming review of `fc98b98`) | killed (`test_a_rejected_group_nonce_cannot_regenerate_the_recall_sample`) |
| candidate path pinned | killed (`test_the_candidate_path_is_pinned_to_the_committed_candidate`) |
| assignment rebuilt against its named corpus, partition and task (independent re-review of `6e3fe74`) | killed (`test_an_edited_assignment_that_drops_attributes_is_refused`) |
| labelled crops unchanged in the final corpus | killed (`test_labels_on_other_imagery_do_not_count`) |
| recall seed from Track identity only | killed (`test_a_confirmed_group_inside_one_partition_cannot_reseed_the_recall_sample`) |
| recall sample size fixed | killed (`test_a_recall_sample_larger_than_the_fixed_size_is_refused`; it first survived with only the too-small test) |
