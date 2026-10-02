# S2c B0 — source admission and acquisition pilot: implementation record

**Date:** 2026-09-30.
**Parent:** PR #124 at `201c537c7710c283eefdde0c8bf0a6f4a43526d4` (Slice A accepted; execution record §8).
**Governing documents:**
- `docs/superpowers/plans/2026-09-30-stage2-s2c-real-qualification-execution.md`;
- the parent S2c plan §10.2;
- the qualification plan §3.1.

**Tooling:** `tools/qualification/source_acquisition/` (README), a Development-only helper.

**Prospective policy amendment, 2026-10-02.** The owner adopts **C+ — Public-first development, protected final qualification** in ADR-015 and owner-decision record §8. The original S1 campaign is closed: 63/63 reviewed, 38 `REJECT_OPERATIONAL_QUALIFICATION`, 15 `REFERENCE_ONLY`, 10 `REJECTED`, 0 operationally admissible seconds; nothing is `ADMISSIBLE` or `FROZEN_QUALIFICATION`. This record's original §1–§10 narrative describes preparation and proposals at their dates, not permission to reopen that campaign. Where it conflicts, the amendment below governs new work.

### Current C+ guidance (supersedes conflicting source-purpose and acquisition proposals below)

- Cleared public material is actively used for the non-frozen purposes in ADR-015: training/fine-tuning, training-only calibration fitting, development/tuning, component/base-model/attribute evaluation, selection with contamination/domain caveats, benchmarks, hard negatives, rare cases, failure analysis, regression/challenge, decoder/tracker/adapter tests and vocabulary work. Public origin alone does not imply `REFERENCE_ONLY`.
- The 15 existing `REFERENCE_ONLY` decisions and all other final B0 decisions stay unchanged. A separate approved engineering purpose may be recorded later without changing the original decision, satisfying its own rights/privacy/provenance review and access rules. It does not count towards the closed S1 tally or promote a file to qualification.
- New public discovery requires a **new purpose-specific declaration** for an explicit engineering coverage gap. Do not rerun the closed S1 scopes as continuation of that campaign. Target camera geometry, subject scale, continuous traffic, lighting, density/occlusion, attributes or media-format robustness; generic freshness is not a development requirement.
- Start with roughly 20–30 distinct reviews and at most 5–10 high-value acquisitions, expanding only against documented deficits. These are recommended workload bounds, not adequacy thresholds or implemented limits.
- Screen terms early; perform detailed R-5/rights/privacy review after usefulness is established from existing evidence or permitted previews and before any acquisition/processing/use requiring that permission. ShareAlike is not automatically disqualifying; a model licence determination does not clear footage.
- `DESCRIBED`, `REVIEWED`, `ROLE_ELIGIBLE`, `RIGHTS/PRIVACY_CLEARED`, `ACQUIRED` and `PARTITIONED` are distinct policy facts, not newly implemented states or synonyms for `ADMISSIBLE`/`FROZEN_QUALIFICATION`. The existing helper only acquires `ADMITTED_FOR_PILOT`; a reference decision does not trigger downloading. Follow ADR-015 §2's execution-gap boundary rather than weakening the gate.
- Public and synthetic material cannot enter the final frozen qualification set. Protected commissioned/owner capture must pass ADR-015 §3, including checkpoint/capture chronology, custody, real processing, support, annotation, audits and seal/access separation. Capture alone and an upload date do not establish disjointness.
- Commission non-frozen material only for demonstrated public-data gaps. ADR-015 §6's provisional two-site, three-viewpoint, two-block campaign is about two raw hours, a bounded qualification-candidate proposal only. There is no universal raw-minute minimum; expand only for predeclared support/coverage/independence deficits, never poor candidate results.

The §5 real MAVI processing handoff, per-source original-file hashes, single raw-evidence pin and privacy boundaries remain requirements for operational video. Still-image component evidence is separate and never fabricated into Tracks. The unchanged R1/b-1/b-2 partition and access firewalls remain in force.

**Status.** B0 is **preparation only**. It adds a per-file admission receipt, a Commons-only acquisition seam, and the pilot plan below. It does **not**:
- start Slice B corpus execution;
- acquire any footage (no real discovery or download ran in this pass; see §9);
- create a VideoAsset, Track, Observation, label, ground truth, task freeze or seal;
- close F1;
- train, tune, run or select anything.

Both MSRs remain `PLANNED`, and no model is selected. No candidate gains credibility or shortlist status from source acquisition. Candidate evaluation permission (execution record §4.3.8) stays separate from operational, deployment and licence clearance.

