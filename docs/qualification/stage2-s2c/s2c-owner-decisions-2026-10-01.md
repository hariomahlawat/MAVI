# S2c owner decisions — roles, controlled directories and pilot-evidence custody, 2026-10-01

**Baseline:** `main@cef1b6585da125428c371a3af3eeca8d7ce8e09d`.
**Decided by:** Hari Om (Hari Om Ahlawat), repository owner, in a Claude Code session on 2026-10-01. The Claude Code session transcribed the decisions into this record. It holds no role and made no decision.
**Governing documents:**
- execution plan `docs/superpowers/plans/2026-09-30-stage2-s2c-real-qualification-execution.md` §5, §6, §17 (Slices B, D and J) and §19;
- execution record `real-qualification-execution-record.md` §2–§3 and §4.3.9–§4.3.13;
- B0 record `s2c-b0-source-acquisition-record.md` §1, §2, §4, §6, §7, §9 and §10;
- pilot record `s2c-b-source-feasibility-pilot-2026-10-01.md` (the "pilot record"), whose as-of-run statements this record does not rewrite;
- `tools/qualification/source_acquisition/README.md` and its code.

**Scope.** This record changes role assignments **prospectively, from the owner's decision (§1)**, designates controlled directories, and records local custody of the 2026-10-01 pilot evidence bundle. It does not:
- admit, acquire or review any footage;
- change any model-licence determination (execution record §4.3.8) or any other role assignment;
- start Slice B corpus execution, or create a VideoAsset, ProcessingRun, Track, label, partition, task freeze or seal;
- train, tune, evaluate or select anything, or read frozen-test material (none exists);
- change any tool.

F1 stays OPEN, both MSRs stay `PLANNED`, and S1.4 B1–B6 stay OPEN and separately governed.

## 1. Role assignments, prospective from the owner's decision

**When the decision took effect.** The decision was made on 2026-10-01, **after** the pilot run. The order of events, from retained evidence and Git:

| Event | Time (UTC) | Evidence |
|---|---|---|
| Pilot run | began before 11:44:06Z; ended by 12:23:49Z | Retained modification times in `MANIFEST.json`. 11:44:06Z is the earliest retained time, not the run start: the predeclaration and P1's list request came earlier, and the run note's own modification time was later overwritten. 12:23:49Z is when the run outcomes were appended to the run note. The P1 console transcription was written later, when the bundle was built. |
| Pilot evidence bundle built | 12:32:54Z | `MANIFEST.json` `createdUtc` |
| Pilot record's last commit before the decisions | 13:02:35Z | commit `6201ff0f` |
| Archive placed on QUEENSGAMBIT | 13:33:03.718Z | archive last-write time (§4) |
| **Owner decisions given** | exact time not recorded | Given in chat. That they came after the archive was placed rests on the Claude Code session's own observation: it saw the placed archive before the decisions arrived. It is not repository evidence. |
| Decisions first recorded | 13:54:38Z (19:24:38+05:30) | author time of commit `775ba92a`; an upper bound, not the decision instant |

The changes below take effect from that decision. Everything earlier on 2026-10-01, including the whole pilot run, falls under the earlier assignments.

The 2026-09-30 assignments in execution record §2 stay the historical record. Every action taken under them stays attributed as recorded, including:
- R-1 Aarav's recorder action on the working M2 ledgers (§4.3.7);
- R-2 Hari Om's review of the draft ledgers (§4.3.6);
- R-5 Aarav's evaluation-permission determinations (§4.3.8);
- R-1/R-6 Aarav's designation of the model store (§4.3.9).

**Changed by the owner's decision:**

| Id | Role | Before the decision (historical, including during the pilot run) | From the decision |
|---|---|---|---|
| R-1 | Accountable execution owner | Aarav | **Hari Om** |
| R-3 | Corpus Custodian | Aarav | **Hari Om** |

**New appointments by the same decision** (roles that the B0 record §10 and the pilot record left unnamed):

| Role | Appointed | Authority |
|---|---|---|
| Footage rights reviewer | **Hari Om** | per-file rights determinations (`rightsReview`, `PERMITTED_FOR_PILOT_ACQUISITION`) |
| Footage privacy reviewer | **Hari Om** | per-file privacy review with a basis (`privacyReview`; B0 §7) |

These appointments name the reviewers. They are **not** a blanket permission or an admission for any footage, provider, category or search. Every file still needs its own recorded rights determination with evidence and its own privacy review with a basis before it can reach `ADMITTED_FOR_PILOT` (README "States"). An open copyright licence does not settle privacy.

