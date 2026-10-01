# S2c Slice B preparation — public-source feasibility pilot (first run), 2026-10-01

**Baseline:** `main@cef1b6585da125428c371a3af3eeca8d7ce8e09d`.
**Governing documents:**
- execution plan `docs/superpowers/plans/2026-09-30-stage2-s2c-real-qualification-execution.md` §5 and §17 (Slice B);
- execution record `real-qualification-execution-record.md` §2–§3 and §4.3.12;
- B0 record `s2c-b0-source-acquisition-record.md` §1–§9;
- `tools/qualification/source_acquisition/README.md`;
- `tools/qualification/attributes/corpus/README.md`;
- the annotation guide.

**Operator:** a Claude Code session, on Hari Om's instruction of 2026-10-01. No delegation from the Corpus Custodian (R-3, Aarav) is recorded, so R-3's confirmation of this run is pending. The operator holds no reviewer role, and its candidate notes below are recommendations, not review decisions.

## Status

This is a bounded feasibility pilot. It is **not** Slice B corpus execution. It did not:
- admit or acquire any file;
- create any VideoAsset, ProcessingRun, Track, Observation, label, annotation, adjudication, partition, task freeze or seal;
- train, tune, evaluate or select anything;
- read any frozen-test material, because none exists.

The following are unchanged:
- **F1** stays OPEN (`corpus/f1-evidence-record.json`).
- **Both MSRs** stay `PLANNED`.
- **S1.4** B1–B6 stay OPEN and separately governed.
- **Accountable roles** are as recorded in execution record §2: R-1/R-3/R-4/R-5/R-6 Aarav; R-2/R-7 Hari Om; Savita as independent annotator. Hari Om remains repository owner.

## 1. Inventory of existing source material

| Item | Finding | Kind |
|---|---|---|
| Source footage (any provider) | None discovered, admitted or acquired before this run. B0 §9 records that no live discovery ran, and no receipt or source-media file exists anywhere on record. | — |
| Controlled store for source media | **Not designated.** The only designated store, `D:\MAVI-Controlled\Models\S2c\2026-01` on host `QUEENSGAMBIT`, holds candidate **model** bytes (execution record §4.3.9–§4.3.11). It is not a footage store. | — |
| Committed corpus records | `corpus/f1-evidence-record.json` only: OPEN, every hash `null`. | record |
| `tests/fixtures/visual-attributes/**` | Synthetic fixtures. They never count as operational F1 evidence (B0 §1.4; corpus README). | synthetic fixture |
| Source-acquisition helper tests | Fake transport only. These are tooling demonstrations, not acquired bytes. | tooling demonstration |

**No acquired source bytes exist, so there is nothing to re-verify before downloading, and no duplicate risk.**

## 2. Missing permissions, custody inputs and decisions

None of these is supplied by this record. Apart from the User-Agent contact, which the operator chose for this run only and which is marked as such, none is defaulted.

| Input | Needed for | Owner | Status |
|---|---|---|---|
| Controlled source-media store, outside Git, on a host that is retained and independently reviewable | any acquisition; custody | Owner / R-1 (B0 §10), operated by R-3 | **MISSING** |
| Named rights reviewer for footage (`PERMITTED_FOR_PILOT_ACQUISITION` determinations) | admission | R-5, or a delegate named by the owner | **MISSING** for footage. R-5's recorded determinations cover model evaluation only. |
| Named privacy reviewer, with a basis per file | admission | owner | **MISSING**: no privacy reviewer is named |
| `freshnessReferenceDate`: the latest public release date of any checkpoint in the evaluated set | `operational-candidate` role | R-1 | **MISSING**. The record holds no checkpoint release dates, and no date is proposed here. |
| Acceptance of the B0 §1 reading of "MAVI-acquired operational footage" | whether public files may be operational at all | R-2 / owner | **PENDING**. If it is rejected, public sources are reference/training only (stop condition S5). |
| Operator contact for the User-Agent | discovery | Owner / R-1 (B0 §10) | **Operator-chosen for this run, pending owner confirmation:** the public repository URL, not a personal address |
| Decision on commissioned or owner-captured footage | the fallback when public sources are insufficient | owner | **PENDING** (§6) |

Every discovered item is therefore at most `DISCOVERED` or pending. **No rights or privacy decision is recorded or implied**, and nothing can reach `ADMITTED_FOR_PILOT`.

## 3. Discovery run