## 1. What "MAVI-acquired operational footage" means

**Historical B0 interpretation.** ADR-015 now excludes public sources from final frozen qualification, permits cleared non-frozen engineering purposes, and replaces any automatic construction-disjointness claim with verified chronology/custody/exposure conditions. The quoted parent wording below is the wording at B0 preparation, since amended in parent §10.2.

Parent plan §10.2 says the qualification corpus is "owner-supplied recorded video … processed through the real MAVI VisionJob". It also says "frozen test is MAVI-sourced, so disjoint … by construction". Hari Om has no private corpus, so B0 reads these clauses as follows:

1. **"Operational" is decided by the processing path, not by who pressed record.** Footage becomes operational corpus material (`corpusKind: operational`) only when it has done both of the following:
   - It has been ingested as a MAVI VideoAsset and processed by the real MAVI detector, tracker and Evidence Set path in a recorded ProcessingRun (§5).
   - It has then passed the S2c corpus tooling, which covers manifest, partitioning, annotation, agreement, adjudication, freeze and seal.

   Acquisition alone makes a file a **candidate source**, never corpus material.
2. **"MAVI-acquired" means the owner, or someone the owner appoints, obtained the exact file bytes, under a recorded right, into the controlled store.** It covers two cases:
   - public files admitted under this record;
   - future commissioned or owner-captured video.
3. **"Disjoint by construction" does not hold for public web video.** Any public file could be in a candidate's training data. For public sources, disjointness is argued from **recorded evidence** (qualification plan §3.1): a reviewed capture interval strictly after the latest candidate checkpoint release date (§4). That argument is weaker than construction. It must be named as such wherever it is used, and it is **not** proof of independence. For example:
   - the same scene may have been published elsewhere earlier;
   - the same camera may have been used before.
4. **Synthetic fixtures never count** as operational F1 evidence. Public benchmark **stills are never turned into MAVI Tracks.** A still has no temporal continuity, so it cannot yield tracker-produced Tracks.

This clarification is an interpretation for review, not an amendment. If R-2 or the owner reads §10.2 as requiring owner-captured footage only, public sources become development or training references only, and the pilot's operational question becomes moot (§6 stop condition S5).

## 2. Cold review of the Astra source categories

For each source category, the table gives a role, a reason and a condition. **Role key:**
- **OPS**: may become operational qualification footage after admission and ingestion.
- **TRAIN**: possible training or tuning source, subject to R-5 licence review. It is never frozen-test material.
- **REF**: development reference bank only (§7).
- **REJECT**: not used.

The licence notes are summaries for R-5 review, not determinations.

### 2.1 Reference/development datasets (stills or tracking benchmarks)

**Historical source-purpose shortlist, not current blanket permissions or exclusions.** The REF/TRAIN restrictions below record the original proposal, not the 63 final human decisions. C+ permits additional separately approved engineering purposes under exact-source rights/privacy/provenance review; age alone does not exclude non-frozen uses. No licence summary here replaces R-5's source-specific determination.

| Source | Nature | Role | Reason and condition |
|---|---|---|---|
| PA-100K | Pedestrian-attribute **stills** | REF; TRAIN only if R-5 clears the licence | Parent §10.2 allows training use subject to licence review, never the frozen test. Stills can never become Tracks. Its research-only terms must be reviewed. A full download is out of scope. |
| PETA | Attribute stills, assembled from other datasets | REF | Mixed upstream provenance and research-only use. Its label scheme differs from the v1 vocabulary. |
| RAP / RAPv2 | Attribute stills from one indoor retail site | REF | Access requires an agreement. It is a single site and indoor, and it does not represent Indian streets. |
| UPAR | Harmonised attribute labels over PA-100K, PETA, RAPv2 and Market-1501 | REF | It inherits every upstream restriction, and its labels are useful for vocabulary mapping only. |
| VeRi-776 | Vehicle re-ID stills (tracklet crops) | REF | Access requires an agreement. Its colour labels need mapping to the v1 vocabulary. It contains crops, not raw video. |
| UFPR-VCR | Vehicle colour recognition stills (Brazil) | REF; TRAIN only if R-5 clears the licence | Useful for colour-vocabulary ambiguity. It is stills only, under an academic licence. |
| UFPR-VeSV | Vehicle model and colour stills (Brazil) | REF | Same as UFPR-VCR. |
| MOT17 / MOT20 | Pedestrian tracking video (CC BY-NC-SA) | REF | NC/SA terms, and the data predates every candidate checkpoint, so it is not fresh. It is useful for tracker sanity checks only. It is never the frozen test. |
| IDD (India Driving Dataset) | Indian road **stills/sequences** from a vehicle dash view | REF | Indian conditions, but a moving dash viewpoint rather than a fixed camera, a registration-based licence, and data that predates the checkpoints. |
| UA-DETRAC | Fixed-camera traffic video (Beijing/Tianjin) | REF | Fixed viewpoint and continuous video, but it predates the checkpoints, is probably in training corpora, and has research-only terms. |
| BDD100K | Dash-cam video (US) | REF | Moving viewpoint, research-only terms, not fresh. |