**Share-alike and other licence questions go to R-5.** This appointment grants no permission. The licence notes in B0 §2 are "summaries for R-5 review", TRAIN roles are "subject to R-5 licence review", and the pilot record §4 calls share-alike compatibility "an R-5 question". So for any share-alike file (for example `cc-by-sa-4.0`), and for any file whose licence terms need interpretation, the path is:
1. R-5 records a determination of whether the licence permits the intended role (`operational-candidate` or `training-only`). This record's reading, which no existing rule states and which is for R-5 to confirm, is that the determination should also address derived material: crops, labels, MAVI-trained heads and any redistribution. R-5's model-evaluation determinations (§4.3.8) do not cover footage.
2. Only then may the footage rights reviewer record `PERMITTED_FOR_PILOT_ACQUISITION` for that file, citing the R-5 determination as evidence.

The helper never admits a file under a non-commercial or no-derivatives licence. Without a decision it marks such a file `REJECTED`. With a decision requesting admission it marks a video file `RIGHTS_PENDING`, because the licence blocker can never be cleared (README "States"; `admission.py`).

**Unchanged:** R-2 Hari Om, R-4 Aarav (annotation owner/annotator) and Savita (independent annotator/reviewer), R-5 Aarav (Licence Review Owner), R-6 Aarav and R-7 Hari Om. The footage rights reviewer is a separate appointment from R-5.

**The 2026-10-01 pilot run is not re-attributed.** It ran before the decision. A Claude Code session operated it, on Hari Om's instruction as repository owner, with no recorded delegation from the then Corpus Custodian (R-3 Aarav). This record claims no delegation, approval or ratification of that run. R-3's confirmation (pilot record header) stays pending. If R-3 Hari Om later gives one, it must be recorded as a dated later ratification by the person who instructed the run. It is not a delegation at the time, and it is not an independent check.

## 2. Independent-review check after the reassignment

From the decision, Hari Om holds R-1, R-2, R-3, R-7, footage rights reviewer and footage privacy reviewer. The table checks each independence rule that the governing documents or validators impose. Rows marked *inference* follow from the plan's structure rather than from an explicit rule.

| Rule | Source | Finding |
|---|---|---|
| R-2 "cannot be R-1" | execution record §2, R-2 row | **Violated from the decision.** Hari Om now holds both. Hari Om's R-2 review of 2026-09-30 (§4.3.6) remains valid, because Aarav was then R-1 and the recorder. |
| Freeze attestation: `recordedBy` ≠ `reviewedBy` (case-insensitive) | `tools/qualification/model_selection/s2c_artifacts.py` (`freeze:independent_reviewer`); plan §6 ("named distinct recorder/reviewer") and §17 Slice D ("independently review freeze") | No freeze exists yet. A freeze recorded and reviewed by Hari Om would be refused by the validator. It would not be an independent review even if the names were spelled differently. |
| Closure review | plan §17 Slice J ("independent review must find no open P1/P2") | The same conflict applies to closure review. |
| Ledger `classificationHistory`: `recordedBy` ≠ `reviewedBy` | `credibility.py` (`history_reviewer_not_independent`) | The existing 48 entries (`recordedBy: Aarav`, `reviewedBy: Hari Om`) stay valid. Any **new** entry that Hari Om records cannot be reviewed by Hari Om. |
| Emerging shortlist: `reviewedBy` ≠ `decidedBy` | `credibility.py` (`shortlist_reviewer_not_independent`) | No shortlist decision exists. The same separation applies when one is made. |
| Recipe "independently reviewed" | plan §17 Slice B acceptance; §19 item 5 ("The reviewer must supply one complete executable recipe") | **Conflict, unconditional while Hari Om holds R-1 and R-7.** R-1 signs owner inputs (execution record §2), and the recipe and owner gates are owner input OI-5. R-7 supplies and reviews the recipe. Holding both makes the recipe review a self-review in every case. |
| Review of the custodian's seal and access log | *inference*: plan §6 (the freeze binds `sealedViewOn` and seal hashes) and §17 Slice B ("seal valid") | No explicit rule assigns seal review to R-2, and no validator compares the custodian with the freeze reviewer. But the freeze review covers the seal. With Hari Om as R-3 and R-2, the custodian's seal would be reviewed by the custodian. |
| Annotator independence | `f1.py` (an annotator independent of model selection on every double-labelled unit; a named custodian) | Unaffected. No `f1` rule relates the custodian to the annotators, and the annotator-independence rule still concerns Aarav and Savita. Already true before the decision: the custodian has frozen-test ground-truth access (plan §5 table). With Hari Om as R-1 the custodian also signs owner gates, as Aarav did when he held R-1 and R-3. |
| Footage rights or privacy reviewer independent of the custodian or R-1 | B0 record; README; `admission.py` | **No such rule is stated.** The admission rules need a *named* reviewer, not an independent one. The same person deciding admission and holding custody is permitted, but nobody independently checks it. That is recorded here as a limitation, not a defect. |
| `ownerChoice.decidedBy` | `s2c_artifacts.py` | No independence rule; R-1 decides. Unaffected. |

