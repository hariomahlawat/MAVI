# Stage 4 — O1A: Indian Native-Frame-Rate Tracking/Association Diagnostic on IDD-X (design)

**Date:** 2026-10-13. **Status:** PROTOCOL (Development), frozen at commit. Nothing has been downloaded and nothing has run.

**Class:** bounded Development diagnostic. It changes no profile, tracker, threshold or frozen result.

## Owner decisions this design follows (2026-10-13)

1. **O1 is split:**
   - **O1A** — Indian native-frame-rate tracking validation;
   - **O1B** — Indian ANPR/OCR validation.
2. **IDD-X is approved for O1A only.** The distributed data has **blurred licence plates**, so it is excluded from O1B.
3. **Permission.** The organisation has research/academic permission under the IIIT Hyderabad collaboration. That permission does not restore the missing plate pixels.
4. **O1B stays OPEN.** The search continues for an admissible Indian video source with visible plates, or for a bounded, purpose-built Indian research corpus. Under plan §3.3, O1B blocks neither PR #213 nor PR-3: "it does not block PR-1 or any other PR". PR-2's entry criterion §4.2 item 3 needs an Indian **still** dataset, not video.
5. **No full 160 GB download.** First define the smallest subset and confirm that the archive allows selective acquisition.

## Question

The O3 root cause found that 14 of the 77 oracle-readable vehicles were lost before evidence:
- tracker fragmentation 6;
- low detector confidence 4;
- association floors 4.

