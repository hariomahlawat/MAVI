# S2c owner decisions — roles, controlled directories and pilot-evidence custody, 2026-10-01

**Baseline:** `main@cef1b6585da125428c371a3af3eeca8d7ce8e09d`.
**Decided by:** Hari Om (Hari Om Ahlawat), repository owner, in a Claude Code session on 2026-10-01. The Claude Code session transcribed the decisions into this record. It holds no role and made no decision.
**Governing documents:**
- execution plan `docs/superpowers/plans/2026-09-30-stage2-s2c-real-qualification-execution.md` §5, §17 (Slice B) and §19;
- execution record `real-qualification-execution-record.md` §2–§3 and §4.3.9–§4.3.12;
- B0 record `s2c-b0-source-acquisition-record.md` §1, §4, §6, §7 and §10;
- pilot record `s2c-b-source-feasibility-pilot-2026-10-01.md` (the "pilot record"), whose as-of-run statements this record does not rewrite;
- `tools/qualification/source_acquisition/README.md`.

**Scope.** This record changes role assignments **from 2026-10-01 onwards**, designates controlled directories, and records local custody of the 2026-10-01 pilot evidence bundle. It does not:
- admit, acquire or review any footage;
- change any model-licence determination (execution record §4.3.8) or any other role assignment;
- start Slice B corpus execution, or create a VideoAsset, ProcessingRun, Track, label, partition, task freeze or seal;
- train, tune, evaluate or select anything, or read frozen-test material (none exists).

F1 stays OPEN, both MSRs stay `PLANNED`, and S1.4 B1–B6 stay OPEN and separately governed.

## 1. Role assignments, prospective from 2026-10-01

The 2026-09-30 assignments in execution record §2 stay the historical record. Every action taken under them stays attributed as recorded, including:
- R-1 Aarav's recorder action on the working M2 ledgers (§4.3.7);
- R-2 Hari Om's review of the draft ledgers (§4.3.6);
- R-5 Aarav's evaluation-permission determinations (§4.3.8);
- R-1/R-6 Aarav's designation of the model store (§4.3.9).

**Changed by the owner on 2026-10-01:**

| Id | Role | Until 2026-09-30 (historical) | From 2026-10-01 |
|---|---|---|---|
| R-1 | Accountable execution owner | Aarav | **Hari Om** |
| R-3 | Corpus Custodian | Aarav | **Hari Om** |

**New appointments on 2026-10-01** (roles that the B0 record §10 and the pilot record left unnamed):

| Role | Appointed | Authority |
|---|---|---|
| Footage rights reviewer | **Hari Om** | per-file rights determinations (`rightsReview`, `PERMITTED_FOR_PILOT_ACQUISITION`) |
| Footage privacy reviewer | **Hari Om** | per-file privacy review with a basis (`privacyReview`; B0 §7) |

These appointments name the reviewers. They are **not** a blanket permission or an admission for any footage, provider, category or search. Every file still needs its own recorded rights determination with evidence and its own privacy review with a basis before it can reach `ADMITTED_FOR_PILOT` (README "States"). An open copyright licence does not settle privacy.

**Unchanged:** R-2 Hari Om, R-4 Aarav (annotation owner/annotator) and Savita (independent annotator/reviewer), R-5 Aarav (Licence Review Owner for models), R-6 Aarav and R-7 Hari Om. The footage rights reviewer is a separate appointment from R-5. R-5's model-evaluation determinations are unchanged and do not extend to footage.

**The 2026-10-01 pilot run is not re-attributed.** It was operated by a Claude Code session before these decisions, with no recorded delegation from the then Corpus Custodian (R-3 Aarav). This record does not retroactively claim that delegation or any approval of that run. R-3's confirmation of the run (pilot record header) stays pending. From today it is the new R-3's decision.

## 2. Independent-review check after the reassignment

From 2026-10-01 Hari Om holds R-1, R-2, R-3, R-7, footage rights reviewer and footage privacy reviewer. The table checks each independence rule that the governing documents or validators impose.