**Scopes.** The scopes were predeclared in the operator run note before any output, taken verbatim from B0 §6, with 20 results per scope:

| Id | Scope | Result | Discovery report SHA-256 |
|---|---|---|---|
| P1 | search `traffic India 2026` | 3 video files | `3d40f18508266c2fa85639bf98566205f2ebaefea2682b84b51d041d44301ef5` |
| P2 | search `street India 2026` | 12 files' metadata retained; the run hit the operator's 900 s wall-clock limit during rate-limit back-off, before its report was written | — (per-file evidence in §4) |
| P3 | search `pedestrians market India` | HTTP 429; the helper failed closed after its 30 s and 60 s back-offs | — |
| P4 | category `Category:Videos of streets in India` | 0 video-file titles. The query (`list=categorymembers`, `cmtype=file`) lists only files *directly* in the category, at most 20, and the helper keeps only video-file titles. It is unverified whether the category's videos sit in subcategories or whether its first 20 direct files are non-video, because the helper does not retain the raw list response. | `83be97152d4d033344c6100af64f5b7e3004a39f408fb7c74f92748ad7fb569a` |
| P5 | category `Category:Videos of road traffic in India` | HTTP 429; failed closed | — |
| S1, S2 | secondary non-India pool | not run (rate limiting) | — |

**Live parser validation.** B0 §9 deferred this. It now passes: real Commons `imageinfo` / `extmetadata` / `revisions` responses parse into the documented fields (MIME type, dimensions, duration, size, SHA-1, licence, author, `DateTimeOriginal`). No tool change was needed.

**Rate limiting.** After the run, a single read-only request was repeated every 2 minutes for 10 minutes, using the helper's own User-Agent. Every request returned HTTP 429 (`retry-after: 5–7`) with Wikimedia's "too many requests" message. B0 §9 saw the same from a different container. Requests that slow cannot be caused by the helper's request rate. The result is **consistent with** a limit on this session container's shared egress address. A User-Agent-based throttle, or a penalty lingering from the earlier burst, is not excluded. No acquisition-tool repair is justified, because the helper's pacing is not shown to be the cause.

The pilot reached **stop condition S4** (rate limiting prevents metadata access) **in this execution environment**. That is not a finding about Commons from an ordinary network.

**Custody of this run's evidence.** Discovery reports and per-file metadata evidence were written to a session-local store outside Git. The run note holds the predeclared scopes, followed by the verbatim run outcomes and probe results, appended after the run; its final SHA-256 is `663481c52a3956200bb2a085132445f66fa7707d0458539340a3d55a498d75d7`. That store is **ephemeral and is not the controlled store**: the identities below are recorded so a rerun can be compared with them, but the bytes are not retained custody. No media bytes were downloaded.

## 4. Candidates described (metadata and title only; no model, no frames viewed, no human review)

The last column is an **operator note**: a recommendation for the named reviewers, not an admission state.

| Page id / revision | Title (abridged) | Licence (machine class) | Duration | Resolution | Declared capture | Assessment |
|---|---|---|---|---|---|---|
| 155325362 / 966182342 | *Patanga* (feature film; cast named in the title) | `pd` | 149.3 min | 656×480 | 2016-02-12 | Recommend reject: a feature film (staged fiction), not street footage. The declared 2016 date cannot be the capture date of a film of that era. |
| 80275825 / 776443974 | *A Native Street in India* (1906) | `pd` | 2.9 min | 1920×1080 | 1906 | Recommend reference only at most: archival; it can never meet freshness |
| 190599393 … 190599574, 9 files | *Developer Skill Development Program India 2025*, videos 02–28 | `cc-by-4.0` | 4–78 s each (2.7 min total) | mostly 1080×1920 portrait | 2026-03-27 | Recommend not suitable: one event series by one uploader, so at most one site; mostly portrait clips; the titles indicate a programme event, not street or vehicle scenes |
| 186746471 / 1187910038 | Holi street procession, Kolkata 2026 | `cc-by-sa-4.0` | 26 s | 3840×2160 | 2026-03-10 | Possible operational candidate after review: street procession, people and vehicles likely; festival crowd; a single short clip; viewpoint unknown without frames |
| 186711192 / 1187910134 | Iftar ambience, street in Kolkata | `cc-by-sa-4.0` | 12 s | 1080×1920 | 2026-03-19 | Possible after review: street scene with people; portrait; very short. Same author as the Holi clip, which weakens site independence. |
| 194270929 / 1236254422 | Narmada bridge piers | `cc-by-4.0` | 10 s | 1080×1920 | 2026-06-21 | Recommend not suitable: landscape or bridge, not a person/vehicle scene |
| 186965042 / 1235557773 | Times Square billboard | `cc-by-sa-4.0` | 30 s | 2304×1980 | 2026-03-25 | Recommend not suitable: a billboard scene outside India |