All of these were measured at **5 fps** (BDD100K's labelled rate). O1A asks two things:
- **(a)** Are these losses a 5 fps artefact? That is, does MAVI's unchanged release-profile tracker hold vehicle identity better at native 25 fps?
- **(b)** How does detection-and-tracking behave in dense, heterogeneous Indian traffic (two-wheelers, autorickshaws, buses)?

This evidence is the owner's stated prerequisite for any tracker change.

## Design

**Data.** IDD-X front view, 2560×1440 at 25 fps. Ground truth is IDD-X's CVAT tracks of **important objects**: per-frame boxes at 25 Hz over each driving scenario.

**Vehicle categories:**

| IDD-X category | Treatment |
|---|---|
| car, bus, truck, motorcycle | `exact` mapping to MAVI's Vehicle capability |
| autorickshaw | `subset` mapping: it is a Vehicle with no COCO class, and is reported as its own stratum |
| bicycle, person/animal, speed breaker, damaged road, others | excluded |

All mappings are declared under ADR-017 §4.

**One causal difference, at no extra cost.** The detector is per-frame, so a 5 fps detection set equals the 25 fps set at every fifth frame. The method mirrors X1, whose replay determinism is already established.
1. **Live (25 fps).** Run the qualified runtime through the worker's own composition on each selected clip, recording every per-frame detection.
2. **Arm N, native.** Replay all recorded detections through the release-profile ByteTrack at 25 fps.
3. **Arm D, decimated.** Replay the detections of every fifth frame at 5 fps, with the same tracker and the same profile. The decimation is deterministic: frame indices ≡ 0 mod 5.

Detection is therefore identical by construction, and any difference between the arms is the tracker's frame-rate behaviour.

**Clips.**
- Each annotated scenario interval, plus a 2 s pre-roll (so a Track can be established before the ground truth starts) and a 1 s post-roll.
- Only scenario frames are labelled instants. MAVI points outside them are not evaluable.
- This must be checked against the association code's §7.1 evaluable-point rule before freezing.

**Association and metrics** use the frozen `vehicle-tracks-association-v1` policy, unchanged. Each arm uses its own labelled rate: 25 Hz for N, and every fifth frame for D.

**Ground-truth side only.** IDD-X does not annotate non-important vehicles. MAVI Tracks on unannotated vehicles are therefore not false positives, and precision, IDF1 and MOTA are **not** measurable. Per ground-truth vehicle Track, per arm:

| Metric | Definition |
|---|---|
| **Association outcome (primary)** | matched / `fragmentedGt` / `unverifiedGt` / `unmatchedGt` / `ambiguousGt` / `mergedGt`. Primary metric: the **matched rate**, plus the **fragmentation rate** |
| Fragmentation count | number of distinct MAVI Tracks contained on the ground-truth Track |
| Identity switches | changes of the containing MAVI Track along the ground-truth Track |
| GT coverage | the policy's `gtCoverage` |
| **Continuity** | the policy's `longestContainedRun` as a fraction of the ground-truth Track length, and the number and length of gaps (ground-truth frames with no containing MAVI point) |
| Detection support (diagnostic, arm-independent) | detector recall below; also the share of ground-truth frames whose best detection is in the low-confidence band (0.1–0.6), which ByteTrack can only use for second-stage association |
| Detector recall (diagnostic, arm-independent) | share of ground-truth frames with a detection at IoU ≥ 0.5, at any confidence and at the tracker thresholds (0.6 high, 0.7 activation) |

**Comparison:**
- arm N vs arm D, paired per ground-truth Track;
- 95 % intervals by cluster bootstrap over videos (MSR §8.1);
- the paired matched-rate difference, with an exact McNemar test on discordant tracks.

**Comparison against the BDD 5 fps observations (O3).**
- The same per-Track metrics are computed on the frozen BDD100K H3 association `bea73d13…` (5 fps, 200 sequences) for every ground-truth vehicle Track. These are descriptive reference distributions:
  - matched, fragmented and unmatched rates;
  - continuity;
  - detection support.
- Three readings follow:
  - **Arm D (IDD-X at 5 fps) vs BDD at 5 fps** separates domain (Indian dense traffic) from frame rate.
  - **Arm N vs arm D** is the frame-rate effect on the same Indian data.
  - If the fragmentation share at 5 fps is similar in both datasets, and arm N removes most of it, then the O3 tracking losses are a 5 fps artefact. If arm N does not, there is real tracker weakness.
- No pooled verdict is formed across the datasets.

**Strata:**
- category (car / two-wheeler / autorickshaw / heavy);
- day vs night;
- ground-truth Track length (< 3 s vs ≥ 3 s);
- density (number of detections per frame, in tertiles).

**Support floor.** Use the frozen protocol's 50 tracks: no stratum is interpreted below 50 ground-truth Tracks.

**Freeze before results.** This document is the O1A Development protocol. Its SHA-256 is recorded in the register when committed, and any later change needs a dated revision recorded before the results it governs.

**What O1A does not do:**
- it changes no tracker parameter;
- it reads no plate (plates are blurred);
- it never feeds an E-A, E-B, P3 or O1B result.

## Minimum IDD-X subset

**Unit:** the validation split, front view, scenarios at least 2 s long (50 frames) containing at least one vehicle-category important-object Track at least 1 s long (25 frames).

**Target:**
- **≥ 200 ground-truth vehicle Tracks**, giving the 50-track support floor in each main stratum;
- drawn from **≥ 30 distinct videos**, so the cluster bootstrap is meaningful;
- selected deterministically: sorted by video id, with a fixed seed for any sub-sampling.

**Estimated size.** The paper reports 85 h, 1,140 untrimmed videos and about 8.7K important-object Tracks (6.4K front). The listing is 160–171 GB, so about 140 MB per dual-view video.
- About 5 front vehicle Tracks per video means roughly **40–60 videos**.
- Front view only, that is **about 4–8 GB**, plus the annotations.
- Only scenario intervals with their pre- and post-roll are processed. The rest of each video is never decoded.

**Acquisition order (each step is the owner's or the portal's to confirm, never assumed):**
1. **Owner (logged-in portal):** list the IDD-X archive structure. Are videos per file or per split archive, are the front and rear views separate, and is there an annotations-only package?
2. **Download the annotations only** (expected to be small) and register their hashes (ADR-017 record).
3. **Run the deterministic selection** on the annotations and produce the video list.
4. **Download only the listed front-view videos** and hash them on arrival.

**If the portal offers only the monolithic archive:** stop. Ask the provider, under the IIIT collaboration, for the selected subset, or for the annotations first. Do not download 160 GB.

## Licence and handling

- India Data DUA: research use, non-commercial, DPDPA 2023, attribution.
- The organisation holds research permission under the IIIT collaboration.
- Bytes stay under `E:\MAVI-Controlled\Benchmarks\idd-x\…`, outside Git, never redistributed.
- Faces are personal data: only boxes and scalar results leave the controlled store.
