# ADR-015: Public-first Development, Protected Final Qualification

**Status:** Accepted owner policy for Stage 2 S2c, on Hari Om Ahlawat's instruction of 2026-10-02; documentation adoption only. Required independent execution reviews and tooling enforcement remain prerequisites, not completed by this decision.

**Date:** 2026-10-02

**Related:** ADR-013; ADR-014; the Visual Attributes qualification plan, revisions R1–R4; the S2c parent/execution plans; the B0 and owner-decision records.

**Prospective refinement (2026-10-04):** ADR-017 governs Development benchmark and data-reuse strategy from that date. Public research benchmarks are strategic Development evidence; established labelled benchmarks are preferred before new labels; and under ADR-017 §7, ambiguity in research-use terms is recorded rather than treated as a block on Development, so a perfect affirmative rights record is no longer a precondition for Development use of research-accessible data. Explicit prohibitions, payment and access controls still block. This ADR's historical C+ decision, its purpose pools (§1), its frozen-qualification admission contract (§3) and its sequencing (§4) are unchanged; §5's two-stage rights review remains the procedure for frozen-qualification and operational-role sources.

## Context

The owner adopts **C+ — Public-first development, protected final qualification**. Public sources are valuable for learning and engineering even when independence from upstream checkpoint training cannot be established. The original B0 public operational-feasibility campaign is closed under S1: 63/63 candidates reviewed, 38 `REJECT_OPERATIONAL_QUALIFICATION`, 15 `REFERENCE_ONLY`, 10 `REJECTED`, and 0 operationally admissible seconds. Nothing is `ADMISSIBLE` or `FROZEN_QUALIFICATION`. These are the owner's verified closure inputs; the signed workbook and discovery evidence remain outside Git. This decision neither rewrites those inputs nor admits footage.

The alternatives in the owner-decision record §6.2 are historical proposals. A allowed public operational material with weaker disjointness; B excluded public operational material; C allowed public training, tuning and selection while reserving the frozen test for commissioned/owner capture. C+ adopts that separation and makes useful public acquisition the default development strategy. Commissioning alone establishes neither independence nor representativeness.

## Decision

> Adopt C+ — Public-first development, protected final qualification. Actively use cleared public material for training, fine-tuning, calibration, development/tuning, base-model and component/attribute evaluation, model/component selection, public benchmark comparison, hard-negative mining, rare-case supplementation, failure analysis, regression/challenge, decoder/tracker/adapter tests and vocabulary/ontology development. Reserve FROZEN_QUALIFICATION for eligible protected newly commissioned or owner-captured real video. Commission non-frozen footage only where public material leaves a demonstrated operational gap. Preserve the closed B0 S1 campaign and all 63 human decisions unchanged.

Public origin alone does not imply `REFERENCE_ONLY`. Permission depends on the intended purpose, exact source/release, rights, privacy, provenance and exposure history. Public selection is allowed with explicit contamination and domain caveats; add a small private selection set only when preparation establishes a genuine operational-domain gap. No claim of independent comparative generalisation follows merely from a public selection score.

This policy prospectively supersedes conflicting public-source, automatic-disjointness and capture-volume guidance in B0, the S2c parent plan §10.2 and earlier pilot proposals. It does not amend b-1/b-2 numerical/statistical semantics, M2 ordering, evidence classes, Production gates, role independence or existing machine schemas. Specific datasets still require their own permission; this decision is not a licence ruling.

## 1. Purposes, partitions and evidence levels

| Pool | Permitted purpose | Boundary |
|---|---|---|
| Training | Fit heads/weights, fine-tune, fit calibration on training-derived group-disjoint predictions; hard-negative/rare-case supplementation | No fitting on tuning, selection or final-test data; respect the approved training recipe |
| Development/Tuning | Debug on development material; choose permitted operating parameters, thresholds and pooling/aggregation values on separate tuning groups | Development exposure is recorded; selection labels cannot tune; calibration coefficients remain training-only |
| Public Benchmark/Reference | Published comparisons, references and vocabulary/ontology work | Preserve published benchmark splits; do not report training-set reuse as an independent benchmark result |
| Selection | Compare already-frozen executables on separately assigned groups; public data allowed with exposure/domain limitations | No fit, tuning, scope change or adaptive search after selection access |
| Qualification Candidate | Sources being reviewed for a specified operational role | A candidate is not admitted or sealed; public non-frozen selection eligibility is distinct from frozen eligibility |
| Frozen Qualification | Authorized final evaluation of the selected frozen identity, after the existing S2c closure/S5 prerequisites | Only eligible protected commissioned/owner capture; no development, tuning or selection access |
| Regression/Challenge | Known failures, difficult cases and lawfully retained exposed tests | Useful engineering evidence, not independent final qualification |