**Required separation (owner action; no reviewer is invented here).** Before any of the following actions, the owner must assign a person other than Hari Om to an independent-review role that covers it, or change the conflicting assignment:
1. review of the b-1 recipe and owner gates (Slice B acceptance), unconditionally while Hari Om is R-1 and R-7;
2. review of the custodian's seal and access log (Slice B; inference, above);
3. review of any new `classificationHistory` entry, or of a shortlist decision, that Hari Om records or decides (from Slice C2, or earlier if the ledgers change);
4. any freeze review or `freezeAttestation.reviewedBy` (Slice D), and any protocol review;
5. closure review (Slice J).

Until then, R-2 and R-7 are recorded as **conflicted for these actions**. The assignments themselves are unchanged, because the owner has not changed them. No current action is blocked: the next Slice B steps (per-file footage review, metadata discovery and custody) need named reviewers, not independent ones.

## 3. Controlled directories on QUEENSGAMBIT

The owner designated the following by the same decision. All are outside Git. Paths are recorded here as custody facts. They never enter receipts or corpus records, which carry no local paths (README; plan §4).

| Purpose | Designated path |
|---|---|
| Source media: retained original files of admitted footage only | `E:\MAVI-Controlled\SourceMedia\S2c\2026-01` |
| Acquisition receipts and discovery records | `E:\MAVI-Controlled\Acquisition\S2c\2026-01`. Each helper run uses its own subdirectory as a separate `--store` root. |
| Processing outputs (VideoAsset/ProcessingRun outputs of the B0 §5 handoff) | `E:\MAVI-Controlled\Processing\S2c\2026-01` |
| Corpus artefacts (custodian record store for `check-f1 --store`) | `E:\MAVI-Controlled\Corpus\S2c\2026-01` |
| 2026-10-01 pilot evidence | `E:\MAVI-Controlled\Evidence\S2c\2026-10-01-source-pilot` |
| Disposable working files (never evidence, never custody) | `E:\MAVI-Working` |
| Candidate model bytes (**unchanged**) | `D:\MAVI-Controlled\Models\S2c\2026-01` (execution record §4.3.9–§4.3.11) |

**How this fits the helper as it is.**
- **Where the helper writes.** Everything goes under the single `--store` root: `discovery/` and `evidence/` from `discover`; `receipts/`, `media/commons/…` and `source-acquisition-summary.json` from `acquire`.
- **The store must be outside Git.** The helper refuses a store inside a Git worktree.
- **Media cannot be redirected by a link.** `acquire` refuses a media path that resolves outside the store root (`acquire.py`, "media path escapes the controlled store"). Path resolution follows junctions and symbolic links, so linking `media/` to the SourceMedia directory does not work.
- **Media cannot be moved afterwards.** `verify` reads media from the store-relative path, so moving files breaks it.
- **Consequence:** a `discover`-only run whose store is a subdirectory of the Acquisition directory fits both the helper and the designations. An `acquire` run would place media under the Acquisition directory, not the SourceMedia directory.
- **Before any `acquire` is authorized**, the owner must choose how the SourceMedia designation is met. Neither option is implemented or authorized:
  - a separately reviewed and tested helper change that adds a distinct media root inside the containment rules;
  - a recorded operator procedure that hard-links each verified media file into the SourceMedia directory. This works only on the same NTFS volume, and both directories are on `E:`. The store copy stays the `verify` target.

**State on 2026-10-01** (observed by the Claude Code session on QUEENSGAMBIT, read-only):
- the four `…\S2c\2026-01` directories exist and are empty;
- E: had 76.7 GB free, and D: had 107.0 GB free;
- read access works for the session's Windows user, and permissions are inherited (Administrators: full control);
- write access was not tested, because that would have meant creating a file.