Share-alike (`cc-by-sa-4.0`) is a machine pre-classification only. Whether SA terms are compatible with operational and derivative use is an R-5 question.

**Tally against the B0 §6 targets.**

| Measure | Target | Found |
|---|---|---|
| Candidates | 40–60 reviewed | 15 described (metadata only); **0 reviewed** |
| Admissible operational-candidate footage | ≥ 30 min (S1); 1–2 h goal | **0 min.** Nothing is admitted, because no reviews exist. Even on the most generous reading, the plausible candidates total 38 s. |
| Independent sites | ≥ 4, none above ~40 % of duration | At most 1–2 plausible (both in one city, by one author) |
| Viewpoint | fixed or slow | None evidenced (no frames viewed) |
| Capture-date evidence | reviewed interval, medium/high confidence, `CAPTURE_AFTER_REFERENCE` | Declared dates only, which are unreviewed. One declared date cannot be a capture date (*Patanga*). The reference date is missing. |
| Person/vehicle visibility | adequate for attribute crops | Unassessed without frames; the two candidates are crowd or festival scenes |

## 5. Feasibility result

**Outcome: INCOMPLETE in this environment (S4). Preliminary indications are that public Commons video is insufficient** for a first operational corpus. They rest on 15 described files from 2 of 5 primary scopes.

- The sample is small and this is not a final determination. But every observed candidate falls into one of four kinds:
  - archival film, which can never be fresh;
  - single-event clips;
  - short phone-style clips, mostly portrait;
  - unrelated scenes.
- None *evidences* the fixed or slowly moving viewpoint that MAVI's camera-based Tracks presuppose; no frames were viewed.
- The corpus checks add structural needs that short single-uploader clips rarely meet:
  - at least 3 cameras in **each** of training, tuning, selection and frozen-test (`check-f1`);
  - a frozen-test camera unseen elsewhere, for example through a held-out site;
  - site/date-block clusters, so that partitions can be filled without splitting a site's block.
- Recent declared capture dates would at best support a *disjointness argument*. They never establish independence from candidate training data (B0 §1.3).

**Not established:** any operational corpus, F1 PASS, rights or privacy approval, annotation, adjudication, or a final "insufficient" ruling under S1, S2 or S3.

## 6. Minimum additional footage if public sources are insufficient

### 6.1 Hard tool requirements (enforced by the corpus tooling)

- At least **3 cameras in every partition**: training, tuning, selection and frozen test (`check-f1`, `minimumCamerasPerPartition`).
- A **frozen-test camera unseen in any other partition** (`requireUnseenFrozenCamera`). This can be achieved through a held-out site (`heldOutSites` ≥ 0 is a policy choice) or through a camera that appears only in frozen blocks.
- Every partition non-empty, and no site/date-block cluster split across partitions. A cluster is `(siteId, dateBlock)`, and a block spans `dateBlockDays` days from the policy's `dateEpoch`.
- A temporal hold-out exists only if a site has enough blocks: the number of frozen blocks per site is `int(blocks × frozenLatestBlockFraction)`, so a small fraction with few blocks yields none.

The floor these rules impose is much smaller than the brief below. As few as about two sites with three cameras each can satisfy it, because cameras from several sites fill a partition, and the same cameras can serve training, tuning and selection in different date blocks. Camera floors do not establish statistical adequacy (plan §5).

### 6.2 Recommended capture brief (planning choices for owner decision, not tool minimums)

