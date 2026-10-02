# S2c Slice B preparation — public-source feasibility pilot (first run), 2026-10-01

**Baseline:** `main@cef1b6585da125428c371a3af3eeca8d7ce8e09d`.

**Historical record; current policy amendment, 2026-10-02.** This document retains the first run's observations, hashes, lost-evidence disclosures and as-of-run pending inputs. The owner has since closed the B0 S1 campaign (63/63 reviewed; 38 `REJECT_OPERATIONAL_QUALIFICATION`, 15 `REFERENCE_ONLY`, 10 `REJECTED`; 0 operationally admissible seconds) and adopted C+ in owner-decision record §8 and ADR-015. Nothing is `ADMISSIBLE` or `FROZEN_QUALIFICATION`. Pending eligibility language and §8's proposed continuation below are historical, not current instructions: do not reopen the closed campaign. New public work requires a new purpose-specific declaration. §6.2's roughly ten-hour brief is superseded for future planning by ADR-015 §6's bounded two-hour qualification-candidate proposal; neither is a minimum or evidence of statistical adequacy. Commissioning alone does not establish disjointness; ADR-015 §3's verified chronology, custody and exposure conditions apply.
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

**Later owner decisions (2026-10-01, after this run).** `s2c-owner-decisions-2026-10-01.md` records decisions that the owner made after this run and after the bundle was placed on the Development host. They take effect from that decision. This record keeps its as-of-run statements, and the decisions do not re-attribute the run:
- **Roles.** R-1 and R-3 pass to Hari Om from the decision. Aarav held both during this run, and the role statement above stays the as-of-run record.
- **Footage reviewers.** Hari Om is named footage rights reviewer and footage privacy reviewer. Per-file determinations are still required, share-alike questions go to R-5 first, and no file is reviewed or admitted.
- **Directories.** The controlled source-media and acquisition directory **locations** are designated. Two parts of the §2 "Controlled source-media store" row stay open: "independently reviewable", while no independent reviewer exists, and the media-placement method needed before any `acquire`.
- **Custody.** Local custody of the bundle (§4a) is recorded, with a fresh automated re-verification on the Development host.
- **No retroactive claims.** No delegation, approval or ratification of this run is claimed. R-3's confirmation stays pending. If R-3 Hari Om gives it, it is a later ratification by the person who instructed the run.
- **Independence.** From the decision the same person holds R-1, R-2, R-3 and R-7. The resulting independent-review conflicts are recorded there (§2) and remain open.
- **Eligibility.** §8 below says "R-2 rules on the B0 §1 interpretation". With R-1 and R-2 now one person, that ruling can only be recorded as an owner decision, not an independent review. It remains PENDING.
- **Freshness.** `freshnessReferenceDate` remains MISSING, with a provisional proposal only.

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
| P2 | search `street India 2026` | 12 files' metadata retained; the run hit the operator's 900 s wall-clock limit before its report was written (the console log shows only `Terminated`, `exit=124`; the session observed HTTP 429 back-off, which the helper does not log) | — (per-file evidence in §4) |
| P3 | search `pedestrians market India` | HTTP 429; the helper failed closed after its 30 s and 60 s back-offs | — |
| P4 | category `Category:Videos of streets in India` | 0 video-file titles. The query (`list=categorymembers`, `cmtype=file`) lists only files *directly* in the category, at most 20, and the helper keeps only video-file titles. It is unverified whether the category's videos sit in subcategories or whether its first 20 direct files are non-video, because the helper does not retain the raw list response. | `83be97152d4d033344c6100af64f5b7e3004a39f408fb7c74f92748ad7fb569a` |
| P5 | category `Category:Videos of road traffic in India` | HTTP 429; failed closed | — |
| S1, S2 | secondary non-India pool | not run (rate limiting) | — |

**Live parser validation.** B0 §9 deferred this. It now passes: real Commons `imageinfo` / `extmetadata` / `revisions` responses parse into the documented fields (MIME type, dimensions, duration, size, SHA-1, licence, author, `DateTimeOriginal`). No tool change was needed.

**Rate limiting.** Repeated HTTP 429 responses blocked discovery from this environment; the underlying cause was not established. After the run, a single read-only request with the helper's own User-Agent was repeated every 2 minutes for 10 minutes, and every request returned HTTP 429 (`retry-after: 5–7`) with Wikimedia's "too many requests" message. No acquisition-tool repair is made, because no tool defect was shown.

The pilot reached **stop condition S4** (rate limiting prevents metadata access) **in this execution environment**. That is not a finding about Commons access from other environments.