**Model store re-verification** (same session, read-only):
- `acquisition-manifest.json` SHA-256 is `bbc949bc546464f57301dd5f05fdccb368dd54ac87efbee2be038ecbd83618a5`, matching §4.3.11;
- all 14 listed artefacts are present, and each file's SHA-256 and byte size, recomputed locally, match the manifest;
- no `.partial` file is present;
- nothing was moved or downloaded.

## 4. Local custody of the 2026-10-01 pilot evidence bundle

This closes, for the local copy, the gap that the pilot record §4a left open ("durable custody is not established").

**Retained original.**

| Field | Value |
|---|---|
| Path | `E:\MAVI-Controlled\Evidence\S2c\2026-10-01-source-pilot\mavi-s2c-b-source-pilot-evidence-2026-10-01.tar.gz` |
| Host | QUEENSGAMBIT |
| Size | 21,782 bytes |
| Last-write time | 2026-10-01T19:03:03.718+05:30 (13:33:03.718Z), as placed by the owner |
| SHA-256 | `82fe15b714111c968d676bdd36b55598d5235697b0200d5954ce2b5350760331` |
| Manifest | `MANIFEST.json`, SHA-256 `60e4edc8a3ae18447d8e44cb4bdaf66d56cb5d94b4a13529ec50abef9a97d599` |
| Custodian | Hari Om, R-3 from the owner's decision (§1). The archive was placed before the decision, by Hari Om as repository owner. |