All of these predate the candidate checkpoints and are widely used in pre-training, so none of them can support the freshness argument. They are never frozen-test or operational material.

### 2.2 Fresh-video candidates

**Historical operational-source proposal.** Commons cannot enter the final frozen test under C+. Commissioning is required there but is insufficient without ADR-015 §3's conditions; construction-disjointness language in this original table is superseded.

| Source | Role | Reason and condition |
|---|---|---|
| Wikimedia Commons (per file) | OPS or TRAIN after per-file admission | It has per-file licences in machine-readable `extmetadata`, a stable revision and SHA-1 identity, and an official API. It is the **only** provider implemented in B0. Admission is always per file and never blanket by category. Capture date must be evidenced beyond the upload date. |
| Taiwan public traffic-camera feeds | Deferred (not in B0) | These are live streams, not files. They would need a recording recipe, a per-feed terms review, a privacy review of the government's publication terms, and freshness by construction (recorded by MAVI after the reference date). That would be a separate slice. It is also non-Indian. |
| Government b-roll (e.g. PIB / Indian ministries, NPS, US agencies) | Candidate for a later provider, if terms are clear | Some are public domain or GODL-style. Terms differ per agency and often forbid implied endorsement. Needs per-agency R-5 review. Capture dates are often undocumented. Not implemented. |
| Commissioned India capture | **Preferred operational source**, owner decision | This is the only route that makes disjointness hold by construction, with controlled consent and signage and chosen sites. It needs owner budget, a capture brief and a privacy basis. Out of scope for B0. It is the fallback if public sources are insufficient (§6). |

### 2.3 Caution or reject

| Source | Role | Reason |
|---|---|---|
| TfL JamCams | REJECT | Terms restrict use and caching. The clips are short, low-rate stills-like loops rather than continuous video, and the data is non-Indian. |
| Pexels / Pixabay / stock | REJECT for OPS; REF at most | The licence is a platform licence rather than a per-work open licence, and the uploader is not necessarily the rights holder. Capture date and model releases are unknown. Stock is staged or curated, which introduces selection bias. |
| YouTube / social media | REJECT | Platform terms forbid downloading. Rights and capture date are unverifiable, and there are privacy concerns. |
| Kaggle mirrors | REJECT | These are re-hosted copies with unclear provenance and licence laundering. Use the original source or nothing. |
| Stills presented as video (slideshows, time-lapse from stills) | REJECT | They are not continuous video, and they cannot produce tracker Tracks. `derive_state` rejects non-VIDEO media. |
| Any file with an unknown capture date | PROVENANCE_PENDING and never OPS | Freshness cannot be established. At most it can serve as TRAIN, and only with a reviewed capture interval. |

## 3. Commons-first design

**Why Commons first.** It is the only candidate that offers all of the following in one place:
- a machine-readable per-file licence;
- an immutable file identity (page revision id plus SHA-1);
- original (non-transcoded) file URLs;
- an official, credential-free API.

Other providers need per-provider terms review before any code is written. B0 does not build a provider abstraction.

**Seam.** The helper is split into four parts:
- `admission.py`: pure rules and the receipt;
- `commons.py`: query builders and metadata parsing;
- `transport.py`: narrow HTTPS;
- `acquire.py`: controlled store.

The helper sits **outside** `tools/qualification/attributes/corpus/`, and a test asserts that the corpus package gained no network imports. See the package README for the states, the receipt fields, the network policy and the store layout.

**Receipt.** There is one canonical receipt per exact file revision and decision, content-addressed by SHA-256. It records:
- provider, file title, page id, revision id, canonical page URL and original URL;
- uploader, author and attribution;
- file licence code, name and URL, with a machine licence class and share-alike flag;
- SHA-256 of the retained metadata response;
- publication time, declared capture text and the reviewed capture interval;
- freshness reference and result;
- declared media properties. Frame rate, time base and discontinuities are `null`, because they are measured at MAVI ingestion.
- pseudonymous site and viewpoint;
- role, requested and effective state, and blockers;
- named reviewers and the rights and privacy reviews;
- acquisition digests.

