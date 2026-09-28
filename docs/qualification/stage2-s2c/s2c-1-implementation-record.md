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
| C7 | Plan §10.2 asks that a recurring subject be "moved wholly into one partition, preferring training". | Every connected set of linked Tracks (confirmed recurrence or applied duplicate) that spans partitions moves wholly to training. Moves are one-way into training, so evaluation partitions never gain a leaking Track. Everything is recorded, and nothing is deleted. |
| C8 | S1.4 (register B1–B6) is still open, so the Evidence Set selector or profile could still change. | The corpus manifest carries one raw-evidence pin, and mixing pins is refused. A change re-derives affected crops, which is the plan's stop condition. |
| C9 | Status text in the roadmaps, parent plan, register and S2c.0 record still said "S2c.0 in progress; S2c.1 not authorized" after PR #116 merged. | Updated to the merged state (S2c.0 closed at `647d8f6`; S2c.1 in progress; F1 OPEN). No row status changed. |

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
- the frozen-test seal, access log and evaluation view;
- the diversity report;
- the F1 checker.

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

Synthetic fixtures prove the mechanisms only. They are never F1 evidence: the checker refuses any `corpusKind` other than `operational`.

## 6. 500-camera foundation

S2c.1 does not need footage from 500 cameras, and claims nothing about scale. It records per-source site, camera, date, lighting, setting, frame size and source class, and per-crop role and size. The diversity report makes camera/site generalisation analysis possible later, and the partitioner keeps camera/site structure intact (no iid split) so that held-camera results stay meaningful. Workload and capacity belong to S2c.2, S2c.3 and S2c.9 (plan §14.1).