**Custody of this run's evidence.** The run wrote to a session-local store outside Git, which is ephemeral and is not a controlled store. No media bytes were downloaded. Everything still available was exported into an evidence bundle and delivered to the owner for retention outside session storage (§4a).

## 4a. Evidence bundle

**Bundle:** `mavi-s2c-b-source-pilot-evidence-2026-10-01.tar.gz`, SHA-256 `82fe15b714111c968d676bdd36b55598d5235697b0200d5954ce2b5350760331`. It was delivered to the owner as a download from the session on 2026-10-01. **Durable custody depends on the owner storing it** on the Development host or another retained store; the session copy is ephemeral.

**Manifest:** `MANIFEST.json` inside the bundle, SHA-256 `60e4edc8a3ae18447d8e44cb4bdaf66d56cb5d94b4a13529ec50abef9a97d599`. It lists the following, with path, SHA-256, size, UTC modification time and role for every file:
- 15 Commons file-metadata API responses;
- 2 discovery reports and their 2 unreviewed decisions templates;
- the run note;
- the P1 console output, transcribed from the session transcript because it was not written to a file;
- the P2–P5 console log;
- the rate-limit probe log and its script.

It also records each scope's completion status and the evidence already lost.

| Scope | Status | Items described | Discovery report |
|---|---|---|---|
| P1 | complete | 3 | `3d40f185…01ef5` |
| P2 | **partial**: terminated by the operator's 900 s wall-clock limit (the retained log shows only `Terminated`, `exit=124`; HTTP 429 back-off was observed in the session but not logged) | 12. The scope is attributed by file modification time, because the helper does not record scope per evidence file. | none written |
| P3 | not completed: HTTP 429 on the search request | 0 | none |
| P4 | complete: 0 video-file titles among direct file members | 0 | `83be9715…b569a` |
| P5 | not completed: HTTP 429 | 0 | none |
| S1, S2 | not started | — | — |

**Run note.** Its final SHA-256 is `663481c52a3956200bb2a085132445f66fa7707d0458539340a3d55a498d75d7`. The predeclaration's hash was not captured when it was written, before P1. `bc4b0c2cf9dc54319bda31a1591c6d16fa9465fa759c047d7a1cbae511b03339` is **reconstructed**. It is the SHA-256 of the note's first 1,346 bytes. These are the bytes before the `\n## Run outcomes` sequence that starts the section appended after the run (in Python, `note.split(b"\n## Run outcomes", 1)[0]`). The reconstruction assumes the predeclaration was not edited before that section was appended, and nothing independent confirms that assumption.

**Evidence already lost.** None of the following can be recovered:
- the raw search and category list responses for every scope, because the helper never retains them, so the ordered candidate lists, including filtered-out non-video titles, are unavailable;
- P2's discovery report and decisions template, which were never written;
- exact per-scope start and end times for P2–P5, of which only file and log modification times remain;
- full HTTP 429 headers and bodies, because the helper reports only "HTTP 429" and the probe log keeps the first 200 bytes of each body;
- the helper's internal back-off timings, which are not logged;
- the original P1 console output, which was not written to a file. `logs/discovery-p1-console.txt` is a transcription from the session transcript, not the original capture.

**Integrity re-verification (2026-10-01).** The archive delivered to the owner (session download `7eefcd11-7a1e-44f8-8081-9c1f2090b5d8`) was re-checked in the session after delivery. The download ID, the delivery time and the build-time hash output are session observations, not bundle evidence:
- It is the same file that was delivered: 21,782 bytes, unchanged since it was built at 12:32:54 UTC, eight seconds before delivery. It was not rebuilt.
- Its SHA-256 is the full 64-hex-digit digest above, which matches the value printed when it was built.
- A fresh extraction contains 24 payload files plus `MANIFEST.json`. Every file the manifest lists exists and matches its recorded size and SHA-256, and every payload file is listed.
- The manifest's own SHA-256 matches the value above.
- All 15 evidence-file references in the scopes resolve to files in the bundle.
- Both discovery reports are named by their own SHA-256.
- The reconstructed predeclaration hash is reproduced by the rule stated above.

Two limitations remain:
- No receipt confirms that the owner retained the file, so **durable custody is not established**.
- The manifest describes the reconstruction less precisely than this record.

**Reproducibility.** These hashes identify exactly the bytes retained in the bundle. A future rerun is a new observation, and is not expected to reproduce them: Commons page revisions, search ranking, category membership and rate limiting all change over time.

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