Receipts contain no credentials, local paths, subject identities or plate text. The operator contact appears only in the User-Agent.

## 4. Freshness reference

`freshnessReferenceDate` is supplied by the reviewer. It is the latest public release date of any candidate checkpoint in the evaluated set (execution record §4.3.11) at the time of review. If a later candidate is added, the reference moves later, and previously admitted operational candidates are re-assessed. They are never grandfathered. The rule is strict:
- the whole capture interval must start after the reference date;
- an interval that straddles the date is `UNDETERMINED`;
- upload time is never capture evidence.

## 5. Ingestion handoff (defined, not executed)

An admitted file enters qualification only through this path. B0 executes none of it.

1. Ingest the retained original from the controlled store as a MAVI **VideoAsset** through the normal import path. The VideoAsset records the measured container properties: frame rate, time base, duration and discontinuities. If these differ materially from the receipt's declared media, stop and reconcile.
2. Run the real detector, tracker and Evidence Set pipeline in a recorded **ProcessingRun**, using the reviewed preparation recipe (§8). Crops come from that run.
3. The corpus manifest source row binds all of the following:
   - `sourceId`;
   - pseudonymous `siteId` / `cameraId` (from the receipt's `siteId` / `viewpointId`);
   - `processingRunId`, `videoAssetId` and `recordingDate` (from the reviewed capture interval);
   - conditions;
   - the receipt SHA-256.
4. Every item carries the ProcessingRun's **Track UUID** and its **Observation** ids, and the **crop SHA-256**. The whole corpus carries exactly **one raw-evidence pin**: the vision pipeline profile SHA-256 recorded by the ProcessingRun, plus the Evidence Set selector and scorer versions (`rawEvidencePin` in `tools/qualification/attributes/corpus/manifest.py`). The pin is not a source-file hash. The retained original's SHA-256 is bound per source through the receipt SHA-256 (step 3).
   *Corrected 2026-10-01: this step previously described the pin as the retained original's SHA-256, which conflicted with `manifest.py`.*
5. Tracks are never synthesised from stills, and crops are never hand-cut outside the pipeline.

## 6. Pilot plan (to be executed by an operator after this PR; not executed here)

**Goal.** Establish whether public Commons video can yield about **1–2 h of usable footage** that meets all three conditions:
- fixed or slow viewpoint showing people and/or vehicles;
- Indian conditions preferred;
- **several independent sites** (target ≥ 4 pseudonymous sites, with no single site above ~40 % of duration).

**Steps.**
1. **Discovery (metadata only).** Run discovery with a small set of pre-declared scopes, fixed **before** any candidate output exists. Target about 40–60 candidate files. Examples:
   - searches such as `traffic India 2026`, `street India 2026`, `pedestrians market India`;
   - categories such as `Category:Videos of streets in India` and `Category:Videos of road traffic in India`, and similar non-India street categories as a secondary pool.

   Scopes are recorded in the operator's run note. A scope is never chosen or changed because of how a candidate performs.
2. **Human review** of the decisions template:
   - rights review;
   - privacy review;
   - capture-interval evidence;
   - role;
   - pseudonymous site and viewpoint.

   Only reviewed items get `state: ADMITTED_FOR_PILOT`. Everything else stays pending or is rejected with a reason.
3. **Acquire** the admitted items only, then run `verify`.
4. **Usability tally** (by a person, from metadata and a visual check only, with no model):
   - duration;
   - resolution;
   - viewpoint stability;
   - subject density;
   - site count.

**Stop conditions.**
- **S1.** 60 candidates are reviewed and fewer than 30 min of admissible `operational-candidate` footage results.
- **S2.** Fewer than 3 independent sites are admissible.
- **S3.** No file can establish `CAPTURE_AFTER_REFERENCE` with medium or high confidence.
- **S4.** Rate limiting or terms prevent metadata access.
- **S5.** The owner or R-2 rules that public sources are not "MAVI-acquired" (§1).

**Acceptable result.** "Public sources are insufficient" is an acceptable, reportable outcome. It is reached at S1, S2, S3 or S5, and it leads to the owner decision on commissioned India capture (§2.2).

**Prohibited.**
- Result-time corpus expansion.
- Candidate-dependent scene selection.
- Bulk download.
- Using admitted footage to tune or select before the corpus freeze and seal.

## 7. Separation rules

**Current amendment:** the original reference-bank restrictions below preserve the B0 campaign's recorded purposes. A separately approved engineering purpose may later use an existing candidate in an appropriate non-frozen pool without changing its immutable human decision. No public item may enter Frozen Qualification. See ADR-015 §1–§2 for pool separation and current tooling boundaries.

- **Reference bank.** `REFERENCE_ONLY` items and every §2.1 dataset stay in a separate reference area of the controlled store. They are never mixed into the qualification source pool. They are never used to fill a partition, and they never count towards the 1–2 h target.
- **Annotation boundary.** Acquisition writes no label, vocabulary decision or ground truth. Annotation starts only in Slice B under the annotation guide, on crops produced by the handoff (§5). Candidate outputs never influence ground truth.
- **Frozen test.** Nothing in B0 assigns a partition. Frozen-test imagery and ground truth remain outside candidate environments, and selection candidates never see frozen-test labels. Those rules are unchanged.
- **Privacy.** The following rules apply:
  - no face recognition, no plate OCR and no subject identification;
  - site and viewpoint ids are pseudonyms;
  - receipts contain no place names and no identities of filmed subjects;
  - an open copyright licence does **not** settle privacy, so a separate named privacy review with a basis is required for admission;
  - the privacy reviewer may reject footage with identifiable close-range faces or legible plates if they judge it inappropriate.

## 8. Preparation-recipe binding

The ingestion handoff (§5) must name the reviewed preparation recipe (Slice B). The recipe covers:
- decoder and frame sampling;
- detector and tracker configuration;
- crop geometry and padding;
- admissibility floors, where those are fixed rather than tuned.

The corpus manifest records the recipe digest. B0 binds nothing yet, because the recipe does not exist. Footage acquired under B0 is recipe-agnostic raw material.

## 9. Validation performed and deferred

**Offline tests.** `tools/qualification/tests/test_source_acquisition.py` uses a fake transport and covers:
- admission rules;
- time separation;
- licences;
- the network rules;
- integrity;
- idempotency;
- store placement;
- package separation.

The mutation results are in the PR.

**Live metadata validation deferred.** During development the Commons API returned HTTP 429 to this container on the second request. The parser was therefore built against the documented `imageinfo` / `extmetadata` / `revisions` response shape, and it was **not** confirmed against live responses. The first operator discovery run is the live check. If any field differs, the operator stops and files a fix before acquiring anything. The helper backs off on 429 and sends a descriptive User-Agent with an operator contact, as Wikimedia's policy asks.

**Windows.** It was tested on Linux only. Windows compatibility is not claimed. In particular, hard-link promotion (`os.link`) needs NTFS and the same volume.

## 10. Open human inputs

| Input | Owner |
|---|---|
| Operator contact for the User-Agent and the controlled-store location for source media | Owner / R-1 |
| Named rights reviewer (R-5 or delegate) and named privacy reviewer | Owner |
| `freshnessReferenceDate` for the current candidate set | R-1, from §4.3.11 evidence |
| Acceptance of the §1 interpretation | R-2 / owner |
| Decision on commissioned India capture if the result is "public sources insufficient" | Owner |

**Update 2026-10-01** (`s2c-owner-decisions-2026-10-01.md`):
- The controlled locations for source media and acquisition records are designated (§3 of that record). How acquired media reaches the source-media location, given the helper's single store root, must be decided before any `acquire`. Layout A is selected (amendment in §7 of that record): the persistent acquisition store is `E:\MAVI-Controlled\SourceMedia\S2c\2026-01\commons-store`.
- Hari Om is named footage rights reviewer and footage privacy reviewer. Per-file reviews are still required, and share-alike or other licence-interpretation questions go to R-5 first.
- `freshnessReferenceDate`, acceptance of the §1 interpretation, the operator contact and the commissioned-capture decision remain open. Proposals for the first two are in §6 of that record.

## 11. Dependencies

There are none. The helper uses the Python standard library and the in-repo corpus canonicaliser. `config/dependencies/offline-dependency-policy-v1.json` is unchanged. The helper is Development tooling with network access, run by an operator, and is not part of the Internet-independent production runtime. `tools/verify_repo.py` now also refuses tracked `.webm`, `.ogv`, `.ogg`, `.mpg` and `.mpeg` files, and treats `tools/qualification/source_acquisition` as a private-evidence area, so no image may be tracked there.