| Item | Recommendation | Reason |
|---|---|---|
| Sites | ≥ 5 independent sites, pseudonymised | B0 §6's ≥ 4-site diversity target, plus one site that can be held out whole, giving an unseen frozen camera with margin |
| Cameras | ≥ 3 fixed cameras per site (mounted or tripod) | any one site's cluster can then supply a partition's camera floor on its own |
| Date blocks | recordings in ≥ 4 distinct date blocks per non-held-out site, under the partition policy's `dateBlockDays`, covering daytime and night/low light. Several recording days inside one block count as one block. | lets each site contribute to training, tuning and selection, and to a temporal frozen hold-out |
| Duration | ≥ 10 min per camera per date block, at sites with steady pedestrian and vehicle flow | planning estimate (≈ 10 h raw at this shape). The B0 1–2 h target only tests feasibility. Whether the pilot's double-labelled units per attribute are reachable (the proposed `minimumDoubleLabelledUnitsPerAttribute: 30` is owner-unconfirmed) is shown by the training pilot. Minimum support itself is fixed later from validation/tuning evidence (qualification plan §5, R1). |
| Subjects | full-body pedestrians and whole vehicles, large enough in frame for the annotation guide's scorability rules. A resolution floor such as 720p is a suggestion, not a recorded requirement. | attribute crops must be scorable |
| Capture records | per-file capture start/end in UTC with the camera clock checked, the camera's IANA timezone, and site and camera pseudonyms | the reviewed capture interval; freshness holds by construction for commissioned capture |
| Privacy basis | signage or consent basis per site, recorded by the named privacy reviewer; no face or plate close-ups as subjects | B0 §7 |
| Custody | the original files, unmodified, in the designated controlled source store with SHA-256 on receipt | per-file custody identity, bound through the receipt SHA-256 in the manifest source row (B0 §5 step 3). This is separate from the corpus raw-evidence pin (§7). |

Commissioned or owner-captured video is the B0-preferred operational route (B0 §2.2). It is the only route in which disjointness holds by construction.

## 7. Raw-evidence identity for subsequent corpus processing

The corpus manifest has a single `rawEvidencePin` field for the whole corpus, so it cannot record crops from two pins. Its contents are the vision pipeline profile digest and the Evidence Set selector and scorer versions (`manifest.py`); it is not a source-file hash. At this baseline the pin's inputs are:

| Pin field | Value at `main@cef1b65` | Source |
|---|---|---|
| `visionPipelineProfileSha256` | the profile digest that the first real ProcessingRun records as `pipelineProfileSha256` for `src/vision/config/pipelines/phase1-detection-tracking-v1.json`. File bytes at this baseline: SHA-256 `503225be736d9622ed110aa69e49a83dde4ae02c858d5e8fa41e527b1c4b23fb` | worker provenance (`mavi_vision/worker/client.py`) |
| `evidenceSelectorVersion` | `evidence-selector-v1-two-tier` | `mavi_vision/evidence/policy.py` |
| `evidenceScorerVersion` | `quality-v2` | as above |

The Corpus Custodian must populate the pin from the ProcessingRun's recorded `pipelineProfileSha256` and selector/scorer versions, not from this table. `manifest.py` validates only the pin's shape and does not cross-check it against provenance, so this is a custody duty, not an automatic check. If the profile, selector or scorer changes before or during corpus processing (S1.4 is open), affected crops are re-derived under the new pin. This record does not claim S1.4 closure.

## 8. Next bounded Slice B step (proposed; requires owner action)

1. **Owner inputs**, all from §2:
   - R-3 designates the controlled source store;
   - the owner names the footage rights reviewer and the privacy reviewer;
   - R-1 supplies `freshnessReferenceDate` with evidence;
   - R-2 rules on the B0 §1 interpretation.
2. **Owner decision**, which can run in parallel: whether to start a commissioned or owner-captured footage brief along the lines of §6.2. The preliminary indications in §5 suggest that public sources are unlikely to supply fixed multi-camera sites, but the completed rerun is the evidence for that.
3. **Complete the public pilot from the Development host**, if the owner still wants it:
   - re-run the *same* predeclared scopes P1–P5 (then S1–S2) with the existing helper from a non-shared network;
   - record the run note and report hashes;
   - have the named reviewers complete the decisions template;
   - acquire admitted files only;
   - apply the §4 tally.
   
   P4 lists only direct members and returned no video titles. If the owner wants subcategory members, that is a **new predeclared scope** (for example the named subcategories), recorded before the rerun and never chosen from results.
4. Only after footage passes admission does the B0 §5 ingestion handoff start Slice B proper.

No tooling was changed, and nothing here may be merged without authorization.

## 9. Inconsistency noted in an existing record (not changed here)

B0 §5 step 4 describes the corpus raw-evidence pin as "the retained original's SHA-256 from the receipt". `manifest.py` defines the pin as the pipeline profile digest plus the selector and scorer versions, and B0 §5 step 3 already binds the receipt SHA-256 per source. The B0 wording should be corrected in a separate change.
