# Stage 4 — Sharpness-Floor Diagnostic at Large NearView Crops (owner decision, 2026-10-13)

**Class:** bounded Development diagnostic, **measurement only**. The release profile, the selector, `sharpnessFloor` (0.05) and every frozen acceptance criterion are unchanged. This document describes; it does not decide.

**Question:** why can visibly useful large plate views fall below the generic 0.05 sharpness floor?

## Method

**Tool:** `tools/benchmarks/plates/sharpness_study.py`.

**Output:** `E:\MAVI-Controlled\Benchmarks\stage4-x1\sharpness-study.json` (`f9930bca…`).

| Input | Hash |
|---|---|
| X1 baseline arm index | `98b1f7d3…` |
| Baseline E-B evaluation | `903b9813…` |
| Frozen truth | `709a560b…` |
| Frozen descriptor | `7169263a…` |

**Population: 251 frames.** A frame is included when all of these hold:
- it is a labelled frame of a matched ground-truth vehicle;
- its text-usable plate is at least `h_min` = 32 px;
- the matched MAVI Track has a candidate at that frame.

**"Readable"** means a pinned instrument reads the plate exactly at that native frame (the E-B oracle read).

**Production metric.** `sharpness = mean |∇grey| over the whole vehicle box / 64` (`quality/scoring.py`). Its values here are the selector's own per-candidate records on the processed video frames. The image-path recomputation on the source JPEGs agrees with them to a median of 0.0002 (max 0.0009).

## Results

| | Frames | Readable | Readable but below the floor |
|---|---|---|---|
| All | 251 | 230 | **26 (11.3 % of readable)** |
| Area tertile: small (≤ 0.142) | 84 | 77 | 9 |
| medium | 83 | 74 | 4 |
| large (> 0.183) | 84 | 79 | **13** |

1. **The floor is a weak readability discriminator.**
   - Below the floor: 31 frames, of which 26 (84 %) are readable.
   - At or above the floor: 220 frames, of which 204 (93 %) are readable.
   - Its main effect on these near, large-plate frames is to exclude useful views.
2. **Dilution by the vehicle box.** In the 26 readable-but-failing frames:
   - the median box sharpness is 0.040;
   - the **plate region alone** has a median of **0.099**, and **25 of 26 are at or above the floor**.

   The plate is sharp. The metric averages it with large low-texture areas (bodywork, glass, shadow), which dominate a near box.
3. **Scale dependence.** The metric is a mean per-pixel gradient, so it falls as the same object occupies more pixels.
   - **Within a Track,** sharpness falls as the box grows. Across 3,076 Vehicle Tracks with at least 10 candidates, the median Spearman ρ(area, sharpness) is **−0.67**, and it is negative in **88 %** of Tracks.
   - **Rescaling the same 26 crops:**
     - to a fixed 128-px height, **19 of 26** reach the floor (median 0.067);
     - at half scale, 17 of 26 do (median 0.055).
   - The median selector sharpness falls from 0.075 (small) to 0.063 (large) across area tertiles.
4. **Consistency with X1.** Five of the ten selection failures are blocked at their best plate frames by sharpness, alone or together with edge contact. One of them (00121309) is blocked by sharpness alone, at 69–72 px plates. This matches the mechanism above.

## Interpretation (no decision implied)

`sharpnessFloor` applies one fixed, scale-dependent, whole-box mean-gradient threshold. On near vehicles that design penalises exactly the views with the largest plates, for two reasons:
- **resolution:** the same edges are spread over more pixels;
- **content:** the plate is a small textured part of a large smooth box.

**What the evidence does and does not show:**
- It **does not** show that a lower floor would be safe. The failing set also contains 5 unreadable frames, and this study measured no blur, false-qualification or encode-cost effects.
- It **does** indicate that any revision should be **scale-normalised**, for example computing the metric at a fixed working resolution, rather than simply lowering the threshold. A plate-region measure would be plate-aware selection (X3), which the owner has excluded at this stage.

**Any change is a pipeline-profile change** with requalification consequences (ADR-013 §6, ADR-009), and it needs a separate owner decision. PR-6 stays held.

## Limitations

- **Domain and labels:** BDD100K dashcam footage at 5 fps, under the frozen R8 labels.
- **Population:** limited to matched tracks at labelled frames with plates of at least 32 px. It says nothing about Person evidence or unlabelled tracks.
- **Single blur measure:** the study uses the production metric and its rescaled variants only. No independent blur ground truth was used.