| Rule | Source | Finding |
|---|---|---|
| R-2 "cannot be R-1" | execution record §2, R-2 row | **Violated from 2026-10-01.** Hari Om is now both. Hari Om's R-2 actions **before** 2026-10-01 (§4.3.6) remain valid, because Aarav was then R-1 and the recorder. |
| Freeze attestation: `recordedBy` ≠ `reviewedBy` (case-insensitive) | `tools/qualification/model_selection/s2c_artifacts.py` (`freeze:independent_reviewer`); plan §6 ("named distinct recorder/reviewer") and §13 | No freeze exists yet. A freeze recorded by R-1 Hari Om and reviewed by R-2 Hari Om would be refused by the validator, and it would not be an independent review even if the names were spelled differently. |
| Ledger `classificationHistory`: `recordedBy` ≠ `reviewedBy` | `credibility.py` (`history_reviewer_not_independent`) | The existing 48 entries (`recordedBy: Aarav`, `reviewedBy: Hari Om`) stay valid. Any **new** entry that Hari Om records cannot be reviewed by Hari Om. |
| Emerging shortlist: `reviewedBy` ≠ `decidedBy` | `credibility.py` (`shortlist_reviewer_not_independent`) | No shortlist decision exists. The same separation applies when one is made. |
| Recipe "independently reviewed" | plan §17 Slice B acceptance; §19 item 5 | **Conflict.** R-1 signs owner inputs (execution record §2), and the b-1 recipe and owner gates (OI-5) are owner inputs. R-7 Hari Om reviewing a recipe that R-1 Hari Om signed would be self-review. R-7 stays valid only for a recipe that Hari Om neither authored nor signed. |
| R-2 review of the seal and freeze carried out by the Corpus Custodian | plan §6, §17 Slice D | The same conflict, through R-3: the custodian's seal and access log would be reviewed by the same person. |
| Annotator independence | `f1.py` (an annotator independent of model selection on every double-labelled unit) | Unaffected: the annotators are still Aarav and Savita, and the custodian is now a different person from both. |
| Footage rights or privacy reviewer independent of the custodian or R-1 | B0 record; README | **No such rule is stated.** The admission rules need a *named* reviewer, not an independent one. The same person deciding admission and holding custody is permitted, but nobody independently checks it. That is recorded here as a limitation, not a defect. |
| `ownerChoice.decidedBy` | `s2c_artifacts.py` | No independence rule; R-1 decides. Unaffected. |

**Required separation (owner action; no reviewer is invented here).** Before any of the following actions, the owner must assign a person other than Hari Om to an independent-review role that covers it, or change the conflicting assignment:
1. any freeze review or `freezeAttestation.reviewedBy` (Slice D), and any protocol or closure review;
2. review of the b-1 recipe and owner gates (Slice B acceptance), if R-1 Hari Om authors or signs them;
3. review of any new `classificationHistory` entry, or of a shortlist decision, that Hari Om records or decides;
4. review of the Corpus Custodian's seal and access log.

Until then, R-2 and R-7 are recorded as **conflicted for these actions**. The assignments themselves are not changed, because the owner has not changed them. No current action is blocked: the next Slice B steps (per-file footage review, metadata discovery, custody) need named reviewers, not independent ones.

## 3. Controlled directories on QUEENSGAMBIT

The owner designated the following on 2026-10-01. All are outside Git. Paths are recorded here as custody facts. They never enter receipts or corpus records, which carry no local paths (README; plan §4).

