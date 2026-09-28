# Stage 2 S2c.1 — Task + Corpus + Labels: implementation record

**Status:** Tooling delivered for review. **S2c.1 and F1 remain OPEN**: no operational corpus, annotators, pilot, freeze decision, main labelling, adjudication or frozen-test seal exists yet.
**Starting main:** `647d8f605d7c29bb6984408cb4d7e87eb5dcc163` (merge of PR #116, S2c.0).
**Governing:** ADR-013, ADR-014; qualification plan §3–§5, §16–§20 (R1, R2); MSR method v1; acceptance register F1; S2c.0 baseline record; S2c plan §6, §7.1, §8.2, §10, §22 (S2c.1 row).

## 1. Acceptance boundary, reconstructed

### 1.1 In scope

From the S2c plan's S2c.1 row, §10.2–§10.3, and qualification plan §3–§4 and R1 step 1:
- corpus and partition manifest schemas and tooling: hashing, site/date-block grouping, near-duplicate check, cross-partition recurrence audit, raw-evidence pin;
- annotation guide v1;
- a pilot drawn from the training partition only;
- agreement tooling;
- a vocabulary freeze that only merges or removes values, never adds;
- main labelling;
- sealing of the frozen test.

**Exit evidence:** the pilot and agreement reports, and the sealed manifest hash, which together close **F1**.

### 1.2 Out of scope

Candidate evaluation, threshold tuning and frozen-test scoring (S5); the harness (S2c.3); Model Packs, adapters, contracts and runtime (S2c.5–S2c.7); CUDA; Production.

## 2. Contradictions and interpretations found

| # | Finding | Resolution |
|---|---|---|
| C1 | Plan §10.2 has an evaluation-environment "appearance-similarity pass" propose recurrence pairs. The S2c.1 instruction forbids automated identity recognition in this slice. | S2c.1 implements reviewer-declared recurrence bookkeeping only. A future similarity pass (S2c.3 environment, never shipped, never a candidate's family) can only *propose* pairs: it must declare its model family, and a human must confirm before anything moves. No such pass is built here. |
| C2 | The plan says presence runtime output has "no Absent", but precision and false-discovery measurement need negative ground truth. | Ground truth records `present` / `absent` / `unscorable`. Runtime semantics are unchanged (present or Unknown). The guide (§3, §5) and the task module docstring state the distinction. |
| C3 | MAVI has no Site entity (Camera has only free-text `LocationName`), but the plan partitions by site. | `siteId` is a corpus-local pseudonym assigned by the Corpus Custodian. It is never a location name; the parser refuses non-pseudonym shapes. |
| C4 | Plan §7.1 defines `person-backpack` as carried "on the back or one shoulder" and lists handbag, shoulder bag and briefcase for `person-bag`. | The guide keeps the plan's definition: a backpack held in the hand is `absent` for both attributes, a known gap that the pilot measures. Totes and shopping/carrier bags count as carried bags, because they are carried bags other than backpacks and are not excluded. |
| C5 | Plan §7.1 says the vocabulary is frozen only by the annotation guide after the pilot, but the pilot thresholds were not numerically declared anywhere. | The candidate task file carries *proposed* thresholds: Krippendorff α ≥ 0.667 (Krippendorff 2004), at least 30 double-labelled units, merge-confusion share 0.25. The tooling refuses pilot assignments until the owner confirms them, and confirmation may raise but never lower a value. |
| C6 | Plan §10.2 frames the frozen test as "whole held-out sites or cameras plus held-out date blocks of seen ones". | Implemented as `heldOutSites` whole sites plus the latest `frozenLatestBlockFraction` of every other site's contiguous date blocks. The frozen test therefore includes cameras unseen elsewhere and a temporal hold-out. |
| C7 | Plan §10.2 asks that a recurring subject be "moved wholly into one partition, preferring training". A Track-level move would fragment the subject's site-date cluster, which is what §10.2 forbids. | When a link (confirmed recurrence or applied duplicate) spans partitions, every **cluster** it touches moves wholly to training, repeated to a fixpoint. Moves are one-way into training, so evaluation partitions never gain a leaking cluster. Everything is recorded, and nothing is deleted. The price: a heavily linked corpus shrinks its evaluation partitions, and the partition checks record that as a limitation. |
| C8 | S1.4 (register B1–B6) is still open, so the Evidence Set selector or profile could still change. | The corpus manifest carries one raw-evidence pin, and mixing pins is refused. A change re-derives affected crops, which is the plan's stop condition. |
| C9 | Status text in the roadmaps, parent plan, register and S2c.0 record still said "S2c.0 in progress; S2c.1 not authorized" after PR #116 merged. | Updated to the merged state (S2c.0 closed at `647d8f6`; S2c.1 in progress; F1 OPEN). No row status changed. |
| C10 | Plan §10.2 describes recurrence by crop-SHA pairs. | The audit records Track UUIDs; each Track owns its crops through the manifest. The link is the same and survives crop re-derivation under a new pin. Reviewer recall is bounded, so F1 also needs a recorded `recallSample` (a second review of random cross-partition pairs). With no biometric matcher, by design, recall remains an estimate. |
| C11 | The initial F1 checker computed PASS from hashes and counts asserted in the record. A second review then showed that retained reports could be edited and re-hashed, that unlabelled attributes went unchecked, and that re-sealing after a compromise went undetected. | The record names artefacts by SHA-256 only. `check-f1 --store` recomputes the pilot report, the main agreement report and both ground-truth views from the retained assignments, batches and adjudications, as of the ledger state at the ground truth. It requires equality, the seal's hashes and member set, every task attribute double-labelled, and main labelling under the frozen guide. Seals are ledger events: a re-seal must supersede the latest seal, the superseded seal must be compromised, and the new set must differ. Without the store the verdict is OPEN. |
| C13 | Ground truth could be built from a subset of the registered batches. | Every registered main batch is required. Final labels must be consistent with the final subject validity. |
| C14 | Residual trust in the custodian's store (an access log recreated by hand) and frozen-test agreement staying outside F1. | Recorded in the tooling README §10. The mitigation is to commit `accessLogHead` on every log change. |
| C15 | Third review: R1 recovery (re-partition and re-seal) could never pass F1; a corrected adjudication or a failed `seal` run blocked a ledger permanently. | The pilot is verified on its own partition, and its Tracks must be in final training, kept there by `pinnedTrainingTrackIds`. Adjudications are corrected by explicit supersession. `seal` appends `seal-created` only after every file is written. Custodian-side truncation of either log remains a recorded residual: commit the F1 record at sealing so Git anchors the heads. |
| C16 | Fourth review: a superseding frozen set could reuse compromised Tracks (only its hash had to differ). | Both member sets are recomputed from their partitions and must be disjoint. Superseded by C18 (exposed Tracks, not only frozen ones). On a corpus whose every site contributed to the old frozen set, the recovered set cannot keep an unseen camera. F1 then stays OPEN on that point, and genuine recovery needs new footage. |
| C17 | Fifth review: disjointness was checked only against the immediate predecessor, so an A→B→C chain could restore A's compromised set. | `seal-created` records each seal's frozen Track IDs. Sealing refuses reuse of any earlier seal's Tracks. F1 recomputes every seal's members from its own retained corpus and partition and refuses any Track appearing twice in the chain. |
| C18 | PR review (automated, three P1s): the seal could carry a later ledger head than its ground truth; a replacement frozen test could use Tracks that were open to evaluation; F1 did not re-derive the frozen task from the owner decision. | The seal head must equal the ground truth head, and F1 refuses any label event after it. `seal-created` records the exposed Track IDs; a replacement frozen set may contain none of them (ledger, `verify_superseding_seal`, F1). R1 recovery therefore needs new footage, supported by `excludedFromFrozenTrackIds` and a corpus revision. F1 requires the frozen task to equal `freeze_task(candidate, pilot, owner decision)`. |
| C12 | The frozen-access `stage` cannot be detected by the tool. | It is recorded as the actor's declaration (honour system). Custody, logging before release and log review make a false declaration visible. Only `seal` may create the access log, so it cannot be silently reset. |

## 3. What is delivered

**Tooling** in `tools/qualification/attributes/corpus/`, with its README and command line `tools/qualification/attribute_corpus.py`:
- the candidate task and vocabulary: `data/attribute-task-v1-candidate.json`, following plan §7.1 exactly;
- corpus manifest v1;
- the four-way cluster-aware partitioner and its verifier;
- recurrence and duplicate audits (exact SHA-256 and dHash-64);
- the annotation workflow, with a hash-chained independence ledger;
- adjudication and ground truth;
- agreement: raw, Cohen's κ and Krippendorff's α, reported for full category, scorability and value;
- the pilot sampler, pilot report and owner-decision freeze;
- the frozen-test seal, the access log (created only by sealing), and the evaluation view bound to the seal;
- the diversity report;
- the F1 checker, which re-verifies the retained records (`check-f1 --store`).

**Documents:**
- the annotation guide v1, `docs/qualification/stage2-s2c/annotation-guide.md`;
- the F1 evidence record, `docs/qualification/stage2-s2c/corpus/f1-evidence-record.json`, which the checker computes as OPEN.

**Guards:**
- `tools/verify_repo.py` refuses tracked images in the S2c corpus areas;
- a test proves the tooling imports no network module;
- parsers refuse local paths and locators inside records.

**Tests:** `tools/qualification/tests/test_attribute_corpus_*.py`, run by the Quality Gate's "S1.4 qualification tooling" step, on synthetic fixtures only. They cover all ten requested mutation classes, and a source-mutation run is recorded in the tooling README §11.

**Dependencies:** none added. Pillow is already a declared MAVI Vision dependency.

## 4. Frozen vocabulary state

The vocabulary is **not yet frozen**: freezing requires the pilot. The candidate vocabulary is exactly plan §7.1.

| Attribute | Values |
|---|---|
| `person-upper-colour`, `person-lower-colour` | black, blue, brown, green, grey, orange, pink, purple, red, white, yellow; conditional `multicolour` |
| `person-backpack`, `person-bag` | present / absent (ground truth) |
| `person-headwear` | present / absent (ground truth); the attribute itself is conditional |
| `vehicle-colour` | beige, black, blue, brown, green, grey, orange, red, silver, white, yellow; conditional `multicolour` |

**Pre-declared changes** — the only ones the freeze may apply:
- value merges: grey/white and brown/orange (person), grey/silver, beige/brown and beige/white (vehicle);
- the backpack+bag attribute merge;
- removal of `multicolour`;
- removal of any attribute.

**Excluded:** age, gender, ethnicity, face attributes or identity, hair or sleeve length, garment style, vehicle type or make/model, plate text, re-identification.

## 5. Evidence available vs missing

| Needed for F1 | State |
|---|---|
| Annotation guide v1 | delivered; its frozen SHA-256 is recorded only at freeze |
| Corpus manifest, partition manifest, recurrence and duplicate audits | tooling delivered; **no operational corpus** |
| Pilot agreement report and freeze decision | tooling delivered; **no annotators or pilot** |
| Main agreement and adjudication, ground truth | tooling delivered; **not executed** |
| Frozen-test seal and access log | tooling delivered; **not executed** |
| Camera/site support (≥ 3 cameras per partition; an unseen frozen camera) | checked by the partitioner and F1 checker; **no data** |
| Corpus Custodian and annotators named (S2c.0 record §4) | **not yet designated** |
| Retained-record store for `check-f1 --store` | **does not exist** (nothing to retain yet) |
| Recurrence recall sample | tooling delivered; **not executed** |

Synthetic fixtures prove the mechanisms only. They are never F1 evidence: the checker refuses any `corpusKind` other than `operational`.

## 6. 500-camera foundation

S2c.1 does not need footage from 500 cameras, and claims nothing about scale. It records per-source site, camera, date, lighting, setting, frame size and source class, and per-crop role and size. The diversity report makes camera/site generalisation analysis possible later, and the partitioner keeps camera/site structure intact (no iid split) so that held-camera results stay meaningful. Workload and capacity belong to S2c.2, S2c.3 and S2c.9 (plan §14.1).