Maintain the existing separate label-free engineering-calibration and held-out E3 traces. Neither may use the sealed quality test, and E3 is not S5.

Still-image data may support component training/evaluation, with a separate source/training manifest. It does not create a Track, satisfy an operational camera floor or demonstrate continuous-video processing. Track-level evidence requires actual temporal Tracks. End-to-end qualification requires original real video through MAVI's VideoAsset, ProcessingRun, detector/tracker and Evidence Set path. Synthetic data may support development and functional tests, never frozen operational qualification.

Assign whole site/date blocks and preserve duplicate/recurrence groups. Promotion requires a separately recorded purpose approval and compatible access history. Material exposed for training, development, tuning, selection or challenge work cannot become an unexposed frozen test by changing its label.

## 2. Policy concepts versus implemented states

`DESCRIBED`, `REVIEWED`, `ROLE_ELIGIBLE`, `RIGHTS/PRIVACY_CLEARED`, `ACQUIRED` and `PARTITIONED` describe separate policy facts. They are not interchangeable with `ADMISSIBLE` or `FROZEN_QUALIFICATION`. Their use here creates no runtime enum, schema field or state transition. The review-inventory tool implements only its documented description/status surface; the acquisition helper retains its existing states, including `ADMITTED_FOR_PILOT` and `REFERENCE_ONLY`.

The current helper downloads only `ADMITTED_FOR_PILOT` items. It does not acquire an item merely because it is `REFERENCE_ONLY`. A separate approved engineering purpose for an existing file must retain the original human decision and identify exact bytes, intended use and clearance. No operational reject is converted to another B0 state. A rights/privacy rejection is not bypassed by calling an asset a negative example. Policy permission does not authorize a CLI path that the current tooling refuses.

The partitioner currently selects held-out sites/date blocks without a commissioned/public eligibility gate. Its `excludedFromFrozenTrackIds` moves affected frozen clusters to training, not arbitrary tuning/selection destinations. Before a mixed-source operational corpus is partitioned/sealed, a separately reviewed execution mechanism must enforce C+ reproducibly while retaining site/date grouping and existing audits. A passing current validator alone does not certify C+ provenance, chronology or source eligibility. No code is changed by this ADR.

## 3. Frozen qualification admission contract

`FROZEN_QUALIFICATION` eligibility requires all of:

1. An approved qualification event, operating envelope and versioned protocol.
2. Newly commissioned or owner-captured continuous real video; no public-source or synthetic final-test footage.
3. Verified capture provenance, original-file identity and chain of custody. Capture records identify the operator, authorized site, camera/viewpoint, device/settings, clock basis and UTC capture interval; sensitive locators stay in restricted records. File hashes establish integrity, not the truth of capture claims.
4. Verified chronology relative to every exact pinned pretrained checkpoint identity in the evaluated set. The whole capture interval starts after those checkpoint bytes were pinned and after the approved event freshness reference. Upload dates or paper dates alone cannot establish this. Missing checkpoint chronology or conflicting capture evidence blocks eligibility.
5. Purpose-specific rights permission and named privacy approval covering acquisition, processing, crops/labels, retention and controlled audit access; redistribution is assessed separately.
6. Deployment-representative continuity, viewpoint and technical criteria, with numeric usable-duration and support requirements predeclared through the approved preparation/support recipe before final scoring. No universal raw-minute threshold is established here.
7. Real MAVI processing and authoritative source/crop provenance. The custodian copies the actual profile SHA-256 and selector/scorer versions from ProcessingRun into the single raw-evidence pin; schema validation does not authenticate that provenance.
8. Resolved exact/near-duplicate and cross-partition recurrence issues under the existing audits; no unresolved prohibited overlap with training, development, tuning, selection or exposed tests.
9. Verified access separation and prior-exposure history, including originals, derivatives, imagery, labels and results.
10. Required independent annotation, agreement/adjudication and adequate attribute/independent-cluster support; a valid frozen member/ground-truth seal and access history.

Missing or conflicting evidence leaves eligibility pending; it never produces automatic admission, F1 PASS, a valid seal or a qualification pass. The current three-camera-per-partition and unseen frozen-camera floors remain requirements, not statistical adequacy. Human attestations remain external trust inputs.

## 4. Capture and evaluation sequencing

Protected holdout video may be physically captured **before final executable freeze** if it remains sealed in controlled custody and inaccessible to development/selection. During capture preparation, retain originals and hash manifests under that isolation; this is not a claim that the corpus annotation seal already exists. The annotated corpus seal still follows R1 before candidate execution on corpus data.

