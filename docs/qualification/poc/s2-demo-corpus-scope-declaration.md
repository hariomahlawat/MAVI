# PoC S2 — demo corpus: predeclared discovery scopes and selection rules

**Status:** recorded and committed **before any search or metadata request**. The commit that adds this file is the scope declaration; the discovery run cites its hash. Changing a scope or rule after discovery starts requires an amendment section below with a reason. Nothing may be silently re-scoped.

**Governing:** plan `docs/superpowers/plans/2026-10-28-mavi-poc-end-to-end.md` §4 S2 and D3 (on `poc/s0-decisions`, PR #237); register rows B1–B5 in `docs/reviews/2026-10-28-poc-acceptance.md`; ADR-017; `AGENTS.md` "Data, benchmarks and annotation"; `tools/qualification/source_acquisition/README.md`.

**Operator:** a Claude Code session (PoC S2), on the owner's instruction of 2026-10-28. The owner sources no data; the operator does the discovery and records determinations. The operator is not an independent reviewer; owner acceptance of the attribution file (register B2) is the owner's ratification of the corpus.

## 1. Purpose (ADR-017 step 1)

Demonstration media for the PoC: 8–12 recorded, fixed-camera clips on which the PoC demo exercises import, tracking, Stage-1 scene analytics (zones, trip lines, dwell, restricted bays), plates (best effort), embeddings, zero-shot attributes and face coverage measurement. **This corpus is not a benchmark, not qualification evidence and not training data.** No label, annotation or ground truth is created (B5). Any capability number later measured on these clips is Development-grade demo evidence only.

**Reuse first (ADR-017).** No established labelled benchmark is a substitute: the demo needs *redistributable* clips the kit can ship. BDD100K (research licence) and the H3 plate sequences are already held for owner-machine live demos (D3) and are not re-acquired here. Kit media must be CC0 or CC-BY (D3).

## 2. Provider and tool

- Provider: **Wikimedia Commons only**, via `tools/qualification/source_acquisition` (`discover`, then `acquire --purpose-approvals`). It is the only provider the tool implements; its network policy (HTTPS, allow-listed hosts, provider SHA-1 verification) applies unchanged.
- Pexels / Pixabay: **not used in the first pass.** They are an owner-machine-only fallback (D3) for a scene class that Commons cannot fill, recorded as an amendment with the reason, retained in a separate `owner-machine-only` folder that never enters the kit.
- Controlled store: `E:\MAVI-Controlled\PoC\Corpus\` (outside Git). Layout: `source-store\` (the helper's `--store`), `derivatives\` (trimmed clips), `manifests\` (SHA-256 manifests), `owner-machine-only\` (empty unless the fallback is used).

## 3. Discovery scopes (fixed)

Each scope is one `discover --search` call (the helper prefixes `filetype:video`) with `--limit 40`, run once, in this order. No other search, category or title lookup is made in the first pass.

| Scope | Search text | Scene class sought |
|---|---|---|
| Q1 | `traffic intersection` | road junction |
| Q2 | `traffic junction` | road junction |
| Q3 | `toll plaza` | gate with vehicles / plates |
| Q4 | `vehicles entering gate` | gate with vehicles / plates |
| Q5 | `parking lot` | car park |
| Q6 | `car park` | car park |
| Q7 | `pedestrian crossing` | pedestrian area |
| Q8 | `pedestrians walking street` | pedestrian area |
| Q9 | `lobby people walking` | lobby / close range, faces |
| Q10 | `railway station concourse people` | lobby / close range, faces |
| Q11 | `surveillance camera footage` | any class |
| Q12 | `timelapse traffic` (excluded at selection unless real-time) | road junction |

## 4. Selection rules (applied in this order)

1. **Licence (file's own page, `extmetadata`).** Kit-eligible only: `cc0`, `cc-by-2.0`, `cc-by-2.5`, `cc-by-3.0`, `cc-by-4.0`. Excluded from the kit: CC-BY-SA (all versions), PD marks other than CC0, GFDL, NC, ND, unknown. A PD-marked file is not CC0 and is excluded under D3.
2. **Technical.** Continuous video (helper rule); duration ≥ 60 s; frame size ≥ 640×360; author named.
3. **Viewpoint.** Fixed (static) camera for the usable span. Screened first from title/description; then a diagnostic look at three frames (start, middle, end) — *rationale: confirm the viewpoint is static so polygon/line geometry stays valid; no labels or counts are produced.* Real-time only (no time-lapse, no edits/cuts in the trimmed span).
4. **Faces (B3).** A clip selected for the face demo, or in which faces are recognisable at close range, is admitted only if CC0 or the page states a model release. Distant, incidental, non-recognisable passers-by in a CC-BY street scene do not make a clip face-bearing; the privacy basis is recorded per determination.
5. **Coverage.** Target 10 clips, minimum 8, maximum 12; at least 3 junction/gate, 1 car park, 2 pedestrian, 1 lobby/close-range. Within a class, prefer: longer real-time span, higher resolution, visible plates (gate/junction), more people/vehicles in frame, distinct site. At most 2 clips from one uploader per class.
6. **Trim.** 1–3 minutes per clip from the original, with the repository's pinned FFmpeg and a recorded deterministic command. Originals are retained unchanged.

## 5. What is never done

No label, box, count, identity, ground truth or annotation is created; no model output is read during selection; no bytes, crops or frames enter Git; no biometric derivative is created in S2.

## Amendments

(none)