**Outcome: INCOMPLETE in this environment (S4). Public-source sufficiency is UNRESOLVED.** Only 15 files were described, from 2 of 5 primary scopes, and none was reviewed. **0 minutes of footage were admitted**, and 0 media bytes were acquired.

- **Observations from this sample only, with no conclusion drawn.** Every described candidate falls into one of four kinds:
  - archival film, which can never be fresh;
  - single-event clips;
  - short phone-style clips, mostly portrait;
  - unrelated scenes.
- None *evidences* the fixed or slowly moving viewpoint that MAVI's camera-based Tracks presuppose; no frames were viewed.
- The corpus tooling's structural constraints (§6.1) apply to whatever footage is eventually admitted:
  - at least 3 cameras in **each** of training, tuning, selection and frozen-test (`check-f1`);
  - a frozen-test camera unseen elsewhere, for example through a held-out site;
  - site/date-block clusters, so that partitions can be filled without splitting a site's block.
- Recent declared capture dates would at best support a *disjointness argument*. They never establish independence from candidate training data (B0 §1.3).

**Not established:** any operational corpus, F1 PASS, rights or privacy approval, annotation, adjudication, or a ruling either way on public-source sufficiency under S1, S2 or S3.

## 6. Corpus-tool constraints and a recommended acquisition brief

§6.1 states what the corpus tooling enforces on any footage. §6.2 is a recommended brief for commissioned or owner capture, for use if the owner decides public sources are insufficient or chooses to proceed in parallel. It is a set of planning choices, not tool requirements.

### 6.1 Hard tool requirements (enforced by the corpus tooling)

- At least **3 cameras in every partition**: training, tuning, selection and frozen test (`check-f1`, `minimumCamerasPerPartition`).
- A **frozen-test camera unseen in any other partition** (`requireUnseenFrozenCamera`). This can be achieved through a held-out site (`heldOutSites` ≥ 0 is a policy choice) or through a camera that appears only in frozen blocks.
- Every partition non-empty, and no site/date-block cluster split across partitions. A cluster is `(siteId, dateBlock)`, and a block spans `dateBlockDays` days from the policy's `dateEpoch`.
- A temporal hold-out exists only if a site has enough blocks: the number of frozen blocks per site is `int(blocks × frozenLatestBlockFraction)`, so a small fraction with few blocks yields none.

The floor these rules impose is much smaller than the brief below. As few as about two sites with three cameras each can satisfy it, because cameras from several sites fill a partition, and the same cameras can serve training, tuning and selection in different date blocks. Camera floors do not establish statistical adequacy (plan §5).

### 6.2 Historical capture brief (superseded by ADR-015 §6; not a minimum)

The original proposal below is preserved as history. Its duration and construction-disjointness claims are not current guidance: the approximately two-hour C+ qualification-candidate proposal replaces it, and capture chronology, custody and prior exposure must be verified under ADR-015 §3. Neither commissioning alone nor a raw-hour total proves eligibility or adequacy.

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

## 8. Historical next-step proposal (superseded by C+; do not reopen S1)

1. **Owner inputs**, all from §2:
   - R-3 designates the controlled source store;
   - the owner names the footage rights reviewer and the privacy reviewer;
   - R-1 supplies `freshnessReferenceDate` with evidence;
   - R-2 rules on the B0 §1 interpretation.
2. **Owner decision**, which can run in parallel: whether to start a commissioned or owner-captured footage brief along the lines of §6.2. Public-source sufficiency remains unresolved until a completed and reviewed run.
3. **Complete the public pilot from the Development host**, if the owner still wants it:
   - re-run the *same* predeclared scopes P1–P5 (then S1–S2) with the existing helper from the Development host. Whether the HTTP 429s recur there is unknown, because their cause was not established;
   - record the run note and report hashes;
   - have the named reviewers complete the decisions template;
   - acquire admitted files only;
   - apply the §4 tally.
   
   P4 lists only direct members and returned no video titles. If the owner wants subcategory members, that is a **new predeclared scope** (for example the named subcategories), recorded before the rerun and never chosen from results.
4. Only after footage passes admission does the B0 §5 ingestion handoff start Slice B proper.

No tooling was changed, and nothing here may be merged without authorization.

## 9. Correction to the B0 record (made in this change)

B0 §5 step 4 described the corpus raw-evidence pin as "the retained original's SHA-256 from the receipt". That conflicts with `manifest.py`, where the pin is the vision pipeline profile digest plus the Evidence Set selector and scorer versions. It is now corrected in `s2c-b0-source-acquisition-record.md`. The retained original's SHA-256 stays bound per source through the receipt SHA-256 in the manifest source row (B0 §5 step 3).
