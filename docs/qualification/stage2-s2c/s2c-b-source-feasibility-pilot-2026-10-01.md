# S2c Slice B preparation — public-source feasibility pilot (first run), 2026-10-01

**Baseline:** `main@cef1b6585da125428c371a3af3eeca8d7ce8e09d`.
**Governing documents:**
- execution plan `docs/superpowers/plans/2026-09-30-stage2-s2c-real-qualification-execution.md` §5 and §17 (Slice B);
- execution record `real-qualification-execution-record.md` §2–§3 and §4.3.12;
- B0 record `s2c-b0-source-acquisition-record.md` §1–§9;
- `tools/qualification/source_acquisition/README.md`;
- `tools/qualification/attributes/corpus/README.md`;
- the annotation guide.

**Operator:** a Claude Code session acting for the Corpus Custodian (R-3, Aarav) under Hari Om's instruction of 2026-10-01. The operator holds no reviewer role.

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

None of these is supplied by this record, and none is defaulted.

| Input | Needed for | Owner | Status |
|---|---|---|---|
| Controlled source-media store, outside Git, on a host that is retained and independently reviewable | any acquisition; custody | R-3 (with R-1) | **MISSING** |
| Named rights reviewer for footage (`PERMITTED_FOR_PILOT_ACQUISITION` determinations) | admission | R-5, or a delegate named by the owner | **MISSING** for footage. R-5's recorded determinations cover model evaluation only. |
| Named privacy reviewer, with a basis per file | admission | owner | **MISSING**: no privacy reviewer is named |
| `freshnessReferenceDate`: the latest public release date of any checkpoint in the evaluated set | `operational-candidate` role | R-1 | **MISSING**. The record holds no checkpoint release dates, and no date is proposed here. |
| Acceptance of the B0 §1 reading of "MAVI-acquired operational footage" | whether public files may be operational at all | R-2 / owner | **PENDING**. If it is rejected, public sources are reference/training only (stop condition S5). |
| Operator contact for the User-Agent | discovery | owner | This run used the public repository URL, not a personal address. |
| Decision on commissioned or owner-captured footage | the fallback when public sources are insufficient | owner | **PENDING** (§6) |

Every discovered item is therefore at most `DISCOVERED` or pending. **No rights or privacy decision is recorded or implied**, and nothing can reach `ADMITTED_FOR_PILOT`.

## 3. Discovery run

**Scopes.** The scopes were predeclared in the operator run note before any output, taken verbatim from B0 §6, with 20 results per scope:

| Id | Scope | Result | Discovery report SHA-256 |
|---|---|---|---|
| P1 | search `traffic India 2026` | 3 video files | `3d40f18508266c2fa85639bf98566205f2ebaefea2682b84b51d041d44301ef5` |
| P2 | search `street India 2026` | 12 files' metadata retained; the run hit the operator's 900 s wall-clock limit during rate-limit back-off, before its report was written | — (per-file evidence in §4) |
| P3 | search `pedestrians market India` | HTTP 429; the helper failed closed after its 30 s and 60 s back-offs | — |
| P4 | category `Category:Videos of streets in India` | 0 files. The query lists only files *directly* in a category, and this category holds its videos in subcategories. | `83be97152d4d033344c6100af64f5b7e3004a39f408fb7c74f92748ad7fb569a` |
| P5 | category `Category:Videos of road traffic in India` | HTTP 429; failed closed | — |
| S1, S2 | secondary non-India pool | not run (rate limiting) | — |

**Live parser validation.** B0 §9 deferred this. It now passes: real Commons `imageinfo` / `extmetadata` / `revisions` responses parse into the documented fields (MIME type, dimensions, duration, size, SHA-1, licence, author, `DateTimeOriginal`). No tool change was needed.

**Rate limiting.** After the run, a single read-only request was repeated every 2 minutes for 10 minutes. Every request returned HTTP 429 (`retry-after: 5–7`) with Wikimedia's "too many requests" message. The limit therefore applies to this session container's shared egress address, not to the helper's request rate. Request pacing would not help, so **no acquisition-tool repair is justified by this failure.**

The pilot reached **stop condition S4** (rate limiting prevents metadata access) **in this execution environment**. That is not a finding about Commons from an ordinary network.