**Verification on 2026-10-01.** The checks below were automated and run by a **Claude Code session on QUEENSGAMBIT**, using PowerShell `Get-FileHash` and Windows `tar`, at the owner's instruction. They are a mechanical re-verification, not a human review:
1. The archive's SHA-256 equals the value above, which is the value recorded in the pilot record §4a.
2. The archive was extracted, read-only, into a new disposable directory, `E:\MAVI-Working\S2c-source-pilot-verify-2026-10-01\`. The extracted copy is working material, not custody.
3. `MANIFEST.json`'s SHA-256 equals the value above.
4. All 24 payload files listed in the manifest exist, and each matches its recorded byte size and SHA-256. The extraction holds 25 files (24 + `MANIFEST.json`), so no payload file is unlisted.
5. The reconstructed predeclaration hash `bc4b0c2cf9dc54319bda31a1591c6d16fa9465fa759c047d7a1cbae511b03339` was reproduced over the run note's first 1,346 bytes, using the rule in the pilot record §4a.
6. The archive was re-hashed after extraction. It is unchanged, and the original was not modified.

**Limits.**
- This establishes local custody of these exact bytes from 2026-10-01. It does not restore the evidence the bundle records as lost.
- How the file was handled between its delivery from the session and its placement on the host is not recorded: who moved it, how, and where it was held in between. The matching SHA-256 shows that the placed bytes are identical to the bundle built at 12:32:54Z, whatever the handling.
- It is not a backup. A second retained copy is an R-3 choice.

## 5. Owner inputs after these decisions

| Input | State |
|---|---|
| Controlled source-media store | **Location designated** (§3). The "independently reviewable" part of the custody input (pilot record §2; OI-2) stays open while no independent reviewer exists (§2). The media-placement method must be chosen before any `acquire` (§3). |
| Footage rights reviewer and footage privacy reviewer | **Named**: Hari Om (§1). Per-file reviews are still required, and R-5 decides share-alike and licence-interpretation questions first (§1). |
| Durable custody of the pilot bundle | **Recorded locally** (§4) |
| Independent reviewer for actions in which Hari Om acts (§2) | **MISSING**: required before the actions listed in §2 |
| `freshnessReferenceDate` | **MISSING**; a provisional proposal only, in §6.1 |
| Acceptance of the B0 §1 reading (public-source eligibility) | **PENDING**; options in §6.2 |
| User-Agent operator contact | PENDING owner confirmation (pilot record §2) |
| R-3 confirmation of the 2026-10-01 pilot run | PENDING. If given, it is a later ratification (§1). |
| Commissioned or owner-captured footage | PENDING (B0 §2.2; pilot record §6.2) |

## 6. Proposals (not decisions; nothing below is adopted, implemented or executed)

### 6.1 Proposed `freshnessReferenceDate` (provisional)

B0 §4 defines the reference date as the latest public release date of any candidate checkpoint in the evaluated set. The evaluated set is the R-5-permitted, acquired set (execution record §4.3.8, §4.3.11):

| Checkpoint (pinned) | Release evidence for the pinned bytes | Evidence and limits |
|---|---|---|
| SigLIP 2 `google/siglip2-base-patch16-224@75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2` | **2025-02-20** (paper) | The arXiv 2502.14786 v1 `published` timestamp is 2025-02-20T18:08:29Z, retrieved from the arXiv API on 2026-10-01. The Hugging Face commit date of the pinned revision or weight file **could not be retrieved**: from this host, Hugging Face connections are reset (as in execution record §4.3.10). |
| DINOv2 `facebook/dinov2-small@ed25f3a31f01632728cabb09d1542f84ab7b0056` | 2023-04-14 (paper) | arXiv 2304.07193 v1 `published` 2023-04-14T15:12:19Z. Hugging Face commit date not retrieved (same reason). |
| OMZ 0230 / 0234 / 0238 / 0042 at `a6946b6d6ce42cbf4278df20275fab199655fc7d` (2023.0 `models_bin`) | 2023-04-12 (2023.0 publication) | Each `model.yml` history at the pin: the 2023.0 publication commit is `cb11ccd29f`, 2023-04-12 ("Publish first set of candidate models for 2023.0"); last touched by `af810de42b` on 2024-02-12 (copyright years and numpy limit). These model families appeared in earlier OMZ releases, whose dates were not checked here; they are earlier still. The repository head commit `a6946b6d` on 2026-09-21 is a dependency bump, not a model release. |

**Proposed wording for R-1:**

> "Provisional `freshnessReferenceDate` = **2025-02-20**, the SigLIP 2 public release (arXiv 2502.14786 v1, 2025-02-20T18:08:29Z), the latest release among the permitted pinned checkpoints. It is not final, and no file may be assessed against it, until R-1 confirms from the Hugging Face commit history on a host that can reach it whether any commit touching the pinned SigLIP 2 or DINOv2 files at the pinned revisions is dated after 2025-02-20. If one is, the latest such date replaces 2025-02-20. Adding a candidate that is now blocked (Awiros, MobileNetV3-Small or VTFPAR++), or a later candidate, **may** move the date later. If it does, admitted operational candidates are re-assessed and never grandfathered (B0 §4)."

Under the strictly-after rule (`admission.py`: the capture start must be after the reference date), 2025-02-20 would make 2025-02-21 the first acceptable capture day. Freshness is necessary, not proof of independence (B0 §1.3).

### 6.2 Public-source eligibility decision (B0 §1): pending

The B0 record assigns this to "R-2 / owner". With Hari Om now holding R-1 and R-2, it can be recorded as an **owner decision**. It must not be described as an independent R-2 review (§2). The pilot record §8 says, as of the run, that "R-2 rules on the B0 §1 interpretation". That ruling will be answered through the owner route when the owner decides; it has not been decided. Three options:

| Option | Proposed wording | Consequence |
|---|---|---|
| A: accept B0 §1 | "The owner accepts B0 §1. A public file may become operational corpus material only after per-file admission and processing through the real MAVI ingestion, detector, tracker and Evidence Set path, plus the corpus tooling. For public files, disjointness is a recorded-evidence argument from a reviewed capture interval after `freshnessReferenceDate`. It is weaker than construction and is named as such wherever it is used." | The public pilot can continue. Each use carries the weaker-disjointness caveat. |
| B: reject B0 §1 | "The owner rules that public files are not MAVI-acquired operational footage. Public files are development references or training-only material at most (stop condition S5)." | The public pilot's operational question ends. Commissioned or owner capture becomes the operational route. |
| C: accept, but frozen test commissioned only | "The owner accepts B0 §1 for training, tuning and selection material. The frozen test is drawn only from commissioned or owner-captured footage, so its disjointness holds by construction." | Combines A and B. It needs commissioned capture for at least the frozen-test sites and cameras, and it must be fixed before partitioning. |

Option C is the most conservative reading consistent with B0 §1.3 and §2.2, but it commits the owner to commissioned capture. This record does not choose between the options. The decision remains open.

### 6.3 Proposed bounded metadata-only local retry

This is a proposal for R-3 Hari Om to approve or change. It is not authorized by this record, and none of the scripts or helper changes it mentions exist.

- **Scope.**
  - Exactly the predeclared scopes P1–P5, verbatim from B0 §6 and the 2026-10-01 run note, with `--limit 20`, in the order P1…P5.
  - Run S1–S2 only if P1–P5 yield fewer than 40 distinct video files described without error.
  - Re-running P1 and P4 is a new observation.
  - A subcategory scope for P4 would be a **new** scope, declared before the run and never chosen from results.
  - Commands: `discover` only. `acquire` is never run.
- **Host and store.** QUEENSGAMBIT, from a checkout at a recorded commit. `--store` is one new run subdirectory of `E:\MAVI-Controlled\Acquisition\S2c\2026-01\` (for example `commons-discovery-<UTC date>`), used as the store root for every scope in this run. `--contact` is the public repository URL, once the owner confirms it.
- **What the helper actually does.**
  - **Logical requests.** Each scope makes one list request, then one metadata request per video title, with no pacing between requests. With `--limit 20` that is at most **21 logical requests per scope** and at most **147** for P1–P5 plus S1–S2.
  - **Attempts.** Retries apply to HTTP 429 and 503 responses only. Such a logical request gets up to **3 attempts**: after each 429 or 503 the helper sleeps 30 s, then 60 s, and it ignores `Retry-After`. Each attempt may follow up to **5 redirects**, each a further HTTP request. A network error (connection reset, TLS failure or socket timeout) is **not** retried. It is not caught by the helper, so the scope ends with a traceback, exit 1, and no discovery report.
  - **Worst case.** About 63 HTTP attempts per scope and about 441 for the run, before redirects.
  - **Timeout.** `TIMEOUT_SECONDS = 60` applies to each socket operation. It is **not** a total deadline per request or per scope.
  - **No duration bound.** Because of the timeout behaviour, a scope's duration has no hard bound. A rough worst case for 21 logical requests is well over an hour.
- **Budget (planning limits, not guarantees).**
  - Wait at least 5 minutes between scopes.
  - Do not start a new scope once 2 hours have passed since the first request. This is checked only **between** scopes, so a scope that has already started can run past it.
  - Do not use an outer kill timer within a scope. The 2026-10-01 kill lost P2's report.
  - If the operator interrupts a scope anyway, record that scope as terminated, with its report lost, and end the run.
- **Preflight (proposed; no such script exists).** Before P1, send one read-only `siteinfo` request with the helper's User-Agent, using a small operator script in the manner of the pilot's `rate-limit-probe.py`. The script and its SHA-256 are retained in the evidence. If the request returns HTTP 429, stop and record S4 without running any scope.
- **Stop conditions.** Each is checked after a scope finishes. The helper cannot be stopped cleanly inside a scope.
  - Any nonzero exit stops the **whole run**: `REFUSED`/exit 2 when the list request fails, or any other unexpected exit. The 2026-10-01 run continued after a 429.
  - A per-file metadata failure stops the run after that scope. A failure the helper catches (an HTTP error status after any retries, or a parse error) does not fail the scope: the helper records the item with `"error"` set and `admissionState` null, writes the report and exits 0. A network error is not caught: it ends the scope with exit 1 and no report, which the nonzero-exit rule above covers. The operator therefore checks the console `states` for `"None"` and the written discovery report for any item with a non-null `error`.
  - An incomplete result stops the run: a scope that ends without printing its `discoveryReportSha256`, or whose discovery report or decisions template is missing from the store.
  - A parser field that differs from the documented shape stops the run (B0 §9).
  - Stop on reaching 60 candidates described without error, or the 147-logical-request planning limit.
  - Record which stop condition was reached (S1–S5, budget or interruption).
- **Durable evidence capture.**
  1. Write the run note's predeclaration (scopes, order, limits, budget, stop rules, commit, host, contact class) before the first request. Record its SHA-256 at once in a separate file, so that no reconstruction is needed.
  2. Capture each scope's console output to its own log file, with start and end UTC timestamps and the exit code.
  3. Have the preflight probe log the full response status, headers and body.
  4. Build a `MANIFEST.json` (path, size, SHA-256, role, modification time), a `.tar.gz` and its SHA-256. Copy the bundle into a new `E:\MAVI-Controlled\Evidence\S2c\<date>-source-pilot-retry\` and re-verify it there.
  5. The ordered raw list responses, per-attempt timings and 429 headers are still not retained, because the helper does not record them. Either accept and record that limitation, or first make a separately reviewed, tested helper change that retains them. That change is outside this documentation-only record and is not implemented.
- **After the run.** Hari Om, as the named footage reviewers, completes the decisions template only for files actually reviewed, recording per-file rights evidence (with R-5's determination first for share-alike files; §1) and a privacy basis. Admission, the media-placement method (§3) and any `acquire` are separate, later authorizations.