The operational sequence is:

`public/private development` → `training/tuning` → `selection protocol fixed` → `candidate executable(s) frozen` → `selection on separate data and implementation choice` → `authorized access to protected final holdout` → `final qualification`.

The preparation recipe, method families and bounded search procedures are fixed before training as required by R1; the final selection protocol binds actual trained artefact hashes before selection access. The existing S2c owner-choice, integration/E3 and CLOSED prerequisites remain before S5 final-test access. This ADR authorizes no scoring during S2c and no candidate replacement after a failed final test.

If developers use final-test imagery, labels or results to change the system, that test is exposed and becomes regression/challenge evidence, subject to its permissions. A new independent holdout is required for a new final qualification claim. Preserve the compromised seal/access history and use the existing version/supersession protocol; do not relabel and reseal the same exposed Tracks. Model/component upgrades require event-specific eligibility and requalification review, not an inherited corpus-independence claim.

## 5. Public acquisition and rights economics

The original B0 S1 campaign stays closed. Any new public discovery requires a **new purpose-specific declaration** fixed before outputs: intended use, coverage deficit, sources/scopes, budget and stop rules. Target fixed/elevated viewpoints, useful pedestrian scale, continuous traffic, day/night, occlusion/density, bag/backpack/headwear, vehicle colour or codec/resolution/frame-rate robustness. Historical public material remains useful outside final qualification; generic upload-date freshness is not a development admission rule.

Recommended initial workload: review roughly **20–30 distinct candidates**, acquire at most **5–10 high-value files**, and expand only against a documented coverage deficit. These are workload bounds, not adequacy thresholds, implemented limits or permission to download. Stop when marginal coverage value is low, duplicates dominate or the declaration's effort/budget is exhausted. Deduplicate exact bytes, reposts, overlapping excerpts and related scene/subject groups before partitioning.

Rights review has two stages:

1. Screen published terms early to eliminate obviously incompatible or unverifiable sources.
2. After technical usefulness is established through existing evidence or permitted previews, obtain detailed R-5/rights/privacy review before any acquisition, processing or use requiring that permission. Use a release-level determination only where its scope genuinely covers the selected files and uses.

ShareAlike is not automatically disqualifying. R-5 determines the exact obligations for the intended private processing, adaptations, labels and any redistribution. Do not assume a platform listing, code licence or public availability grants all needed footage rights or settles privacy. Existing R-5 model determinations do not automatically clear footage.

## 6. Bounded protected-capture campaign

No universal minimum in raw minutes is currently justified. The earlier roughly ten-hour proposal is historical planning guidance, not a requirement or a permanent minimum. Public material should carry most preparation/development work. Commission non-frozen footage only for a demonstrated operational gap.

A provisional first **qualification-candidate** campaign may use two independent sites, three genuine deployment-style viewpoints per site, two separate day/night recording blocks, and about ten minutes per viewpoint/block: approximately **two raw hours**. Recording blocks are mapped to the approved contiguous date-block policy; two sessions inside one date block are not two independent clusters. This is a bounded acquisition proposal, not authorization, a frozen corpus, statistical adequacy or a claim of broad site generalisation.

Expansion is driven only by predeclared deficits: independent clusters/sites, attribute support, required operating conditions, recurrence/duplication or statistical precision. Add sites where independence is deficient rather than merely more minutes at one camera. Custodian-only support checks must not expose frozen labels/results to selection work. Never expand a frozen corpus merely because a candidate performed poorly; a sealed revision follows the existing review/version protocol and preserves its predecessor.

## Consequences and open execution items

- Preserve the original S1 closure and all 63 final human decisions. An existing candidate may later receive a **separate approved engineering purpose** without changing that immutable B0 decision. The 15 `REFERENCE_ONLY` decisions remain exactly that; neither they nor operational rejects automatically acquire training or selection permission.
- Retain public sources as strategic engineering resources, but distinguish component, Track and end-to-end claims and disclose public-selection exposure/domain limitations.
- Complete required independent reviewer assignments, event numerical/support inputs, checkpoint chronology, rights/privacy decisions and custody arrangements before execution. Owner policy adoption is not independent R-2/R-7 review.
- Review future tooling changes for purpose-specific reference acquisition and mixed-source partition enforcement separately. Until an execution path satisfies both C+ and existing gates, it remains blocked; do not weaken a validator or claim unimplemented enforcement.
- No media acquisition, discovery, training, annotation, runtime change, acceptance-row change or Production promotion is performed or authorized by this documentation change.