**Custody of this run's evidence.** Discovery reports and per-file metadata evidence were written to a session-local store outside Git. That store is **ephemeral and is not the controlled store**: the identities below are recorded so a rerun can be compared with them, but the bytes are not retained custody. No media bytes were downloaded.

## 4. Candidates assessed (metadata and title only; no model, no frames viewed)

| Page id / revision | Title (abridged) | Licence (machine class) | Duration | Resolution | Declared capture | Assessment |
|---|---|---|---|---|---|---|
| 155325362 / 966182342 | *Patanga* (feature film; cast named in the title) | `pd` | 149.3 min | 656×480 | 2016-02-12 (digitisation date, not capture) | **Reject**: staged fiction, not street footage; the declared date is not the capture date |
| 80275825 / 776443974 | *A Native Street in India* (1906) | `pd` | 2.9 min | 1920×1080 | 1906 | **REFERENCE_ONLY at most**: archival; it can never meet freshness |
| 190599393 … 190599574, 9 files | *Developer Skill Development Program India 2025*, videos 02–28 | `cc-by-4.0` | 4–78 s each (2.7 min total) | mostly 1080×1920 portrait | 2026-03-27 | **Not suitable**: one indoor event, so one site; portrait handheld clips; not street or vehicle scenes |
| 186746471 / 1187910038 | Holi street procession, Kolkata 2026 | `cc-by-sa-4.0` | 26 s | 3840×2160 | 2026-03-10 | **Possible operational candidate after review**: street, people and vehicles likely; handheld, festival crowd, a single short clip |
| 186711192 / 1187910134 | Iftar ambience, street in Kolkata | `cc-by-sa-4.0` | 12 s | 1080×1920 | 2026-03-19 | **Possible after review**: street, people; portrait handheld; very short |
| 194270929 / 1236254422 | Narmada bridge piers | `cc-by-4.0` | 10 s | 1080×1920 | 2026-06-21 | Not suitable: landscape or bridge, not a person/vehicle scene |
| 186965042 / 1235557773 | Times Square billboard | `cc-by-sa-4.0` | 30 s | 2304×1980 | 2026-03-25 | Not suitable: a screen recording or billboard, outside India |

Share-alike (`cc-by-sa-4.0`) is a machine pre-classification only. Whether SA terms are compatible with operational and derivative use is an R-5 question.

**Tally against the B0 §6 targets.**

| Measure | Target | Found |
|---|---|---|
| Candidates reviewed | 40–60 | 15 (not reached) |
| Admissible operational-candidate footage | ≥ 30 min (S1); 1–2 h goal | **0 min.** Nothing is admitted, because no reviews exist. Even on the most generous reading, the plausible candidates total 38 s. |
| Independent sites | ≥ 4, none above ~40 % of duration | At most 1–2 plausible (both Kolkata) |
| Viewpoint | fixed or slow | None evidenced; the plausible clips appear handheld |
| Capture-date evidence | reviewed interval, medium/high confidence, `CAPTURE_AFTER_REFERENCE` | Declared dates only, which are unreviewed. One declared date is demonstrably not a capture date (*Patanga*). The reference date is missing. |
| Person/vehicle visibility | adequate for attribute crops | Unassessed without frames; the two candidates are crowd or festival scenes |

## 5. Feasibility result

**Outcome: INCOMPLETE in this environment (S4), with strong preliminary evidence that public Commons video is insufficient** for a first operational corpus.

- The sample is small and this is not a final determination. But every observed candidate falls into one of four kinds:
  - archival film, which can never be fresh;
  - single-event clips;
  - short handheld phone clips;
  - unrelated scenes.
- None shows the fixed or slowly moving viewpoint that MAVI's camera-based Tracks presuppose.
- The corpus checks add structural needs that short handheld uploads rarely meet:
  - at least 3 cameras in **each** of training, tuning, selection and frozen-test (`check-f1`);
  - a whole held-out site whose camera is unseen elsewhere;
  - site/date-block clusters with several date blocks per site for the temporal hold-out.
- Recent declared capture dates would at best support a *disjointness argument*. They never establish independence from candidate training data (B0 §1.3).

**Not established:** any operational corpus, F1 PASS, rights or privacy approval, annotation, adjudication, or a final "insufficient" ruling under S1, S2 or S3.

## 6. Minimum additional footage if public sources are insufficient