| Purpose | Designated path |
|---|---|
| Source media: retained original files of admitted footage only | `E:\MAVI-Controlled\SourceMedia\S2c\2026-01` |
| Acquisition receipts and discovery records (the helper's `discovery/`, `evidence/`, `receipts/`) | `E:\MAVI-Controlled\Acquisition\S2c\2026-01` |
| Processing outputs (VideoAsset/ProcessingRun outputs of the B0 §5 handoff) | `E:\MAVI-Controlled\Processing\S2c\2026-01` |
| Corpus artefacts (custodian record store for `check-f1 --store`) | `E:\MAVI-Controlled\Corpus\S2c\2026-01` |
| 2026-10-01 pilot evidence | `E:\MAVI-Controlled\Evidence\S2c\2026-10-01-source-pilot` |
| Disposable working files (never evidence, never custody) | `E:\MAVI-Working` |
| Candidate model bytes (**unchanged**) | `D:\MAVI-Controlled\Models\S2c\2026-01` (execution record §4.3.9–§4.3.11) |

**How this fits the helper.** The helper uses one `--store` root, with `media/commons/…` beneath it. To land media in the SourceMedia directory and records in the Acquisition directory, the operator procedure must place or link `media/` accordingly, or the helper needs a separate media root. Hard-link promotion needs NTFS and the same volume (B0 §9), and both directories are on `E:`. This record makes no tool change. The question is settled before the first `acquire` run, and no `acquire` is authorized now.

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

This closes the gap that the pilot record §4a left open ("durable custody is not established") for the local copy.

**Retained original.**

| Field | Value |
|---|---|
| Path | `E:\MAVI-Controlled\Evidence\S2c\2026-10-01-source-pilot\mavi-s2c-b-source-pilot-evidence-2026-10-01.tar.gz` |
| Host | QUEENSGAMBIT |
| Size | 21,782 bytes |
| Last-write time | 2026-10-01T19:03:03.718+05:30 (13:33:03.718Z), as placed by the owner |
| SHA-256 | `82fe15b714111c968d676bdd36b55598d5235697b0200d5954ce2b5350760331` |
| Manifest | `MANIFEST.json`, SHA-256 `60e4edc8a3ae18447d8e44cb4bdaf66d56cb5d94b4a13529ec50abef9a97d599` |
| Custodian | Hari Om (R-3 from 2026-10-01) |

**Verification on 2026-10-01.** The checks below were automated and run by a **Claude Code session on QUEENSGAMBIT**, using PowerShell `Get-FileHash` and Windows `tar`, at the owner's instruction. They are a mechanical re-verification, not a human review:
1. The archive's SHA-256 equals the value above, which is the value recorded in the pilot record §4a.
2. The archive was extracted, read-only, into a new disposable directory, `E:\MAVI-Working\S2c-source-pilot-verify-2026-10-01\`. The extracted copy is working material, not custody.
3. `MANIFEST.json`'s SHA-256 equals the value above.
4. All 24 payload files listed in the manifest exist, and each matches its recorded byte size and SHA-256. The extraction holds 25 files (24 + `MANIFEST.json`), so no payload file is unlisted.
5. The reconstructed predeclaration hash `bc4b0c2cf9dc54319bda31a1591c6d16fa9465fa759c047d7a1cbae511b03339` was reproduced over the run note's first 1,346 bytes, using the rule in the pilot record §4a.
6. The archive was re-hashed after extraction. It is unchanged, and the original was not modified.

**Limits.**
- This establishes local custody of these exact bytes from 2026-10-01. It does not restore the evidence the bundle records as lost.
- It does not show that the bytes were unchanged between session delivery and placement on the host. The matching SHA-256 shows that they are the same bytes.
- It is not a backup. A second retained copy is an R-3 choice.

## 5. Owner inputs after these decisions

| Input | State |
|---|---|
| Controlled source-media store | **Designated** (§3) |
| Footage rights reviewer and footage privacy reviewer | **Named**: Hari Om (§1). Per-file reviews still required. |
| Durable custody of the pilot bundle | **Recorded locally** (§4) |
| Independent reviewer for actions in which Hari Om acts (§2) | **MISSING**: required before the actions listed in §2 |
| `freshnessReferenceDate` | MISSING; proposal in §6.1 |
| Acceptance of the B0 §1 reading (public-source eligibility) | PENDING; proposal in §6.2 |
| User-Agent operator contact | PENDING owner confirmation (pilot record §2) |
| R-3 confirmation of the 2026-10-01 pilot run | PENDING; now for R-3 Hari Om |
| Commissioned or owner-captured footage | PENDING (B0 §2.2; pilot record §6.2) |

## 6. Proposals (not decisions; nothing below is adopted or executed)

### 6.1 Proposed `freshnessReferenceDate`

B0 §4 defines the reference date as the latest public release date of any candidate checkpoint in the evaluated set. The evaluated set is the R-5-permitted, acquired set (execution record §4.3.8, §4.3.11):

| Checkpoint (pinned) | Earliest public-release evidence found | Evidence and limits |
|---|---|---|
| SigLIP 2 `google/siglip2-base-patch16-224@75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2` | **2025-02-20** | The arXiv 2502.14786 v1 `published` timestamp is 2025-02-20T18:08:29Z, retrieved from the arXiv API on 2026-10-01. The Hugging Face commit date of the pinned revision or weight file **could not be retrieved**: from this host, Hugging Face connections are reset (as in execution record §4.3.10). |
| DINOv2 `facebook/dinov2-small@ed25f3a31f01632728cabb09d1542f84ab7b0056` | 2023-04-14 | arXiv 2304.07193 v1 `published` 2023-04-14T15:12:19Z. Hugging Face commit date not retrieved (same reason). |
| OMZ 0230 / 0234 / 0238 / 0042 at `a6946b6d6ce42cbf4278df20275fab199655fc7d` (2023.0 `models_bin`) | 2023-04-12 | Each `model.yml` history at the pin: published in `cb11ccd29f` on 2023-04-12 ("Publish first set of candidate models for 2023.0"); last touched in `af810de42b` on 2024-02-12 (copyright years and numpy limit). The repository head commit `a6946b6d` on 2026-09-21 is a dependency bump, not a model release. |

**Proposed wording for R-1:**

> "`freshnessReferenceDate` = **2025-02-20**, the SigLIP 2 public release (arXiv 2502.14786 v1, 2025-02-20T18:08:29Z), which is the latest release among the permitted pinned checkpoints. It becomes final only after R-1 confirms, from the Hugging Face commit history on a host that can reach it, that no commit touching the pinned SigLIP 2 or DINOv2 files at the pinned revisions is dated after 2025-02-20. If one is, the latest such commit date replaces 2025-02-20. Adding any candidate that is now blocked (Awiros, MobileNetV3-Small or VTFPAR++), or any later candidate, moves the date later and triggers re-assessment of admitted operational candidates (B0 §4)."

A strictly-after rule makes the first acceptable capture day 2025-02-21. Freshness is necessary, not proof of independence (B0 §1.3).

### 6.2 Proposed public-source eligibility decision (B0 §1)

The record assigns this to "R-2 / owner". With Hari Om now R-1 and R-2, it can be recorded as an **owner decision**. It must not be described as an independent R-2 review (§2). Three options:

| Option | Proposed wording | Consequence |
|---|---|---|
| A: accept B0 §1 | "The owner accepts B0 §1. A public file may become operational corpus material only after per-file admission and processing through the real MAVI ingestion, detector, tracker and Evidence Set path, plus the corpus tooling. For public files, disjointness is a recorded-evidence argument from a reviewed capture interval after `freshnessReferenceDate`. It is weaker than construction and is named as such wherever it is used." | The public pilot can continue. Each use carries the weaker-disjointness caveat. |
| B: reject B0 §1 | "The owner rules that public files are not MAVI-acquired operational footage. Public files are development references or training-only material at most (stop condition S5)." | The public pilot's operational question ends. Commissioned or owner capture becomes the operational route. |
| C: accept, but frozen test commissioned only | "The owner accepts B0 §1 for training, tuning and selection material. The frozen test is drawn only from commissioned or owner-captured footage, so its disjointness holds by construction." | Combines A and B. It needs commissioned capture for at least the frozen-test sites and cameras, and it must be fixed before partitioning. |

Option C is the most conservative reading consistent with B0 §1.3 and §2.2, but it commits the owner to commissioned capture. This record does not choose between the options.

### 6.3 Proposed bounded metadata-only local retry

This is a proposal for R-3 Hari Om to approve or change. It is not authorized by this record.

- **Scope.** Exactly the predeclared scopes P1–P5, verbatim from B0 §6 and the 2026-10-01 run note, with `--limit 20`, in the order P1…P5. Run S1–S2 only if P1–P5 yield fewer than 40 distinct video files. Re-running P1 and P4 is a new observation. A subcategory scope for P4 would be a **new** scope, declared before the run and never chosen from results. Commands: `discover` only. `acquire` is never run.
- **Host and store.** QUEENSGAMBIT, from a checkout at a recorded commit. `--store` is a new run directory under `E:\MAVI-Controlled\Acquisition\S2c\2026-01\` (for example `commons-discovery-<UTC date>`). `--contact` is the public repository URL, once the owner confirms it.
- **Budget.**
  - The helper sends one list request plus one metadata request per video title, with no pacing, so each scope is at most 21 requests and the whole run at most 147.
  - Wait at least 5 minutes between scopes.
  - Global wall-clock cap: 2 hours.
  - No outer kill timer inside a scope. The 2026-10-01 kill lost P2's report. The helper's own 30 s / 60 s back-off then fail-closed bounds each request.
- **Preflight.** Before P1, send one read-only `siteinfo` request with the helper's User-Agent. If it returns HTTP 429, stop and record S4 without running any scope.
- **Stop conditions.**
  - The first `REFUSED` (exit 2) or unexpected exit in any scope stops the **whole run**. The 2026-10-01 run continued after a 429.
  - A parser field that differs from the documented shape stops the run (B0 §9).
  - Stop on reaching 60 described candidates, the request budget or the wall-clock cap.
  - Record which stop condition was reached (S1–S5 or budget).
- **Durable evidence capture.**
  1. Write the run note's predeclaration (scopes, order, limits, budget, stop rules, commit, host, contact class) before the first request. Record its SHA-256 at once in a separate file, so that no reconstruction is needed.
  2. Capture each scope's console output to its own log file, with start and end UTC timestamps and the exit code.
  3. Have the preflight probe log the full response status, headers and body.
  4. Build a `MANIFEST.json` (path, size, SHA-256, role, modification time), a `.tar.gz` and its SHA-256. Copy the bundle into a new `E:\MAVI-Controlled\Evidence\S2c\<date>-source-pilot-retry\` and re-verify it there.
  5. The ordered raw list responses are still not retained, because the helper discards them. Either accept and record that limitation, or first make a separately reviewed, tested tool change that retains them. The second option is a code change, outside this documentation-only record.
- **After the run.** Hari Om, as the named reviewers, completes the decisions template only for files actually reviewed, recording per-file rights evidence and a privacy basis. Admission and any `acquire` are separate, later authorizations.