This is the smallest **structural** footage set that lets the existing corpus tooling partition and pass its F1 structural checks. Camera floors do not establish statistical adequacy (plan §5). Whether attribute support suffices is decided only after the training pilot.

| Requirement | Minimum | Why |
|---|---|---|
| Sites | **≥ 5** independent sites, pseudonymised | at least 1 whole site held out for the frozen test (`heldOutSites` ≥ 1 in the partition policy, which is set at partition time); ≥ 4 remain for the other partitions; B0 §6 asks for ≥ 4 sites with none above ~40 % |
| Fixed cameras | **≥ 3 per site (≥ 15 total)**, mounted or tripod, stable viewpoint | every partition needs ≥ 3 cameras, and all cameras of a site in one date block move together |
| Date blocks | **≥ 4 separate recording days per non-held-out site**, including daytime and night/low light | site/date clusters fill training, tuning and selection, plus the temporal frozen hold-out (`frozenLatestBlockFraction`) |
| Duration | **≥ 10 min per camera per recording day**, at sites with steady pedestrian and vehicle flow | planning estimate (≈ 10 h raw at the minimum shape). The 1–2 h B0 target only tests feasibility; the training pilot then confirms whether ≥ 30 double-labelled units per attribute (`minimumDoubleLabelledUnitsPerAttribute`) and per-value support are reachable |
| Subjects | full-body pedestrians and whole vehicles at ≥ 720p, within the detector's working distance | attribute crops must be scorable under the annotation guide |
| Capture records | per-file capture start/end in UTC with the camera clock checked, the camera's IANA timezone, the site pseudonym, and the camera pseudonym | the reviewed capture interval; freshness holds by construction for commissioned capture |
| Privacy basis | signage or consent basis per site, recorded by the named privacy reviewer; no face or plate close-ups as subjects | B0 §7 |
| Custody | the original files, unmodified, in the designated controlled source store with SHA-256 on receipt | one raw-evidence pin per corpus |

Commissioned or owner-captured video is the B0-preferred operational route (B0 §2.2). It is the only route in which disjointness holds by construction.

## 7. Raw-evidence identity for subsequent corpus processing

The corpus manifest carries exactly one `rawEvidencePin`, and mixing pins is refused. At this baseline the pin's inputs are:

| Pin field | Value at `main@cef1b65` | Source |
|---|---|---|
| `visionPipelineProfileSha256` | the profile digest that the first real ProcessingRun records as `pipelineProfileSha256` for `src/vision/config/pipelines/phase1-detection-tracking-v1.json`. File bytes at this baseline: SHA-256 `503225be736d9622ed110aa69e49a83dde4ae02c858d5e8fa41e527b1c4b23fb` | worker provenance (`mavi_vision/worker/client.py`) |
| `evidenceSelectorVersion` | `evidence-selector-v1-two-tier` | `mavi_vision/evidence/policy.py` |
| `evidenceScorerVersion` | `quality-v2` | as above |

The manifest takes the pin **from the ProcessingRun provenance**, not from this table. If the profile, selector or scorer changes before or during corpus processing (S1.4 is open), affected crops are re-derived under the new pin. This record does not claim S1.4 closure.

## 8. Next bounded Slice B step (proposed; requires owner action)

1. **Owner inputs**, all from §2:
   - R-3 designates the controlled source store;
   - the owner names the footage rights reviewer and the privacy reviewer;
   - R-1 supplies `freshnessReferenceDate` with evidence;
   - R-2 rules on the B0 §1 interpretation.
2. **Owner decision now**, in parallel: start a commissioned or owner-captured footage brief to the §6 minimum. Public sources are unlikely to meet the structural needs regardless of the rerun.
3. **Complete the public pilot from the Development host**, if the owner still wants it:
   - re-run the *same* predeclared scopes P1–P5 (then S1–S2) with the existing helper from a non-shared network;
   - record the run note and report hashes;
   - have the named reviewers complete the decisions template;
   - acquire admitted files only;
   - apply the §4 tally.
   
   P4 lists only direct members and returned no files. If the owner wants subcategory members, that is a **new predeclared scope** (for example the named subcategories), recorded before the rerun and never chosen from results.
4. Only after footage passes admission does the B0 §5 ingestion handoff start Slice B proper.

No tooling was changed, and nothing here may be merged without authorization.
